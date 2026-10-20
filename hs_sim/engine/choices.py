"""Choice suspension and resumption; no Python stack is retained between actions."""
from dataclasses import replace

from .model import ChoiceResult, PendingChoice
from .errors import ResolutionError, ResolutionLimitExceeded


def request_choice(r, effect):
    from .continuations import FrameCodec
    r.player(effect.player_id)
    if r._choice_request is not None or r.state.pending_choice is not None:
        raise ResolutionError('A resolution can request only one choice at a time')
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Choice source does not exist')
    # Check every candidate, including candidates that sampling might omit.
    codec = FrameCodec(r.game.mechanics, r.registry)
    codec.decode(codec.encode(effect))
    for option in effect.options:
        if option.entity_id is not None and option.entity_id not in r.state.entities:
            raise ResolutionError('Choice option entity does not exist')
    if effect.kindred is not None:
        from .kindred import validate_preparation
        validate_preparation(r.state, r.registry, effect.kindred)
    offered = effect.sample_size if effect.sample_size is not None else len(effect.options)
    if offered > r.rules.max_choice_options:
        raise ResolutionLimitExceeded('Too many offered choice options')
    options = effect.options if effect.sample_size is None else tuple(r.game._rng.sample(effect.options, effect.sample_size))
    choice = PendingChoice(r.state.next_choice_id, effect.player_id, effect.source_id, effect.prompt,
                           tuple(o.item for o in options), effect.min_count, effect.max_count, effect.purpose, effect.repeat_key)
    r.state.next_choice_id += 1
    if effect.kindred is not None:
        # This finite profile is automatic; no additional pending-frame state.
        # Preserve the original immutable activation across the sampled callback.
        from .spell_repeats import remember_choice
        result = ChoiceResult(choice, ())
        remember_choice(r.state, result)
        r.emit('choice_skipped', source_id=choice.source_id, player_id=choice.player_id, choice_id=choice.id)
        return choice_effects(r, result, options, effect.on_select, kindred=effect.kindred)
    from .discovery_summons import bind_choice
    bind_choice(r,choice,options)
    from .hand_choice_followups import bind_choice as bind_hand_followup
    bind_hand_followup(r, choice, options)
    from .discovery_offers import capture as capture_discovery_offer
    r._original_discovery_offer = capture_discovery_offer(r, choice, options, effect.on_select)
    from .battlecry_sources import automatic_choice as battlecry_choice
    automatic = battlecry_choice(r,choice,options,effect.on_select)
    if automatic is not None:
        return automatic
    from .spell_casts import automatic_choice
    automatic = automatic_choice(r, choice, options, effect.on_select)
    if automatic is not None:
        return automatic
    from .hero_powers import automatic_choice as power_choice
    automatic = power_choice(r,choice,options,effect.on_select)
    if automatic is not None:
        return automatic
    from .spell_repeats import remembered_choice, remember_choice
    from .whole_card_physical import automatic_choice as physical_choice
    automatic = physical_choice(r, choice, options, effect.on_select)
    if automatic is not None:
        return automatic
    remembered = remembered_choice(r.state, choice)
    if remembered is not None:
        result = ChoiceResult(choice, remembered)
        return choice_effects(r, result, options, effect.on_select)
    if choice.max_count == 0:
        result = ChoiceResult(choice, ())
        remember_choice(r.state, result)
        r.emit('choice_skipped', source_id=choice.source_id, player_id=choice.player_id, choice_id=choice.id)
        return choice_effects(r, result, options, effect.on_select)
    r.state.pending_choice = choice
    r._choice_request = replace(effect, options=options, sample_size=None)
    r.emit('choice_requested', source_id=choice.source_id, player_id=choice.player_id,
           choice_id=choice.id, option_ids=tuple(o.id for o in options),
           min_count=choice.min_count, max_count=choice.max_count, purpose=choice.purpose.value,
           _choice_paid_boundary=True)


