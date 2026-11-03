"""Hero-power activation predicates, usage and replacement primitives."""
from .runtime_copy import deepcopy
from dataclasses import dataclass, replace

from .actions import UseHeroPower
from .effects import (Effect, ReplaceHeroPower, _integer, _player, _source, _behavior,
    validate_power_reference, validate_generated_cost, validate_additional_power_policy)
from .errors import ResolutionError
from .lifecycle import active_abilities, copy_attachments, refresh_entity
from .model import CardType, Keyword, Zone, HeroPowerRecord, HeroPowerReference, CostSpec, GameState, ChooseBranchSelection
from .registry import RuleContext
from .costs import payment_error, quote_cost, pay_quote


def hero_powers_can_activate(state):
    """Pure global eligibility from ordinary current native board carriers."""
    return not any(e.zone == Zone.BOARD and e.kind == CardType.MINION and e.active and
        e.health > 0 and not e.doomed and Keyword.HERO_POWER_SUPPRESSOR in e.keywords
        for p in state.players.values() for i in p.board for e in (state.entities[i],))


def validate_prohibition_carrier(registry, card_id, kind, abilities, components=()):
    flags = tuple(a for a in abilities if a.kind == 'keyword' and a.keyword == Keyword.HERO_POWER_SUPPRESSOR)
    if not flags:
        return
    if kind != CardType.MINION or components or len(flags) != 1 or Keyword.HERO_POWER_SUPPRESSOR not in registry.card(card_id).keywords:
        raise ValueError('Hero Power prohibition carrier differs from its native declaration')
    for ability in flags:
        ability.__post_init__()


def power_record(state, record_id):
    _integer(record_id, 'hero power record', 1)
    if record_id > len(state.hero_power_history):
        raise ValueError('Unknown hero power activation')
    return state.hero_power_history[record_id - 1]


def validate_use_aura_definition(card):
    from .model import HeroPowerUseAuraSpec
    spec = card.hero_power_use_aura
    if spec is None:
        return
    if type(spec) is not HeroPowerUseAuraSpec:
        raise ValueError('Expected a native HeroPowerUseAuraSpec')
    spec.__post_init__()
    if card.kind != CardType.MINION or card.starship_for or Keyword.STARSHIP_PIECE in card.keywords:
        raise ValueError('Native Hero Power use aura requires an ordinary minion')


def validate_use_aura_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'hero_power_use_aura')
    if not rows:
        return
    card = registry.card(card_id); validate_use_aura_definition(card)
    if kind != CardType.MINION or components or len(rows) != 1 or card.hero_power_use_aura is None:
        raise ValueError('Hero Power use aura lost its ordinary native carrier')
    row = rows[0]; row.__post_init__()
    if row.hero_power_use_aura != card.hero_power_use_aura:
        raise ValueError('Hero Power use aura changed its complete native cap')


def effective_use_limit(state, power):
    """Current local cap and live native permissions, without changing usage."""
    if power.kind != CardType.HERO_POWER:
        raise ValueError('Effective Hero Power cap requires a physical skill')
    limit = power.use_limit
    for entity_id in state.players[power.controller].board:
        source = state.entities[entity_id]
        if source.zone != Zone.BOARD or source.kind != CardType.MINION or not source.active or source.health <= 0 or source.doomed:
            continue
        for ability in active_abilities(source,'hero_power_use_aura'):
            current = ability.hero_power_use_aura.limit
            if current is None:
                return None
            limit = max(limit,current)
    return limit


def active_power(state, source_id, player_id):
    return next((p for p in reversed(state.hero_power_history) if
        p.source_id == source_id and p.player_id == player_id and not p.completed and not p.interrupted), None)


def activated_powers(state, player_id, *, origin=None, successful=None, turn=None, before_id=None):
    """Trusted history query. Effect activations do not count as manual uses."""
    _player(player_id)
    if origin is not None and origin not in ('manual','effect'):
        raise ValueError('Invalid hero power origin filter')
    if successful is not None and type(successful) is not bool:
        raise ValueError('Hero power success filter must be boolean')
    for value in (turn,before_id):
        if value is not None: _integer(value,'hero power history bound',1)
    return tuple(p for p in state.hero_power_history if p.player_id == player_id and
        (origin is None or p.origin == origin) and (turn is None or p.turn == turn) and
        (before_id is None or p.id < before_id) and
        (successful is None or successful == (p.completed and p.failure is None)))


