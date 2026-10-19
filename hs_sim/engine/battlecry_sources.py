"""Indirect Battlecry payload execution, without playing or copying a card.

R-120 is an explicit prototype contract. History queries count activations or
deduplicate hand-play payloads; neither invents activations for countered plays.
"""
from copy import deepcopy
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import BattlecryPayload, BattlecryRecord, CardType, HeldOpponentCopyMatch, _name
from .sacrifice import MinionReference, reference_value, live_minion
from .targeting import effect_policies, select_effect_target


@dataclass(frozen=True)
class BattlecryHistoryQuery:
    origins: tuple[str, ...] = ('hand',)
    turn: int | None = None
    before_id: int | None = None
    before_play_id: int | None = None
    exclude_ids: tuple[int, ...] = ()
    distinct: str = 'activation'

    def __post_init__(self):
        if (type(self.origins) is not tuple or not self.origins or
                len(set(self.origins)) != len(self.origins) or
                any(o not in ('hand','effect','history','played_history') for o in self.origins)):
            raise ValueError('Invalid Battlecry history origins')
        for value in (self.turn,self.before_id,self.before_play_id):
            if value is not None: _integer(value,'Battlecry history bound',1)
        if type(self.exclude_ids) is not tuple or len(set(self.exclude_ids)) != len(self.exclude_ids):
            raise ValueError('Battlecry exclusions require unique immutable IDs')
        for value in self.exclude_ids: _integer(value,'excluded Battlecry',1)
        if self.distinct not in ('activation','play_payload'):
            raise ValueError('Unknown Battlecry history distinctness')
        if (self.distinct == 'play_payload' or self.before_play_id is not None) and self.origins != ('hand',):
            raise ValueError('Play-based queries require hand origins')


def battlecry_history_candidates(state, player_id, query=BattlecryHistoryQuery()):
    """Trusted, completed successful payloads; canonical first occurrence per key."""
    _player(player_id)
    if type(query) is not BattlecryHistoryQuery: raise ValueError('Expected BattlecryHistoryQuery')
    query.__post_init__()
    seen=set(); result=[]
    for b in state.battlecry_history:
        if (b.player_id != player_id or b.origin not in query.origins or
                not b.completed or b.failure is not None or b.id in query.exclude_ids or
                query.turn is not None and b.turn != query.turn or
                query.before_id is not None and b.id >= query.before_id or
                query.before_play_id is not None and b.play_id >= query.before_play_id):
            continue
        key = b.id if query.distinct == 'activation' else (b.play_id,b.payload.ability_id)
        if key not in seen: seen.add(key); result.append(b)
    return tuple(result)


@dataclass(frozen=True)
class TriggerBattlecry(Effect):
    subject: MinionReference
    source_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    profile_id: str | None = None

    def __post_init__(self):
        reference_value(self.subject); _source(self.source_id)
        effect_policies(self.targeting,self.target_id,self.choices)
        if self.profile_id is not None: _name(self.profile_id,'indirect target profile')


@dataclass(frozen=True)
class RepeatBattlecry(Effect):
    player_id: int
    source_id: int
    history_id: int
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    profile_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id,'Battlecry carrier',1)
        _integer(self.history_id,'historical Battlecry',1)
        effect_policies(self.targeting,self.target_id,self.choices)
        if self.profile_id is not None: _name(self.profile_id,'historical target profile')


@dataclass(frozen=True)
class RepeatBattlecries(Effect):
    player_id: int
    source_id: int
    query: BattlecryHistoryQuery = BattlecryHistoryQuery()
    selection: str = 'last'
    order: str = 'chronological'
    choices: str = 'random'
    profile_id: str | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id,'Battlecry carrier',1)
        if type(self.query) is not BattlecryHistoryQuery: raise ValueError('Expected BattlecryHistoryQuery')
        self.query.__post_init__()
        if self.selection not in ('first','last','all') or self.order not in ('chronological','random'):
            raise ValueError('Invalid Battlecry history selection')
        effect_policies('random',None,self.choices)
        if self.profile_id is not None: _name(self.profile_id,'historical target profile')


