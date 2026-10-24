"""Spell execution provenance and effect-driven casts, without invented hand plays.

R-088 records provisional targeting, condition and automatic-choice windows.
"""
from .hand_capacity import hand_capacity
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
import json

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError
from .lifecycle import active_abilities
from .model import CardType, Keyword, SpellCastRecord, SpellManaBudgetLink, TargetMode, Zone, _name
from .zones import CardReference, reference_entity, reference_value, source_exists
from .automatic_targets import (AutomaticTargetPreference, AutomaticTargetProof,
    PreferredMinionTarget, validate_preferred_source)
from .automatic_spell_groups import AutomaticSpellGroupProof


CONDITIONS = ('combo', 'outcast', 'finale', 'quickdraw', 'manathirst')
CAST_ORIGINS = ('hand', 'repeat', 'effect', 'draw', 'history','native_repeat')
AUTOMATIC_ORIGINS = ('effect', 'draw', 'history','native_repeat')


def cast_record(state, cast_id):
    _integer(cast_id, 'cast ID', 1)
    if cast_id > len(state.cast_history):
        raise ValueError('Unknown spell cast')
    return state.cast_history[cast_id - 1]


def bind_cast_prefix(before, state):
    """Later payload progress cannot rewrite an earlier CAST's accepted input."""
    progress = {'payload_started', 'completed', 'interrupted', 'local_spell_damage',
        'spell_damage_effects', 'native_spell_value', 'aura_duration_grants', 'spell_aura_id',
        'next_spell_bonus_effects', 'next_spell_body_effects', 'next_spell_body_cursor'}
    if len(before.cast_history) > len(state.cast_history):
        raise ValueError('Acceptance lost its complete original CAST prefix')
    for old, new in zip(before.cast_history, state.cast_history):
        fixed = lambda row:tuple(getattr(row, f.name) for f in fields(type(row)) if f.name not in progress)
        if fixed(old) != fixed(new) or old.completed and not new.completed or old.interrupted and not new.interrupted:
            raise ValueError('Acceptance changed an immutable earlier CAST target or input')


def capture_target_origin(state, target_id):
    """Freeze the final actual target at this cast's acceptance, before payload."""
    from .allocation_facts import SourceAllocationFact
    return None if target_id is None else SourceAllocationFact.capture(state,state.entities[target_id])


def target_origin_receipt(record):
    """Private event binding; no current entity is consulted after acceptance."""
    return json.dumps(None if record.target_origin is None else asdict(record.target_origin),
        ensure_ascii=False,sort_keys=True,separators=(',',':'))


def validate_target_origins(game):
    from .hero_health_history import effective_events
    seen=set()
    for event in effective_events(game._events):
        if event.kind!='spell_cast_started':continue
        data=dict(event.data)
        record=cast_record(game._state,data.get('cast_id'))
        expected={'cast_id','target_origin'} | ({'quest_parent_cast_id'} if record.quest_parent_cast_id is not None else set())
        from .spell_source_costs import start_receipt
        cost_data = start_receipt(record)
        expected.update(cost_data)
        if any(data.get(key) != value for key, value in cost_data.items()):
            raise ValueError('Spell source cost differs from its original start receipt')
        if record.mana_budget is not None:
            from .spell_mana_budget import receipt
            expected.add('mana_budget')
            if data.get('mana_budget')!=receipt(record):raise ValueError('Budget CAST lost its original start receipt')
        if set(data)!=expected or data.get('quest_parent_cast_id')!=record.quest_parent_cast_id:
            raise ValueError('Cast start requires its exact original target receipt')
        if (record.id in seen or
                (event.source_id,event.player_id,event.target_id,event.action)!=(record.source_id,record.player_id,record.target_id,record.action)or
                event.sequence<=record.recorded_event or data['target_origin']!=target_origin_receipt(record)):
            raise ValueError('Cast original target differs from its actual start fact')
        seen.add(record.id)
    if seen!={c.id for c in game._state.cast_history}:
        raise ValueError('Cast history lost its complete original target facts')


def cast_spells(state, player_id, *, origin=None, successful=None, turn=None, before_id=None):
    """Trusted query; default includes attempts. Successful means fully executed."""
    _player(player_id)
    if origin is not None and origin not in CAST_ORIGINS:
        raise ValueError('Unknown cast origin filter')
    if successful is not None and type(successful) is not bool:
        raise ValueError('Cast success filter must be boolean')
    for value in (turn, before_id):
        if value is not None: _integer(value, 'cast history bound', 1)
    return tuple(c for c in state.cast_history if c.player_id == player_id and
        (origin is None or c.origin == origin) and (turn is None or c.turn == turn) and
        (before_id is None or c.id < before_id) and
        (successful is None or successful == (c.completed and c.failure is None)))