def hero_power_references(state, player_id, *, scope='all'):
    """Freeze the current installation set; later additions are not included."""
    _player(player_id)
    if scope not in ('all', 'primary', 'additional'):
        raise ValueError('Unknown hero power selection scope')
    player = state.players[player_id]
    ids = (player.hero_power_ids if scope == 'all' else player.additional_hero_power_ids
           if scope == 'additional' else (() if player.hero_power_id is None else (player.hero_power_id,)))
    return tuple(HeroPowerReference.capture(state.entities[i]) for i in ids)


def selected_power(r, effect, *, allow_empty=False):
    """None selects the primary at execution; a reference selects one incarnation."""
    reference = effect.power
    validate_power_reference(reference, effect.player_id)
    player = r.player(effect.player_id)
    if reference is None:
        if player.hero_power_id is None and not allow_empty:
            raise ResolutionError('Player has no hero power')
        return r.state.entities.get(player.hero_power_id)
    entity = r.state.entities.get(reference.entity_id)
    if (entity is not None and entity.id in player.hero_power_ids and
            (entity.zone, entity.kind, entity.controller, entity.card_id, entity.zone_epoch, entity.entered_order) ==
            (Zone.HERO_POWER, CardType.HERO_POWER, reference.player_id, reference.card_id,
             reference.zone_epoch, reference.entered_order)):
        return entity
    r.emit('effect_skipped', target_id=reference.entity_id, player_id=player.id,
           effect=type(effect).__name__, reason='hero_power_reference_stale')
    return None


def installation_definition(r, effect):
    from .costs import validate_creation_cost
    from .zones import source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    definition = r.registry.card(effect.card_id)
    if definition.kind != CardType.HERO_POWER:
        raise ResolutionError('Installation requires a hero power definition')
    validate_creation_cost(r.state, effect, (definition,))
    from .choose_branch_state import validate_selection, transfer_map
    if effect.choose_branch is not None:
        validate_selection(r.registry, effect.choose_branch, card_id=definition.id)
    if getattr(effect, 'branch_policy', 'clear') == 'inherit' and effect.power is not None:
        old_definition = r.registry.card(effect.power.card_id)
        if old_definition.choose_one is not None or effect.branch_map is not None:
            transfer_map(r.registry, effect.power.card_id, definition.id, effect.branch_map)
    return definition


def installation_cost(r, power, effect):
    if effect.cost is not None:
        from .costs import attach_cost
        attach_cost(r.state, power, effect.cost, effect.source_id, effect.expires_turn)


@dataclass(frozen=True)
class TriggerHeroPower(Effect):
    """Trigger a selected power's payload without paying or spending a use."""
    player_id: int
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    power: HeroPowerReference | None = None

    branch_id: str | None = None

    def __post_init__(self):
        if self.branch_id is not None: _behavior(self.branch_id)
        from .targeting import effect_policies
        _player(self.player_id); _source(self.source_id)
        effect_policies(self.targeting,self.target_id,self.choices)
        validate_power_reference(self.power, self.player_id)


@dataclass(frozen=True)
class AddHeroPower(Effect):
    """Install an independent additional power; never replace the primary."""
    player_id: int
    card_id: str
    source_id: int | None = None
    cost: CostSpec | None = None
    expires_turn: int | None = None
    choose_branch: ChooseBranchSelection | None = None

    def __post_init__(self):
        _player(self.player_id); _behavior(self.card_id); _source(self.source_id)
        validate_generated_cost(self.cost, self.expires_turn)
        from .card_creation import validate_branch_declaration
        validate_branch_declaration(self.choose_branch, self.card_id)


def add_hero_power(r, effect):
    installation_definition(r, effect)
    power = r.create_entity(effect.player_id, effect.card_id, Zone.HERO_POWER, additional_hero_power=True)
    installation_cost(r, power, effect)
    power.choose_branch = effect.choose_branch
    r.emit('hero_power_added', source_id=effect.source_id, target_id=power.id, player_id=effect.player_id)


@dataclass(frozen=True)
class RemoveHeroPower(Effect):
    player_id: int
    power: HeroPowerReference | None = None
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        validate_power_reference(self.power, self.player_id)