@dataclass(frozen=True)
class BeginIndirectBattlecry(Effect):
    source_id: int
    player_id: int
    card_id: str
    payload: BattlecryPayload
    origin: str = 'effect'
    history_id: int | None = None
    caster_id: int | None = None
    target_id: int | None = None
    targeting: str = 'random'
    choices: str = 'random'
    history_play_id: int | None = None
    history_player_id: int | None = None
    controller_policy: str = 'captured'
    exclude_source_target: bool = False
    physical_child_id: int | None = None
    outcome_id: int | None = None
    iteration: int = 1
    repeat_index: int = 1
    indirect_body_id: int | None = None
    historical_profile_id: str | None = None
    historical_body_id: int | None = None
    held_opponent_copy: HeldOpponentCopyMatch | None = None

    def __post_init__(self):
        if self.held_opponent_copy is not None:
            if self.origin != 'effect' or type(self.held_opponent_copy) is not HeldOpponentCopyMatch:
                raise ValueError('Only effect origins carry their original captured held copied-play fact')
            self.held_opponent_copy.__post_init__()
        _integer(self.source_id,'Battlecry carrier',1); _player(self.player_id)
        _name(self.card_id,'Battlecry carrier card'); _source(self.caster_id); _source(self.history_id)
        if type(self.payload) is not BattlecryPayload: raise ValueError('Expected captured Battlecry payload')
        self.payload.__post_init__()
        _source(self.history_play_id)
        _source(self.physical_child_id)
        _source(self.indirect_body_id)
        _source(self.historical_body_id)
        if self.historical_profile_id is not None: _name(self.historical_profile_id,'historical target profile')
        if (self.historical_body_id is not None and self.historical_profile_id is None or
                self.historical_profile_id is not None and (self.origin not in ('history','played_history')
                    or self.physical_child_id is not None or self.indirect_body_id is not None)):
            raise ValueError('Historical body requires its own actual history origin')
        if self.indirect_body_id is not None and (self.origin != 'effect' or self.physical_child_id is not None
                or self.targeting != 'explicit' or self.exclude_source_target or self.controller_policy != 'captured'):
            raise ValueError('Bound indirect invocation requires its own accepted target producer')
        _source(self.outcome_id)
        _integer(self.iteration, 'actual generated BC result', 1)
        _integer(self.repeat_index, 'actual generated BC repetition', 1)
        if self.physical_child_id is None and (self.outcome_id is not None or self.iteration != 1 or self.repeat_index != 1):
            raise ValueError('Ordinary indirect BC cannot borrow generated retained results')
        if self.outcome_id is None and self.iteration != 1:
            raise ValueError('Extra generated BC result requires its retained root')
        if self.history_player_id is not None: _player(self.history_player_id)
        if (self.origin in ('history','played_history')) != (self.history_player_id is not None):
            raise ValueError('Indirect Battlecry history requires its owner')
        if (self.controller_policy not in ('captured','current') or
                self.controller_policy == 'current' and self.origin != 'played_history' or
                self.controller_policy == 'captured' and self.history_player_id not in (None,self.player_id)):
            raise ValueError('Invalid indirect Battlecry controller policy')
        if type(self.exclude_source_target) is not bool: raise ValueError('Expected source target exclusion boolean')
        if (self.origin not in ('effect','history','played_history') or
                (self.origin == 'history') != (self.history_id is not None) or
                (self.origin == 'played_history') != (self.history_play_id is not None)):
            raise ValueError('Invalid indirect Battlecry origin')
        effect_policies(self.targeting,self.target_id,self.choices)


@dataclass(frozen=True)
class ResolveIndirectBattlecry(Effect):
    record_id: int

    def __post_init__(self): _integer(self.record_id,'Battlecry payload record',1)


def trigger(r,effect):
    from .battlecries import capture
    from .zones import source_exists
    effect.__post_init__(); source_exists(r,effect.source_id)
    entity=live_minion(r.state,effect.subject)
    if entity is None:
        r.stale(effect,effect.subject.entity_id); return ()
    from .indirect_body_targets import start, connected_carrier
    if effect.profile_id is not None:
        return start(r,effect,entity)
    if connected_carrier(r.registry,entity.card_id):
        raise ResolutionError('Independent target carrier requires its own indirect origin producer')
    # Acceptance freezes every declared payload. Later deaths, silence or morphs
    # do not substitute the next ability in an already accepted sequence.
    from .held_opponent_copies import freeze_carrier
    return tuple(BeginIndirectBattlecry(entity.id,entity.controller,entity.card_id,p,
        caster_id=effect.source_id,target_id=effect.target_id,targeting=effect.targeting,
        choices=effect.choices,held_opponent_copy=freeze_carrier(r.state,r.registry,entity,p)) for p in capture(entity))