def active_cast(state, source_id, player_id):
    return next((c for c in reversed(state.cast_history) if
        c.source_id == source_id and c.player_id == player_id and not c.completed and not c.interrupted), None)


def cast_owner_turn_id(state):
    from .owner_turns import current_owner_turn
    if state.owner_turn_history:
        return current_owner_turn(state).id
    if state.opening is None or state.opening.stage == 'complete':
        raise ResolutionError('A spell cast needs a real current interval or pre-first opening')
    return None


def automatic_conditions(state, definition, player_id):
    """The single condition clock used by actual automatic casts and proofs."""
    from .play_history import played_cards
    return dict(combo=bool(played_cards(state, player_id, turn=state.turn)),
        outcast=False, finale=False, quickdraw=False,
        manathirst=definition.manathirst is not None and state.players[player_id].max_mana >= definition.manathirst)


def accepted_fact_id(event):
    """Shape also applies to old attempt logs preserved by ordinary Rewind."""
    if event.kind != 'spell_cast_accepted':
        return None
    data = dict(event.data)
    if set(data) != {'cast_id'}:
        raise ValueError('Accepted cast fact requires only its physical cast ID')
    _integer(data['cast_id'], 'accepted physical cast ID', 1)
    _integer(event.source_id, 'accepted physical spell source', 1)
    _source(event.target_id); _player(event.player_id)
    if type(event.amount) is not int or event.amount != 1:
        raise ValueError('A physical cast contributes exactly one integer unit')
    return data['cast_id']


def accepted_cast(state, event):
    """Internal current physical-payload fact, not an old rewound attempt."""
    cast_id = accepted_fact_id(event)
    if cast_id is None:
        return None
    record = cast_record(state, cast_id)
    if (not record.payload_started or record.failure is not None or
            (event.source_id, event.target_id, event.player_id) !=
            (record.source_id, record.target_id, record.player_id) or
            not record.action <= event.action <= state.action_number or
            event.sequence <= record.recorded_event):
        raise ValueError('Accepted cast fact differs from its physical payload')
    return record


def note_payload(r, record):
    """One acceptance path for hand, repeat, effect, draw and history casts."""
    if not record.payload_started or record.failure is not None:
        return record
    from .adjoining_spells import accept as accept_adjoining_group
    accept_adjoining_group(r,record)
    from .stored_spell_damage import capture
    record = capture(r,record)
    from .native_spell_values import capture as capture_native_value
    record = capture_native_value(r,record)
    from .aura_duration import capture as capture_aura_duration
    record = capture_aura_duration(r, record)
    from .spell_auras import capture_cast as capture_spell_aura
    record = capture_spell_aura(r, record)
    from .player_effects import claim_next_spell_damage
    record = claim_next_spell_damage(r,record)
    from .next_spell_bodies import claim as claim_next_spell_bodies
    record = claim_next_spell_bodies(r, record)
    from .held_spells import note_cast
    note_cast(r, record)
    from .deathrattle_memory import remember_targeted_spell
    remember_targeted_spell(r, record)
    r.emit('spell_cast_accepted', source_id=record.source_id, target_id=record.target_id,
           player_id=record.player_id, amount=1, cast_id=record.id, _cast_acceptance=True)
    return record


def begin_played(r, play, target_id, *, iteration=1, countered=False, failure=None):
    if failure not in(None,'no_target') or countered and failure is not None:
        raise ValueError('Invalid hand CAST target failure')
    from .spell_source_costs import capture_hand, start_receipt
    record = SpellCastRecord(len(r.state.cast_history)+1, play.source_id, play.player_id,
        play.card_id, r.state.turn, r.state.action_number, 'hand' if iteration == 1 else 'repeat',
        target_id, play_id=play.id, iteration=iteration, from_zone=Zone.HAND,
        **{key: getattr(play, key) for key in CONDITIONS}, completed=countered or failure is not None,
        payload_started=not countered and failure is None,
        failure='countered' if countered else failure,branch_id=play.branch_id,
        owner_turn_id=cast_owner_turn_id(r.state), recorded_event=len(r.game._events),
        target_origin=capture_target_origin(r.state,target_id), held_higher_cost=play.held_higher_cost,
        next_spell_bonus_effects=play.next_spell_bonus_effects if iteration==1 else (),
        hand_cost_rank=play.hand_cost_rank, source_cost=capture_hand(r.registry, play),
        spell_target_group=play.spell_target_group, spell_target_receipt=play.spell_target_receipt)
    r.state.cast_history.append(record)
    # Match automatic casts: a real attempted physical cast has a start even
    # when countered; successful payload acceptance remains a separate fact.
    r.emit('spell_cast_started',source_id=record.source_id,target_id=record.target_id,
        player_id=record.player_id,cast_id=record.id,target_origin=target_origin_receipt(record), **start_receipt(record))
    record = note_payload(r, record)
    if failure is not None:
        r.emit('spell_cast_failed',source_id=record.source_id,player_id=record.player_id,cast_id=record.id,reason=failure)
    return record