def remove_hero_power(r, effect):
    from .zones import source_exists
    effect.__post_init__(); source_exists(r, effect.source_id)
    power = selected_power(r, effect)
    if power is None:
        return
    r.move(power, Zone.GRAVEYARD)
    r.emit('hero_power_removed', source_id=effect.source_id, target_id=power.id, player_id=effect.player_id)


def replace_hero_additional_powers(r, player, policy):
    """Remove the whole old set before emitting any removal event."""
    validate_additional_power_policy(policy)
    if policy == 'preserve':
        return
    removed = tuple(player.additional_hero_power_ids)
    for power_id in removed:
        r.move(r.state.entities[power_id], Zone.GRAVEYARD)
    for power_id in removed:
        r.emit('hero_power_removed', source_id=player.hero_id, target_id=power_id, player_id=player.id)


@dataclass(frozen=True)
class ActivateHeroPower(Effect):
    action: UseHeroPower


@dataclass(frozen=True)
class FinishHeroPower(Effect):
    record_id: int
    context: RuleContext | None = None

    def __post_init__(self):
        validate_acceptance(self)


def validate_acceptance(work, registry=None):
    """A root retains its complete acceptance proof until it settles.

The current board-only capture is structural without a registry. Runtime and
boundary callers additionally validate declared historical source provenance.
"""
    _integer(work.record_id,'hero power completion',1)
    if type(work.context) is not RuleContext or type(work.context.state) is not GameState:
        raise ValueError('Hero power completion requires its root acceptance view')
    c=work.context;accepted=power_record(c.state,work.record_id)
    accepted.__post_init__()
    from .hero_power_repeats import capture_plan, validate_plan
    if (c.power!=accepted or accepted.failure is not None or accepted.completed or accepted.interrupted or
            c.state.status!='playing' or (accepted.turn,accepted.action)!=(c.state.turn,c.state.action_number) or
            (c.source_id,c.player_id,c.target_id)!=(accepted.source_id,accepted.player_id,accepted.target_id) or
            c.source.kind!=CardType.HERO_POWER or c.source.card_id!=accepted.card_id or
            c.source.zone!=Zone.HERO_POWER or c.source.controller!=accepted.player_id or
            c.source.id not in c.state.players[accepted.player_id].hero_power_ids or
            tuple(active_abilities(c.source,'on_use'))!=accepted.payloads or
            any(getattr(c,name) is not None for name in (
                'event','death','choice','player_effect','window','play','trigger','cast','draw',
                'battlecry','combo','deathrattle','power_payload','end_turn')) or c.rewind_attempt!=0):
        raise ValueError('Hero power root differs from its complete acceptance view')
    increment=int(accepted.origin=='manual')
    if ((c.source.uses_this_turn,c.state.players[accepted.player_id].hero_power_uses_this_turn)!=
            (accepted.uses_before+increment,accepted.player_uses_before+increment)):
        raise ValueError('Hero power root differs from its original successful use window')
    if registry is not None:
        from .hero_power_values import validate_acceptance as validate_value_acceptance
        validate_value_acceptance(c.state, registry, accepted)
        validate_plan(c.state,registry,accepted.repeat_plan,accepted.player_id,accepted.turn)
        if capture_plan(c.state,registry,accepted.player_id)!=accepted.repeat_plan:
            raise ValueError('Hero power root differs from its complete acceptance view')


def use_error(state, registry, rules, player, source, *, context_factory=None, branch_id=None):
    if source.id not in player.hero_power_ids or source.zone != Zone.HERO_POWER:
        return 'This is not the current hero power'
    if not hero_powers_can_activate(state):
        return 'Hero powers are disabled'
    if registry.card(source.card_id).passive_hero_power:
        return 'Passive hero powers cannot be activated manually'
    limit = effective_use_limit(state,source)
    if limit is not None and source.uses_this_turn >= limit:
        return 'No hero power uses remaining'
    if reason := payment_error(state, quote_cost(state, registry, source)):
        return reason
    definition = registry.card(source.card_id)
    if definition.requires_board_space and len(player.board) >= rules.max_board:
        return 'Board is full'
    try:
        visibility = registry.use_visibility(definition.use_rule)
        if visibility == 'player':
            if context_factory is None:
                raise ValueError('Player use rules require an observation context')
            context = context_factory(source.id, None)
        else:
            context = RuleContext(state if visibility == 'builtin' else deepcopy(state), source.id, player.id)
        allowed = registry.use_rule(definition.use_rule)(context)
    except Exception as exc:
        raise ResolutionError(f'Hero power use rule failed: {exc}') from exc
    if type(allowed) is not bool:
        raise ResolutionError('Hero power use rule must return bool')
    return None if allowed else 'Hero power use condition is not satisfied'