def historical_record(state,record_id,player_id):
    from .battlecries import battlecry_record
    b=battlecry_record(state,record_id)
    if b.player_id != player_id or not b.completed or b.failure is not None:
        raise ValueError('Historical Battlecry must be a completed successful activation of this player')
    return b


def carrier_card(state,registry,source_id):
    entity=state.entities.get(source_id)
    if entity is None or entity.kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO):
        raise ValueError('Indirect Battlecry requires a character or weapon carrier')
    # Preserve the accepted carrier identity when its own payload has morphed it.
    active=next((b for b in reversed(state.battlecry_history) if b.source_id == source_id and
        not b.completed and not b.interrupted),None)
    card=active.card_id if active else entity.card_id
    registry.card(card)
    return card


def repeat(r,effect):
    effect.__post_init__()
    original=historical_record(r.state,effect.history_id,effect.player_id)
    card=carrier_card(r.state,r.registry,effect.source_id)
    return (BeginIndirectBattlecry(effect.source_id,effect.player_id,card,original.payload,'history',
        original.id,effect.source_id,effect.target_id,effect.targeting,effect.choices,history_player_id=effect.player_id,
        historical_profile_id=effect.profile_id),)


def repeat_many(r,effect):
    effect.__post_init__(); carrier_card(r.state,r.registry,effect.source_id)
    records=battlecry_history_candidates(r.state,effect.player_id,effect.query)
    if effect.selection == 'first': records=records[:1]
    elif effect.selection == 'last': records=records[-1:]
    if len(records) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Battlecry history sequence exceeds resolution budget')
    if effect.order == 'random': records=tuple(r.game._rng.sample(records,len(records)))
    # Materialize once. New child activations cannot extend their own sequence.
    return tuple(RepeatBattlecry(effect.player_id,effect.source_id,b.id,choices=effect.choices,
        profile_id=effect.profile_id) for b in records)


def validate_payload(state,registry,source_id,card_id,payload,caster_id=None):
    registry.behavior(payload.behavior_id)
    if (source_id not in state.entities or caster_id is not None and caster_id not in state.entities or
            registry.card(card_id).kind not in (CardType.MINION,CardType.WEAPON,CardType.HERO) or
            payload.ability_id >= state.next_attachment_id or
            registry.card(payload.card_id).battlecry != payload.behavior_id):
        raise ValueError('Invalid indirect Battlecry payload provenance')


def validate_start(state,registry,effect):
    effect.__post_init__()
    from .held_opponent_copies import indirect_fact
    indirect_fact(state, registry, effect)
    if effect.historical_body_id is not None:
        from .historical_body_targets import accepted_start
        accepted_start(state,effect)
    elif effect.historical_profile_id is not None:
        from .historical_body_targets import authority
        authority(registry,effect)
    elif effect.origin in ('history','played_history') and any(card == effect.card_id for card,_ in registry.historical_battlecry_bindings):
        raise ValueError('Historical carrier requires its own connected target producer')
    from .indirect_body_targets import accepted_start,connected_carrier
    if effect.indirect_body_id is not None:
        accepted_start(state,effect)
    elif effect.origin == 'effect' and effect.physical_child_id is None and connected_carrier(registry,effect.card_id):
        raise ValueError('Independent target carrier requires its own indirect origin producer')
    validate_payload(state,registry,effect.source_id,effect.card_id,effect.payload,effect.caster_id)
    if effect.controller_policy == 'current' and state.entities[effect.source_id].controller != effect.player_id:
        raise ValueError('Indirect Battlecry execution player differs from current controller')
    if effect.history_id is not None:
        original=historical_record(state,effect.history_id,effect.history_player_id)
        if effect.payload != original.payload: raise ValueError('Historical Battlecry payload differs')
    if effect.history_play_id is not None:
        from .played_battlecries import validate_played_payload
        validate_played_payload(state,effect.history_play_id,effect.history_player_id,effect.payload)