@dataclass(frozen=True)
class FinishSpellCast(Effect):
    cast_id: int
    target_proof: AutomaticTargetProof | None = None
    group_target_proof: AutomaticSpellGroupProof | None = None

    def __post_init__(self):
        _integer(self.cast_id, 'cast completion ID', 1)
        if self.target_proof is not None and type(self.target_proof) is not AutomaticTargetProof:
            raise ValueError('Cast Finish requires its typed original target proof')
        if self.group_target_proof is not None and type(self.group_target_proof) is not AutomaticSpellGroupProof:
            raise ValueError('Cast Finish requires its typed complete original group proof')


def finish(r, effect):
    record = cast_record(r.state, effect.cast_id)
    validate_target_finish(effect, record, r.registry, state=r.state)
    if record.completed or record.interrupted or not record.payload_started:
        raise ResolutionError('Spell cast is already settled')
    if record.next_spell_body_cursor != 2*len(record.next_spell_body_effects):
        from .next_spell_bodies import ContinueNextSpellBodies
        if record.next_spell_body_cursor % 2:
            raise ResolutionError('Spell completion overtook a running extra body')
        return (ContinueNextSpellBodies(record.id, record.next_spell_body_cursor//2), effect)
    r.state.cast_history[record.id - 1] = replace(record, completed=True)
    # Each actual payload has one completion, including every hand repetition.
    # The separate card_played window still closes the whole physical play.
    r.emit('spell_cast_finished', source_id=record.source_id, target_id=record.target_id,
           player_id=record.player_id, cast_id=record.id)


def policies(targeting, target_id, choices, target_preference=None, *, target_ids=()):
    from .targeting import effect_policies
    effect_policies(targeting,target_id,choices)
    if type(target_ids) is not tuple or any(type(i) is not int or i < 1 for i in target_ids):
        raise ValueError('Automatic spell target vectors require immutable positive identities')
    if target_ids and (targeting != 'explicit' or len(set(target_ids)) != len(target_ids) or target_id != target_ids[0]):
        raise ValueError('Automatic explicit target vector requires distinct arrows and its exact primary alias')
    if target_preference is not None:
        if type(target_preference) not in (AutomaticTargetPreference, PreferredMinionTarget) or targeting != 'random':
            raise ValueError('Automatic target preference requires a typed random activation policy')


@dataclass(frozen=True)
class CastSpell(Effect):
    player_id: int
    card_id: str
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'

    branch_id: str | None = None
    target_preference: AutomaticTargetPreference | PreferredMinionTarget | None = None
    mana_budget: SpellManaBudgetLink | None = None
    target_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.mana_budget is not None:
            if type(self.mana_budget) is not SpellManaBudgetLink or self.source_id is None:
                raise ValueError('Budget CAST requires its exact original typed link and caster')
            self.mana_budget.__post_init__()
        if self.branch_id is not None: _name(self.branch_id, 'branch')
        _player(self.player_id); _name(self.card_id, 'cast spell'); _source(self.source_id)
        policies(self.targeting, self.target_id, self.choices, self.target_preference, target_ids=self.target_ids)
        validate_preferred_source(self.target_preference, self.source_id)


@dataclass(frozen=True)
class CastStoredSpell(Effect):
    card: CardReference
    player_id: int
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'

    branch_id: str | None = None
    target_preference: AutomaticTargetPreference | PreferredMinionTarget | None = None
    target_ids: tuple[int, ...] = ()

    def __post_init__(self):
        if self.branch_id is not None: _name(self.branch_id, 'branch')
        reference_value(self.card); _player(self.player_id); _source(self.source_id)
        policies(self.targeting, self.target_id, self.choices, self.target_preference, target_ids=self.target_ids)
        validate_preferred_source(self.target_preference, self.source_id)


@dataclass(frozen=True)
class ResolveAutomaticSpell(Effect):
    cast_id: int
    behavior_ids: tuple[str, ...]

    def __post_init__(self):
        _integer(self.cast_id, 'automatic cast ID', 1)
        if type(self.behavior_ids) is not tuple:
            raise ValueError('Spell behaviors require a tuple')
        for behavior in self.behavior_ids: _name(behavior, 'spell behavior')


@dataclass(frozen=True)
class CreateCastDerivative(Effect):
    cast_id: int
    card_id: str

    def __post_init__(self):
        _integer(self.cast_id, 'derivative cast ID', 1)
        _name(self.card_id, 'derivative card')


def effective_definition(definition, conditions):
    if definition.target_condition and not conditions[definition.target_condition]:
        return replace(definition, requires_target=False, targeting=None, target_rule='any_entity')
    return definition


def automatic(r, effect, entity, from_zone, *, origin='effect', draw_id=None, recast_id=None, target_proofs=None, quest_parent_cast_id=None, adjoining_parent=None, retain_targets=False):
    grouped = entity.card_id in r.registry.spell_target_group_profiles
    if not grouped and effect.target_ids:
        raise ResolutionError('This automatic spell has no declared target group')
    if type(retain_targets) is not bool or retain_targets and (not grouped or origin != 'history' or recast_id is None):
        raise ResolutionError('Retaining a complete group requires its original historical CAST')
    from .spell_source_costs import capture_automatic as capture_source_cost, start_receipt
    source_cost = capture_source_cost(r, entity, effect.player_id)
    from .adjoining_spells import capture as capture_adjoining,note_automatic as note_adjoining_automatic
    adjoining_material=None if adjoining_parent is not None else capture_adjoining(r.state,r.registry,entity,from_zone,player_id=effect.player_id)
    from .one_cost_casts import capture_automatic,accept_automatic
    native_repeat=capture_automatic(r,entity,effect.player_id)
    from .play_history import played_cards
    from .targeting import accepts_target, target_spec
    definition = r.registry.card(entity.card_id)
    validate_preferred_source(getattr(effect, 'target_preference', None), effect.source_id, r.state)
    if definition.kind != CardType.SPELL:
        raise ResolutionError('Casting requires a spell')
    # Hand-only positional/payment conditions do not acquire a fabricated play.
    conditions = automatic_conditions(r.state, definition, effect.player_id)
    from .hand_cost_rank import capture as capture_hand_rank
    hand_rank = capture_hand_rank(r.state, r.registry, entity, player_id=effect.player_id)
    r.move(entity, Zone.GRAVEYARD)
    if entity.controller != effect.player_id:
        r.player(entity.controller).graveyard.remove(entity.id)
        entity.controller = effect.player_id
        r.player(entity.controller).graveyard.append(entity.id)
    from .choose_one import automatic_branch, effective as branch_definition
    from .choose_policies import matching as choose_matching, capture as capture_choose, accept as accept_choose
    choose_origin = 'cast_' + origin
    choose_before = deepcopy(r.state) if choose_matching(r.state, definition, effect.player_id, choose_origin) else None
    branch_id = automatic_branch(r,definition,effect.player_id,getattr(effect,'branch_id',None), origin=choose_origin, entity=entity)
    choose_proof = None if choose_before is None else capture_choose(choose_before, r.registry, definition.id, effect.player_id,
        'cast', len(r.state.cast_history) + 1, choose_origin, branch_id, source_id=entity.id)
    effective = branch_definition(effective_definition(definition, conditions),branch_id)
    from .targeting import select_effect_target
    preference = getattr(effect, 'target_preference', None)
    target_proof = None
    group_receipt = group_proof = None
    if grouped:
        from .automatic_spell_groups import accept
        group_receipt, group_proof = accept(r, entity, effective, effect,
            retained_cast_id=recast_id if retain_targets else None)
        target_id, failure = group_receipt.primary_target_id, group_receipt.failure
        if target_proofs is not None: target_proofs.append(group_proof)
    elif preference is None:
        target_id, failure = select_effect_target(r,entity,effective,effect.targeting,effect.target_id)
    else:
        policies(effect.targeting, effect.target_id, effect.choices, preference)
        from .automatic_targets import select_target_with_proof
        target_id, failure, target_proof = select_target_with_proof(r, entity, effective, preference)
        if target_proofs is not None: target_proofs.append(target_proof)
    from .held_higher_cost import capture as capture_higher_cost
    record = SpellCastRecord(len(r.state.cast_history)+1, entity.id, effect.player_id,
        entity.card_id, r.state.turn, r.state.action_number, origin, target_id,
        caster_id=effect.source_id, from_zone=from_zone, choices=effect.choices,
        **conditions, completed=failure is not None, failure=failure, draw_id=draw_id, recast_id=recast_id,branch_id=branch_id,
        owner_turn_id=cast_owner_turn_id(r.state), recorded_event=len(r.game._events),
        target_selection=target_proof.selection if target_proof is not None else None,
        target_origin=capture_target_origin(r.state,target_id),
        held_higher_cost=capture_higher_cost(r.state, entity), quest_parent_cast_id=quest_parent_cast_id,
        mana_budget=getattr(effect,'mana_budget',None), hand_cost_rank=hand_rank, source_cost=source_cost,
        spell_target_receipt=group_receipt)
    r.state.cast_history.append(record)
    choose_tail = accept_choose(r, choose_proof)
    note_adjoining_automatic(r,record,adjoining_material,adjoining_parent)
    from .next_spell_bonuses import accept_automatic as accept_native_spell_bonus
    record=accept_native_spell_bonus(r,record)
    if draw_id is not None:
        from .draw_casts import note_cast
        note_cast(r, draw_id, record.id)
    budget_data={}
    if record.mana_budget is not None:
        from .spell_mana_budget import receipt,validate_record
        validate_record(r.state,r.registry,record)
        budget_data={'mana_budget':receipt(record)}
    r.emit('spell_cast_started', source_id=entity.id, target_id=target_id, player_id=record.player_id,
           cast_id=record.id,target_origin=target_origin_receipt(record),
           **({'quest_parent_cast_id':quest_parent_cast_id} if quest_parent_cast_id is not None else {}),
           **budget_data, **start_receipt(record))
    if group_receipt is not None:
        from .automatic_spell_groups import note
        note(r, record)
    if failure:
        if group_proof is not None:
            from .automatic_spell_groups import validate_finish
            validate_finish(group_proof, record, r.registry, r.state)
        r.emit('spell_cast_failed', source_id=entity.id, player_id=record.player_id,
               cast_id=record.id, reason=failure)
        return choose_tail
    behaviors = tuple(a.behavior_id for a in active_abilities(entity, 'on_play'))
    native_tail=accept_automatic(r,record,behaviors,native_repeat)
    return (ResolveAutomaticSpell(record.id, behaviors), FinishSpellCast(record.id, target_proof, group_proof), *native_tail,*choose_tail)


def cast_generated(r, effect, *, quest_parent_cast_id=None):
    effect.__post_init__(); source_exists(r, effect.source_id)
    if r.registry.card(effect.card_id).kind != CardType.SPELL:
        raise ResolutionError('CastSpell requires a spell definition')
    entity = r.create_entity(effect.player_id, effect.card_id, Zone.GRAVEYARD)
    entity.origin_entity_id = effect.source_id
    return automatic(r, effect, entity, None, quest_parent_cast_id=quest_parent_cast_id)


def cast_stored(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    entity = reference_entity(r, effect.card)
    if entity is None: return ()
    # Detach while still owned by its current zone controller.
    from_zone = entity.zone
    if entity.kind != CardType.SPELL:
        raise ResolutionError('CastStoredSpell requires a stored spell')
    return automatic(r, effect, entity, from_zone)


def resolve_automatic(r, effect):
    record = cast_record(r.state, effect.cast_id)
    if record.origin not in AUTOMATIC_ORIGINS or record.completed or record.interrupted or record.payload_started:
        raise ResolutionError('Invalid automatic spell execution')
    record = replace(record, payload_started=True)
    r.state.cast_history[record.id - 1] = record
    record = note_payload(r, record)
    from .rewind_outcomes import payload
    return payload(r, record.source_id, record.player_id, record.target_id, effect.behavior_ids, cast=record)


def payload_effects(r, record, behavior_ids, *, play=None, extra_outcome=False):
    """Shared spell text and derivatives; an activation owns its single history."""
    entity = r.state.entities[record.source_id]
    definition = r.registry.card(record.card_id)
    repeated = record.iteration > 1 or extra_outcome
    work = []
    if definition.secret is not None:
        from .secrets import activate, set_secret, SetSecret
        if repeated: set_secret(r, SetSecret(record.player_id, record.card_id))
        else: activate(r, entity)
    elif definition.quest is not None:
        from .quests import spell_payload
        work.extend(spell_payload(r, entity, record, repeated=repeated))
    elif definition.ongoing_effect_id is not None:
        from .player_effects import AddPlayerEffect
        work.append(AddPlayerEffect(record.player_id, definition.ongoing_effect_id, entity.id,
            aura_duration_cast_id=record.id if record.aura_duration_grants else None,
            spell_aura_id=record.spell_aura_id))
    work.extend(r.call(b, record.source_id, record.player_id, record.target_id, play=play, cast=record) for b in behavior_ids)
    # Twinspell is a payload derivative. Echo remains a paid-hand-play facility.
    if play is not None:
        from .hand_derivatives import after_spell_effects
        work.extend(after_spell_effects(play))
    else:
        work.extend(CreateCastDerivative(record.id, s.card_id) for s in definition.hand_derivatives
                    if s.keyword == Keyword.TWINSPELL and s.keyword in entity.keywords)
    from .adjoining_spells import payload_tail as adjoining_payload_tail
    work.extend(adjoining_payload_tail(r,record))
    return work


def create_derivative(r, effect):
    record = cast_record(r.state, effect.cast_id)
    definition = r.registry.card(record.card_id)
    if (record.origin not in AUTOMATIC_ORIGINS or record.completed or record.interrupted or
            not any(s.keyword == Keyword.TWINSPELL and s.card_id == effect.card_id for s in definition.hand_derivatives)):
        raise ResolutionError('Invalid automatic spell derivative')
    player = r.player(record.player_id)
    zone = Zone.HAND if len(player.hand) < hand_capacity(player, r.rules) else Zone.GRAVEYARD
    entity = r.create_entity(player.id, effect.card_id, zone, hand_entry_source_id=record.source_id)
    entity.origin_entity_id = record.source_id
    r.emit('card_created', source_id=record.source_id, target_id=entity.id, player_id=player.id)
    if zone==Zone.GRAVEYARD:
        from .zones import emit_burn
        emit_burn(r,entity,profile='created_overflow',source_id=record.source_id,reason='twinspell')
    else:
        r.emit('card_added_to_hand',source_id=record.source_id,target_id=entity.id,player_id=player.id,reason='twinspell')
        from .hand_history import publish as publish_hand_entry
        publish_hand_entry(r, entity.hand_entry_id)


def automatic_choice(r, choice, options, on_select):
    """Only the spell's own choices inherit policy; independent reactions do not."""
    record = active_cast(r.state, choice.source_id, choice.player_id)
    if record is None:
        from .draw_casts import active_after_draw
        draw = active_after_draw(r.state, choice.source_id, choice.player_id)
        if draw is not None: record = cast_record(r.state, draw.cast_id)
    if record is None or record.choices != 'random': return None
    from .choices import random_choice_effects
    return random_choice_effects(r,choice,options,on_select,'spell_choice_automatic',cast_id=record.id)


def validate_history(state, registry):
    from .quests import pair_parent
    for child in state.cast_history:
        if child.quest_parent_cast_id is not None:
            pair_parent(state, registry, child)
    if type(state.cast_history) is not list: raise ValueError('Cast history must be a list')
    from .repeat_provenance import checked_live_attachments
    live = checked_live_attachments(state)
    claimed_ids = set()
    local_owners = {}
    last_turn = last_action = 0
    iterations = {}
    for index, record in enumerate(state.cast_history, 1):
        if type(record) is not SpellCastRecord: raise ValueError('Invalid spell cast record')
        record.__post_init__()
        from .held_higher_cost import validate_cast as validate_higher_cost_cast
        validate_higher_cost_cast(state, registry, record)
        from .hand_cost_rank import validate_cast as validate_hand_rank
        validate_hand_rank(state, registry, record)
        from .spell_source_costs import validate_record as validate_source_cost
        validate_source_cost(state, registry, record)
        if record.target_origin is not None:
            from .allocation_facts import validate_allocation
            validate_allocation(state,registry,record.target_origin)
        if record.target_selection is not None:
            validate_preferred_source(record.target_selection.partition.preference, record.caster_id, state)
        from .stored_spell_damage import validate_record
        validate_record(state,record,live,local_owners)
        from .native_spell_values import validate_record as validate_native_value
        validate_native_value(state,registry,record,live,local_owners)
        from .aura_duration import validate_record as validate_aura_duration_record
        validate_aura_duration_record(state, registry, record)
        for effect in record.spell_damage_effects:
            spec = registry.player_effect(effect.spec_id)
            spec.__post_init__()
            if (spec.kind not in ('next_spell_damage', 'next_spell_damage_until_cast') or
                    spec.kind == 'next_spell_damage' and effect.created_turn != record.turn or
                    effect.remaining_turns is not None or
                    effect.id >= state.next_attachment_id or effect.entered_order >= state.next_order or
                    effect.source_id not in state.entities or effect.id in live or effect.id in claimed_ids):
                raise ValueError('Cast reused or invented a pending Spell Damage effect')
            registry.card(effect.source_card_id)
            claimed_ids.add(effect.id)
        from .choose_one import branch
        branch(registry.card(record.card_id),record.branch_id)
        if (record.id != index or registry.card(record.card_id).kind != CardType.SPELL or
                record.source_id not in state.entities or
                any(i is not None and i not in state.entities for i in (record.caster_id, record.target_id)) or
                not last_turn <= record.turn <= state.turn or not last_action <= record.action <= state.action_number or
                record.interrupted and state.status == 'playing'):
            raise ValueError('Invalid spell cast provenance')
        if record.owner_turn_id is None:
            first = state.owner_turn_history[0] if state.owner_turn_history else None
            if (state.opening is None or record.turn != 1 or
                    first is None and state.opening.stage == 'complete' or
                    first is not None and (record.action > first.start_action or record.recorded_event >= first.start_event)):
                raise ValueError('Unowned cast is not a genuine pre-first opening fact')
        else:
            if record.owner_turn_id > len(state.owner_turn_history):
                raise ValueError('Spell cast references an unknown actual interval')
            interval = state.owner_turn_history[record.owner_turn_id - 1]
            if (record.turn != interval.turn or record.action < interval.start_action or
                    record.recorded_event < interval.start_event or
                    interval.closed and (record.action > interval.closed_action or record.recorded_event > interval.closed_event)):
                raise ValueError('Spell cast differs from its original actual interval')
        if record.play_id is not None:
            from .play_history import play_record
            play = play_record(state, record.play_id)
            actual_empty = (play.spell_target_receipt is not None and play.spell_target_receipt.closed and
                play.spell_target_receipt.primary_target_id is None)
            if record.failure=='no_target' and (not registry.random_target_cards and not actual_empty or record.target_id is not None or
                    play.spell_payload is None or play.spell_payload.target_id is not None):
                raise ValueError('Hand no-target failure requires an actual native empty target acceptance')
            ordinal = iterations.get(play.id, 0) + 1
            if ((record.source_id, record.player_id, record.card_id, record.turn) !=
                    (play.source_id, play.player_id, play.card_id, play.turn) or
                    record.owner_turn_id != play.played_face.owner_turn_id or
                    record.action < play.action or record.iteration != ordinal or record.branch_id != play.branch_id or
                    any(getattr(record, k) != getattr(play, k) for k in CONDITIONS) or
                    (record.failure == 'countered') != play.countered or
                    play.completed and not record.completed or play.interrupted and not(record.completed or record.interrupted)):
                raise ValueError('Spell cast and hand play disagree')
            iterations[play.id] = ordinal
        if record.origin == 'history':
            original = cast_record(state,record.recast_id)
            entity = state.entities[record.source_id]
            if (original.card_id != record.card_id or entity.origin_entity_id != original.source_id or
                    record.source_id <= original.source_id):
                raise ValueError('Historical spell has inconsistent original provenance')
        if record.origin == 'native_repeat':
            original = cast_record(state,record.recast_id)
            if (original.origin not in ('effect','draw','history') or not original.completed or original.failure is not None or
                    (record.source_id,record.card_id,record.player_id,record.target_id,record.branch_id,record.choices) !=
                    (original.source_id,original.card_id,original.player_id,original.target_id,original.branch_id,original.choices) or
                    any(getattr(record,k)!=getattr(original,k) for k in CONDITIONS)):
                raise ValueError('Native repeated spell changed its accepted original cast')
        last_turn, last_action = record.turn, record.action
    for play in state.play_history:
        if play.kind == CardType.SPELL and play.completed and play.id not in iterations:
            raise ValueError('Completed spell play has no cast history')


def validate_boundary(game):
    from .one_cost_casts import validate_boundary as validate_native_repeat_boundary
    validate_native_repeat_boundary(game)
    validate_target_origins(game)
    if any(c.recorded_event > len(game._events) for c in game._state.cast_history):
        raise ValueError('Cast allocation cursor is newer than the actual event boundary')
    accepted = set(); restored_after = None
    # Rewind preserves attempted event logs while restoring cast history and
    # reusing its IDs. A later Retry invalidates only the earlier events after
    # its original checkpoint cursor, never the retried/new final facts.
    for event in reversed(game._events):
        if event.kind == 'timeline_rewound':
            start = dict(event.data).get('event_start')
            _integer(start, 'actual Retry event checkpoint', 0)
            if start >= event.sequence:
                raise ValueError('Retry event checkpoint exceeds its original window')
            restored_after = start if restored_after is None else min(restored_after, start)
        fact_id = accepted_fact_id(event)
        if fact_id is not None and (restored_after is None or event.sequence <= restored_after):
            record = accepted_cast(game._state, event)
            if record.id in accepted:
                raise ValueError('Duplicate physical cast acceptance fact')
            accepted.add(record.id)
    if accepted != {c.id for c in game._state.cast_history if c.payload_started and c.failure is None}:
        raise ValueError('Physical casts and acceptance facts differ')
    pending = [c for c in game._state.cast_history if not c.completed and not c.interrupted]
    queue = (*game._frame.prefix, *game._frame.continuation) if game._frame else ()
    validate_target_queue(game._state, game.registry, queue)
    closers = [w.cast_id for w in queue if type(w) is FinishSpellCast]
    if closers != [c.id for c in reversed(pending)]:
        raise ValueError('Spell cast progress and completion markers differ')
    starters = [w.cast_id for w in queue if type(w) is ResolveAutomaticSpell]
    if starters != [c.id for c in reversed(pending) if c.origin in AUTOMATIC_ORIGINS and not c.payload_started]:
        raise ValueError('Automatic spell phase and payload markers differ')
    from .hand_progress import AdvanceHandProgress
    for work in queue:
        if type(work) is AdvanceHandProgress and work.event.kind == 'spell_cast_accepted':
            accepted_cast(game._state, work.event)
            if (work.event.sequence > len(game._events) or
                    game._events[work.event.sequence - 1] != work.event):
                raise ValueError('Queued hand progress lost its actual cast acceptance event')
        if type(work) is ResolveAutomaticSpell:
            record = cast_record(game._state, work.cast_id)
            if record not in pending or record.origin not in AUTOMATIC_ORIGINS:
                raise ValueError('Invalid pending automatic spell')
            closer = next(w for w in queue if type(w) is FinishSpellCast and w.cast_id == record.id)
            if queue.index(work) > queue.index(closer):
                raise ValueError('Spell payload follows its completion')
            for behavior in work.behavior_ids: game.registry.behavior(behavior)


def validate_target_finish(effect, record, registry, *, state=None):
    from .automatic_spell_groups import validate_finish
    validate_finish(effect.group_target_proof, record, registry, state)
    if record.target_selection is None:
        if effect.target_proof is not None:
            raise ValueError('Cast without preference cannot borrow another target acceptance')
    else:
        if type(effect.target_proof) is not AutomaticTargetProof:
            raise ValueError('Automatic preferred cast lost its original target Finish proof')
        from .automatic_targets import validate_cast_proof
        validate_cast_proof(effect.target_proof, record, registry)


def validate_target_queue(state, registry, queue):
    for work in queue:
        if type(work) is FinishSpellCast:
            record = cast_record(state, work.cast_id)
            if record.completed or record.interrupted:
                raise ValueError('Stale automatic target Finish marker')
            validate_target_finish(work, record, registry, state=state)
    for cast in state.cast_history:
        if cast.target_selection is not None and not cast.completed and not cast.interrupted:
            if sum(type(w) is FinishSpellCast and w.cast_id == cast.id for w in queue) != 1:
                raise ValueError('Preferred automatic cast lost its unique original target Finish')


def register(mechanics):
    from .automatic_targets import register_payloads
    register_payloads(mechanics)
    for effect, handler in ((CastSpell, cast_generated), (CastStoredSpell, cast_stored),
            (ResolveAutomaticSpell, resolve_automatic), (FinishSpellCast, finish),
            (CreateCastDerivative, create_derivative)):
        mechanics.register(effect, handler)