def activate_hero_power(r, effect):
    action = effect.action
    player, source = r.player(action.player_id), r.state.entities[action.entity_id]
    from .rewind import retry_quote
    quote = retry_quote(r,source)
    return begin(r,player,source,'manual',action.target_id,quote=quote,branch_id=action.branch_id)


def trigger_hero_power(r, effect):
    from .zones import source_exists
    from .targeting import select_effect_target
    effect.__post_init__(); source_exists(r,effect.source_id)
    player = r.player(effect.player_id)
    source = selected_power(r, effect)
    if source is None:
        return ()
    if not hero_powers_can_activate(r.state):
        return begin(r,player,source,'effect',None,effect=effect,failure='disabled')
    if r.registry.card(source.card_id).passive_hero_power:
        from .choose_one import branch
        branch(r.registry.card(source.card_id),effect.branch_id)
        # R-103: no active payload; retain an explicit effect attempt, without
        # synthesizing the events that normally drive the passive listener.
        return begin(r,player,source,'effect',None,effect=effect,failure='passive')
    from .choose_one import automatic_branch, effective
    definition=r.registry.card(source.card_id)
    branch_id=automatic_branch(r,definition,player.id,effect.branch_id,entity=source)
    target, failure = select_effect_target(r,source,effective(definition,branch_id),effect.targeting,effect.target_id)
    return begin(r,player,source,'effect',target,effect=effect,failure=failure,branch_id=branch_id)


def begin(r, player, source, origin, target_id, *, quote=None, effect=None, failure=None, branch_id=None):
    from .choose_policies import matching as choose_matching, capture as capture_choose, accept as accept_choose
    definition = r.registry.card(source.card_id)
    choose_origin = 'power_' + origin
    choose_before = deepcopy(r.state) if failure != 'disabled' and choose_matching(r.state, definition, player.id, choose_origin) else None
    choose_proof = None if choose_before is None else capture_choose(choose_before, r.registry, definition.id, player.id,
        'power', len(r.state.hero_power_history) + 1, choose_origin, branch_id, source_id=source.id)
    parent = next((x.id for x in reversed(r.state.hero_power_history) if not x.completed and not x.interrupted),None)
    record = HeroPowerRecord(len(r.state.hero_power_history)+1,source.id,player.id,source.card_id,
        r.state.turn,r.state.action_number,origin,target_id,
        activator_id=effect.source_id if effect else None,parent_id=parent,
        targeting=effect.targeting if effect else 'explicit',choices=effect.choices if effect else 'player',
        cost=quote.amount if quote else None,payment=quote.payment if quote else None,
        uses_before=source.uses_this_turn,player_uses_before=player.hero_power_uses_this_turn,
        completed=failure is not None,failure=failure,branch_id=branch_id)
    from .native_target_acceptance import accept as accept_native_target,FinishNativeTarget
    native=accept_native_target(r,'hero_power',record) if origin=='manual'and failure is None else None
    if native is not None:
        target_id=native.selection.target_id
        failure='invalid_target' if native.selection.failure is not None else None
        record=replace(record,target_id=target_id,native_target=native.selection,failure=failure,completed=failure is not None)
    r.state.hero_power_history.append(record)
    if quote is not None:
        pay_quote(r,player,source,quote)
        source.uses_this_turn += 1
        player.hero_power_uses_this_turn += 1
    if failure is None:
        from .hero_power_repeats import capture_plan
        record=replace(record,payloads=tuple(active_abilities(source,'on_use')),
                       repeat_plan=capture_plan(r.state,r.registry,player.id))
        r.state.hero_power_history[record.id-1]=record
    choose_tail = accept_choose(r, choose_proof)
    if failure is None:
        from .hero_power_values import claim as claim_personal_values
        record = claim_personal_values(r, record)
    r.emit('hero_power_started' if origin == 'manual' else 'hero_power_trigger_started',
        source_id=source.id,target_id=target_id,player_id=player.id,power_id=record.id)
    if failure is not None:
        r.emit('hero_power_trigger_failed',source_id=source.id,player_id=player.id,
            power_id=record.id,reason=failure)
        return [*(()if native is None else(FinishNativeTarget(native),)),*choose_tail]
    # Capture the accepted payload before start-event reactions, preserving the
    # manual activation contract. Replacing the slot does not retarget this work.
    from .rewind_outcomes import payload
    generated=payload(r,source.id,player.id,target_id,
        tuple(a.behavior_id for a in record.payloads),power=record)
    # Synchronous scheduling installs the root's ordinary batch or retained
    # outcome. No reaction or body has run, and the accepted plan is unchanged.
    # Keep those durable identities in the existing completion proof too.
    acceptance=RuleContext(deepcopy(r.state),source.id,player.id,target_id,power=record)
    return [*generated,*(()if native is None else(FinishNativeTarget(native),)),FinishHeroPower(record.id,acceptance), *choose_tail]