def begin(r,effect,*,historical_sequence=None):
    from .battlecries import FinishBattlecry
    if effect.historical_profile_id is not None and effect.historical_body_id is None:
        from .historical_body_targets import accept
        return accept(r,effect,historical_sequence)
    validate_start(r.state,r.registry,effect)
    source=deepcopy(r.state.entities[effect.source_id]); source.controller=effect.player_id
    # Target restrictions belong to the declaring ability, not its new carrier.
    definition=r.registry.card(effect.payload.card_id)
    if effect.payload.carved_spell_id is not None:
        from .carved_spells import spell_target_definition
        definition=spell_target_definition(r.registry,definition,effect.payload.carved_spell_id)
    if effect.historical_body_id is not None:
        from .historical_body_targets import accepted_start
        accepted=accepted_start(r.state,effect)
        target,failure=accepted.selection.target_id,accepted.selection.failure
    elif effect.indirect_body_id is not None:
        from .indirect_body_targets import accepted_start
        accepted=accepted_start(r.state,effect)
        target,failure=accepted.selection.target_id,accepted.selection.failure
    elif effect.physical_child_id is not None:
        from .whole_card_physical import child_for
        from .generated_body_targets import target_for,failure_for
        progress=child_for(r.state,effect.physical_child_id).physical
        if progress.body_targets is not None:
            target=target_for(progress,effect.payload,'battlecry')
            failure=failure_for(r,progress,effect.payload,'battlecry')
        else:
            target,failure=select_effect_target(r,source,definition,effect.targeting,effect.target_id,
                excluded_ids=(source.id,) if effect.exclude_source_target else ())
    else:
        target,failure=select_effect_target(r,source,definition,effect.targeting,effect.target_id,
            excluded_ids=(source.id,) if effect.exclude_source_target else ())
    parent=next((b.id for b in reversed(r.state.battlecry_history) if not b.completed and not b.interrupted),None)
    from .held_opponent_copies import indirect_fact
    record=BattlecryRecord(len(r.state.battlecry_history)+1,effect.source_id,effect.player_id,
        effect.card_id,r.state.turn,r.state.action_number,target,None,effect.payload,None,
        origin=effect.origin,caster_id=effect.caster_id,history_id=effect.history_id,parent_id=parent,
        choices=effect.choices,failure=failure,payload_started=False,history_play_id=effect.history_play_id,
        history_player_id=effect.history_player_id,controller_policy=effect.controller_policy,
        exclude_source_target=effect.exclude_source_target, physical_child_id=effect.physical_child_id,
        outcome_id=effect.outcome_id, iteration=effect.iteration, repeat_index=effect.repeat_index,
        indirect_body_id=effect.indirect_body_id,historical_body_id=effect.historical_body_id,
        held_opponent_copy=indirect_fact(r.state,r.registry,effect))
    validate_indirect_record(r.state,r.registry,record,before_binding=True)
    r.state.battlecry_history.append(record)
    if effect.physical_child_id is not None:
        from .whole_card_physical import bind_actual_battlecry
        bind_actual_battlecry(r, effect, record)
    r.emit('battlecry_started',source_id=record.source_id,target_id=target,player_id=record.player_id,
        battlecry_id=record.id,origin=record.origin,history_id=record.history_id)
    return (ResolveIndirectBattlecry(record.id),FinishBattlecry(record.id))


def resolve(r,effect):
    from .battlecries import battlecry_record
    b=battlecry_record(r.state,effect.record_id)
    if b.origin == 'hand' or b.completed or b.interrupted or b.payload_started:
        raise ResolutionError('Invalid indirect Battlecry payload progress')
    if b.failure is not None: return ()
    b=replace(b,payload_started=True); r.state.battlecry_history[b.id-1]=b
    return (r.call(b.payload.behavior_id,b.source_id,b.player_id,b.target_id,battlecry=b),)


def automatic_choice(r,choice,options,on_select):
    from .battlecries import active_battlecry
    from .choices import random_choice_effects
    b=active_battlecry(r.state,choice.source_id,choice.player_id)
    if b is None or b.choices != 'random': return None
    return random_choice_effects(r,choice,options,on_select,'battlecry_choice_randomized',battlecry_id=b.id)