def choice_effects(r, result, options, on_select, *, kindred=None, selection_event=None):
    from .card_discoveries import commit
    commit(r, result, selection_event, options, on_select)
    from .resolver import ResolveChoiceResult
    callback = [ResolveChoiceResult(result, on_select, kindred)] if on_select is not None else []
    from .discovery import ResolvePoolDiscovery,RefreshPoolDiscovery
    from .discovery_destinations import DeliverDiscoveredSpell
    from .hand_choice_followups import ResolveHandFollowupChoice
    from .assemble_offers import ResolveAssemble
    from .crafted_offers import ResolveCraft
    from .model import ChoicePurpose
    from .stored_gift_discovery import SelectGiftedDeckCard
    from .zones import SelectDeckTake
    from .summon_sources import ResurrectMinion
    from .discovery_delivery import MaterializeDiscoveredCard, MaterializeDiscoveredResurrection, recipe_types
    def selected_effect(effect):
        if type(effect) in (ResolveAssemble,ResolveCraft):
            return replace(effect,result=result)
        if type(effect) is ResolveHandFollowupChoice:
            return replace(effect, result=result)
        if type(effect)in(ResolvePoolDiscovery,RefreshPoolDiscovery):
            return replace(effect,choice_result=result)
        if type(effect)is DeliverDiscoveredSpell:
            return replace(effect,decision=result)
        if type(effect) is SelectGiftedDeckCard:
            return replace(effect, result=result)
        if type(effect) is SelectDeckTake:
            return replace(effect, result=result)
        if result.choice.purpose == ChoicePurpose.CARD_DISCOVERY:
            if type(effect) in recipe_types():
                return MaterializeDiscoveredCard(result, effect)
            if type(effect) is ResurrectMinion:
                return MaterializeDiscoveredResurrection(result, effect)
            raise ResolutionError('Card discovery requires a typed original delivery producer')
        return effect
    if result.choice.purpose == ChoicePurpose.CARD_DISCOVERY and on_select is not None:
        raise ResolutionError('Card discovery callback requires a typed original delivery producer')
    if result.choice.purpose == ChoicePurpose.CARD_DISCOVERY and not any(option.effects for option in options if option.id in result.selected_ids):
        return [MaterializeDiscoveredCard(result, None)]
    return [*callback, *(selected_effect(effect) for option in options if option.id in result.selected_ids for effect in option.effects)]


def resolve_choice_result(r, effect):
    choice = effect.result.choice
    if effect.kindred is not None:
        from .kindred import context_kwargs, validate_preparation, validate_prepared_choice
        validate_preparation(r.state, r.registry, effect.kindred)
        validate_prepared_choice(effect.kindred, effect.result)
        if choice.id >= r.state.next_choice_id:
            raise ValueError('Sampled Kindred callback has a future choice identity')
        old = effect.kindred.original
        kwargs = context_kwargs(old)
        kwargs['choice'] = effect.result
        return [r.call(effect.behavior_id, old.source_id, old.player_id, old.target_id,
                       **kwargs, kindred=effect.kindred)]
    return [r.call(effect.behavior_id, choice.source_id or r.player(choice.player_id).hero_id,
                   choice.player_id, choice=effect.result)]


def resume_choice(r, action):
    frame, choice = r.game._frame, r.state.pending_choice
    from .paid_hand_acceptance import validate_choice_boundary
    validate_choice_boundary(r.game, resume=True)
    r._steps, r.root_action_number, r.ending_turn = frame.steps, frame.root_action_number, frame.ending_turn
    r.death_deferrals = frame.death_deferrals
    r.charge()  # Choosing is part of the original resolution's cumulative budget.
    result = ChoiceResult(choice, tuple(o.id for o in choice.options if o.id in action.option_ids))
    r._original_discovery_offer = frame.original_discovery_offer
    from .spell_repeats import remember_choice
    remember_choice(r.state, result)
    r.game._frame = None
    r._paid_hand_choice_boundary = None
    r.state.pending_choice = None
    selected = r.emit('choice_selected', source_id=choice.source_id, player_id=choice.player_id,
           choice_id=choice.id, option_ids=result.selected_ids, purpose=choice.purpose.value)
    triggers, r._captured = r._captured, []
    from .hero_lethal_windows import resume_work
    r.run(resume_work(r,frame,triggers,choice_effects(r,result,frame.options,frame.on_select,selection_event=selected)))


def random_choice_effects(r, choice, options, on_select, event_kind, **provenance):
    from .model import ChoiceResult
    count = choice.min_count if choice.min_count == choice.max_count else r.game._rng.randint(choice.min_count,choice.max_count)
    selected = set(r.game._rng.sample([o.id for o in options],count)) if count else set()
    result = ChoiceResult(choice,tuple(o.id for o in options if o.id in selected))
    selected_event = r.emit(event_kind,source_id=choice.source_id,player_id=choice.player_id,
        choice_id=choice.id,purpose=choice.purpose.value,option_ids=result.selected_ids,**provenance)
    return choice_effects(r,result,options,on_select,selection_event=selected_event)