def finish_hero_power(r, effect):
    validate_acceptance(effect,r.registry)
    from .hero_power_acceptance import validate_queue
    validate_queue(r.state,r.registry,r._work_queue,r.rules.max_resolution_steps,closing=effect)
    record = power_record(r.state,effect.record_id)
    if effect.context.power!=record:
        raise ResolutionError('Hero power completion changed its accepted root')
    if record.completed or record.interrupted:
        raise ResolutionError('Hero power activation is already settled')
    if any(row.capture.power_id==record.id and not row.completed for row in r.state.hero_power_payload_history):
        raise ResolutionError('Hero power payloads must finish before their activation')
    record = replace(record,completed=True)
    r.state.hero_power_history[record.id-1] = record
    from .temporary_hero_powers import after_use
    after_use(r, record)
    r.emit('hero_power_used' if record.origin == 'manual' else 'hero_power_triggered',
        source_id=record.source_id,target_id=record.target_id,player_id=record.player_id,power_id=record.id)


def automatic_choice(r, choice, options, on_select):
    record = active_power(r.state,choice.source_id,choice.player_id)
    if record is None or record.choices != 'random': return None
    from .choices import random_choice_effects
    return random_choice_effects(r,choice,options,on_select,'hero_power_choice_automatic',power_id=record.id)


def validate_history(state, registry):
    from .temporary_hero_powers import historical_face_transitions
    if type(state.hero_power_history) is not list:
        raise ValueError('Hero power history must be a list')
    face_transitions = historical_face_transitions(state, registry)
    previous = (0,0)
    for index, record in enumerate(state.hero_power_history,1):
        if type(record) is not HeroPowerRecord: raise ValueError('Invalid hero power record')
        record.__post_init__()
        from .choose_one import branch
        if record.failure != 'disabled' or record.branch_id is not None:
            branch(registry.card(record.card_id),record.branch_id)
        source = state.entities.get(record.source_id)
        passive = registry.card(record.card_id).passive_hero_power
        if (record.failure != 'disabled' and (record.failure == 'passive') != passive or
                passive and (record.origin != 'effect' or record.target_id is not None)):
            raise ValueError('Passive power history cannot contain an active use')
        if (record.id != index or source is None or source.kind != CardType.HERO_POWER or
                source.owner != record.player_id or (source.card_id != record.card_id and
                    (source.id, record.card_id, source.card_id) not in face_transitions) or
                registry.card(record.card_id).kind != CardType.HERO_POWER or
                any(i is not None and i not in state.entities for i in (record.target_id,record.activator_id)) or
                not previous <= (record.turn,record.action) <= (state.turn,state.action_number) or
                record.interrupted and state.status == 'playing'):
            raise ValueError('Invalid hero power provenance')
        if record.parent_id is not None:
            parent = power_record(state,record.parent_id)
            if parent.turn != record.turn or parent.action > record.action or parent.failure is not None:
                raise ValueError('Invalid enclosing hero power activation')
            if (not record.completed and not record.interrupted) and (parent.completed or parent.interrupted):
                raise ValueError('Pending child of settled hero power')
        previous = (record.turn,record.action)
    from .power_payloads import validate_history as validate_payload_history
    validate_payload_history(state,registry)
    from .hero_power_values import validate_history as validate_value_history
    validate_value_history(state, registry)