def validate_indirect_record(state,registry,record,*,before_binding=False):
    record.__post_init__()
    from .held_opponent_copies import validate_battlecry
    validate_battlecry(state, registry, record)
    if (record.origin in ('history','played_history') and record.historical_body_id is None and
            any(card == record.card_id for card,_ in registry.historical_battlecry_bindings)):
        raise ValueError('Historical record requires its own connected target producer')
    validate_payload(state,registry,record.source_id,record.card_id,record.payload,record.caster_id)
    if (record.target_id is not None and record.target_id not in state.entities or
            record.interrupted and state.status == 'playing'):
        raise ValueError('Invalid indirect Battlecry target or interruption')
    if record.physical_child_id is not None:
        from .whole_card_physical import validate_generated_battlecry
        validate_generated_battlecry(state, registry, record, before_binding=before_binding)
    if record.indirect_body_id is not None:
        from .indirect_body_targets import validate_record as validate_bound_record
        validate_bound_record(state,registry,record)
    if record.historical_body_id is not None:
        from .historical_body_targets import validate_record as validate_historical_record
        validate_historical_record(state,registry,record)
    if record.history_id is not None:
        original=historical_record(state,record.history_id,record.history_player_id)
        if original.id >= record.id or original.payload != record.payload:
            raise ValueError('Historical Battlecry source or captured payload differs')
    if record.history_play_id is not None:
        from .played_battlecries import validate_played_payload
        original=validate_played_payload(state,record.history_play_id,record.history_player_id,record.payload)
        if original.action > record.action:
            raise ValueError('Played Battlecry source is newer than its activation')
    if record.parent_id is not None:
        from .battlecries import battlecry_record
        parent=battlecry_record(state,record.parent_id)
        if (parent.id >= record.id or parent.action > record.action or parent.turn != record.turn or
                parent.completed and not record.completed or
                parent.interrupted and not(record.completed or record.interrupted)):
            raise ValueError('Invalid nested Battlecry parent')


def validate_boundary(game):
    from .historical_body_targets import validate_boundary as validate_historical_boundary
    validate_historical_boundary(game)
    from .indirect_body_targets import validate_boundary as validate_bound_boundary
    validate_bound_boundary(game)
    from .played_battlecries import validate_boundary as validate_played_boundary
    validate_played_boundary(game)
    from .battlecries import FinishBattlecry, battlecry_record
    state=game._state
    queue=(*game._frame.prefix,*game._frame.continuation) if game._frame else ()
    expected=[]
    for b in state.battlecry_history:
        if b.origin == 'hand' or b.completed or b.interrupted: continue
        end=FinishBattlecry(b.id)
        if end not in queue: raise ValueError('Missing indirect Battlecry completion')
        if not b.payload_started:
            marker=ResolveIndirectBattlecry(b.id)
            # Failed attempts still consume the typed resolver before completion.
            if b.failure is None:
                expected.append(marker)
                if marker not in queue or queue.index(marker) >= queue.index(end):
                    raise ValueError('Indirect Battlecry lost its payload start')
            elif marker in queue: expected.append(marker)
        if b.parent_id is not None:
            parent=FinishBattlecry(b.parent_id)
            if parent not in queue or queue.index(end) >= queue.index(parent):
                raise ValueError('Nested Battlecry must finish before its parent')
    actual=[w for w in queue if type(w) is ResolveIndirectBattlecry]
    if actual != list(reversed(expected)): raise ValueError('Indirect Battlecry start markers differ')
    for w in queue:
        if type(w) is BeginIndirectBattlecry: validate_start(state,game.registry,w)
        elif type(w) is RepeatBattlecry:
            w.__post_init__(); historical_record(state,w.history_id,w.player_id)
            carrier_card(state,game.registry,w.source_id)
        elif type(w) is ResolveIndirectBattlecry: battlecry_record(state,w.record_id)


def register(mechanics):
    from .indirect_body_targets import register as register_bound_targets
    register_bound_targets(mechanics)
    from .historical_body_targets import register as register_historical_targets
    register_historical_targets(mechanics)
    from .played_battlecries import register as register_played
    register_played(mechanics)
    mechanics.register_payload_type(BattlecryHistoryQuery)
    for effect,handler in ((TriggerBattlecry,trigger),(RepeatBattlecry,repeat),
            (RepeatBattlecries,repeat_many),(BeginIndirectBattlecry,begin),(ResolveIndirectBattlecry,resolve)):
        mechanics.register(effect,handler)