def validate_boundary(game):
    from .hero_power_acceptance import validate_queue
    queue = (*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    validate_queue(game._state,game.registry,queue,game.ruleset.max_resolution_steps)


@dataclass(frozen=True)
class CheckHeroPowerTrigger(Effect):
    """A captured skill listener must retain its installed identity to start."""
    behavior_id: str
    context: RuleContext
    ability_id: int

    def __post_init__(self):
        _integer(self.ability_id,'hero power trigger ability',1)
        if type(self.context) is not RuleContext or self.context.event is None:
            raise ValueError('Power listener requires a captured event context')
        c=self.context
        source=c.state.entities.get(c.source_id)
        if (source is None or source.kind != CardType.HERO_POWER or source.zone != Zone.HERO_POWER or
                source.controller != c.player_id or source.id not in c.state.players[c.player_id].hero_power_ids or
                not any(a.id==self.ability_id and a.kind=='trigger' and a.behavior_id==self.behavior_id and
                    a.event==c.event.kind for a in active_abilities(source,'trigger'))):
            raise ValueError('Invalid captured hero power listener')


def check_power_trigger(r,effect):
    from .resolver import BehaviorCall
    effect.__post_init__()
    c=effect.context;old=c.state.entities[c.source_id];now=r.state.entities.get(c.source_id)
    if r.registry.card(old.card_id).passive_hero_power and not hero_powers_can_activate(c.state):
        if c.end_turn is not None:
            from .end_turns import skip
            skip(r,c.end_turn)
        return ()
    if (now is None or now.id not in r.player(c.player_id).hero_power_ids or
            (now.zone,now.controller,now.zone_epoch,now.entered_order) !=
            (Zone.HERO_POWER,c.player_id,old.zone_epoch,old.entered_order) or
            not any(a.id==effect.ability_id and a.behavior_id==effect.behavior_id and
                a.event==c.event.kind for a in active_abilities(now,'trigger'))):
        if c.end_turn is not None:
            from .end_turns import skip
            skip(r,c.end_turn)
        return ()
    if c.end_turn is not None:
        from .end_turns import InvokeEndTurn, pass_guard
        pass_guard(r.state,c.end_turn)
        return [InvokeEndTurn(c,c)]
    return [BehaviorCall(effect.behavior_id,c)]


def install_hero_power(r, effect, *, retirement_zone=Zone.GRAVEYARD):
    """Mutate the physical power slot; callers own their atomic event boundary."""
    player = r.player(effect.player_id)
    if retirement_zone not in (Zone.GRAVEYARD, Zone.SETASIDE):
        raise ResolutionError('Unsupported original power retirement zone')
    installation_definition(r, effect)
    old = selected_power(r, effect, allow_empty=True)
    if effect.power is not None and old is None:
        return None, None
    selection = effect.choose_branch
    if effect.branch_policy == 'inherit':
        if old is None: raise ResolutionError('Branch inheritance requires an installed original hero power')
        from .choose_branch_state import transfer_choose_branch, transfer_map
        if r.registry.card(old.card_id).choose_one is not None or effect.branch_map is not None:
            transfer_map(r.registry, old.card_id, effect.card_id, effect.branch_map)
        selection = transfer_choose_branch(r.registry, old.choose_branch, effect.card_id,
            effect.branch_map if old.choose_branch is not None else None)
    old_id = old.id if old is not None else None
    index = player.additional_hero_power_ids.index(old_id) if old_id in player.additional_hero_power_ids else None
    if old is not None:
        r.move(old, retirement_zone)
    new = r.create_entity(player.id, effect.card_id, Zone.HERO_POWER, additional_hero_power=index is not None)
    if index is not None:
        player.additional_hero_power_ids.remove(new.id)
        player.additional_hero_power_ids.insert(index, new.id)
    installation_cost(r, new, effect)
    new.choose_branch = selection
    return old_id, new


def replace_hero_power(r, effect):
    old_id, new = install_hero_power(r, effect)
    if new is not None:
        r.emit('hero_power_replaced', source_id=old_id, target_id=new.id, player_id=effect.player_id)


def refresh_hero_power(r, effect):
    effect.__post_init__()
    power = selected_power(r, effect)
    if power is None:
        return
    power.uses_this_turn = 0
    r.emit('hero_power_refreshed', target_id=power.id, player_id=effect.player_id)


def set_hero_power_uses(r, effect):
    effect.__post_init__()
    power = selected_power(r, effect)
    if power is None:
        return
    power.use_limit = effect.limit
    r.emit('hero_power_limit_changed', target_id=power.id, player_id=effect.player_id, amount=effect.limit)


def assign_hero_class(player, definition):
    if not definition.keep_hero_class:
        classes = definition.metadata.classes if definition.metadata is not None else ()
        player.hero_class = classes[0] if len(classes) == 1 else None


def play_hero(r, entity, *, origin=Zone.HAND):
    """Install the actual hand/deck hero card through one replacement lifecycle."""
    player = r.player(entity.controller)
    definition = r.registry.card(entity.card_id)
    if type(origin) is not Zone or origin not in (Zone.HAND,Zone.DECK) or not definition.hero_card or entity.zone != origin:
        raise ResolutionError('Playing a hero requires its actual hand/deck hero card')
    old = r.state.entities[player.hero_id]
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(old)
    old.zone = Zone.GRAVEYARD
    player.graveyard.append(old.id)
    getattr(player,origin.value).remove(entity.id)
    entity.zone = Zone.HERO
    entity.zone_epoch += 1
    from .lifecycle import renew_hand_progress
    renew_hand_progress(r.state, entity, previous_zone=origin)
    entity.entered_order = r.state.next_order
    r.state.next_order += 1
    player.hero_id = entity.id
    # Existing hero effects and incoming hand enhancements have independent IDs.
    card_abilities, card_enchantments = entity.abilities, entity.enchantments
    copy_attachments(r.state, old, entity)
    entity.abilities = [*card_abilities, *(a for a in entity.abilities if a.origin != 'printed')]
    entity.enchantments = [*entity.enchantments, *card_enchantments]
    entity.base_health = old.base_health
    entity.silenced = False
    refresh_entity(entity)
    entity.damage = max(0, entity.max_health - old.health)
    entity.armor = old.armor + definition.hero_armor
    entity.attacks_this_turn = old.attacks_this_turn
    entity.frozen_until_owner_turn = old.frozen_until_owner_turn
    entity.origin_entity_id = old.id
    assign_hero_class(player, definition)
    r.refresh_auras()
    replace_hero_additional_powers(r, player, definition.additional_power_policy)
    from .armor_gains import commit as commit_armor_gain
    commit_armor_gain(r, entity, old.armor, definition.hero_armor, 'hero_card')
    r.emit('hero_replaced', source_id=old.id, target_id=entity.id, player_id=player.id,
           _hero_health_before=health_before)
    replace_hero_power(r, ReplaceHeroPower(player.id, definition.initial_hero_power))


def replace_hero(r, effect):
    player = r.player(effect.player_id)
    if r.registry.card(effect.card_id).kind != CardType.HERO:
        raise ResolutionError('ReplaceHero requires a hero definition')
    old = r.state.entities[player.hero_id]
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(old)
    # Hero replacement is not a death. Preserve ongoing attachments and attack
    # expenditure; new ID prevents queued attacks from silently changing source.
    old.zone = Zone.GRAVEYARD
    player.graveyard.append(old.id)
    player.hero_id = 0
    new = r.create_entity(player.id, effect.card_id, Zone.HERO)
    printed = new.abilities
    copy_attachments(r.state, old, new)
    new.abilities = [*printed, *(a for a in new.abilities if a.origin != 'printed')]
    new.silenced = False
    refresh_entity(new)
    new.armor = old.armor + effect.armor
    new.attacks_this_turn = old.attacks_this_turn
    new.frozen_until_owner_turn = old.frozen_until_owner_turn
    new.origin_entity_id = old.id
    new.damage = max(0, new.max_health - (old.health if effect.health is None else effect.health))
    r.refresh_auras()
    replace_hero_additional_powers(r, player, effect.additional_power_policy)
    from .armor_gains import commit as commit_armor_gain
    commit_armor_gain(r, new, old.armor, effect.armor, 'replacement')
    r.emit('hero_replaced', source_id=old.id, target_id=new.id, player_id=player.id,
           _hero_health_before=health_before)
    if effect.hero_power_card_id is not None:
        return [ReplaceHeroPower(player.id, effect.hero_power_card_id)]
