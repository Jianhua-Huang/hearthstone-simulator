"""One-shot native extra bodies owned by the next accepted hand spell.

Ordinary player programs are transferred into the existing physical CAST.
The shared interpreter executes their ordinary effects after the base body.
"""
from dataclasses import asdict, dataclass, replace
import json

from .effects import Effect, _integer
from .errors import ResolutionError
from .model import CardType, PlayerEffect, PlayerEffectSpec, SpellSchool

INSTALLED = 'next_spell_body_installed'
CLAIMED = 'next_spell_body_claimed'
REMOVED = 'next_spell_body_removed'
STARTED = 'next_spell_body_started'
FINISHED = 'next_spell_body_finished'


@dataclass(frozen=True)
class NextSpellBodyProfile:
    program_id: str
    card_id: str
    behavior_id: str
    school: SpellSchool = SpellSchool.SHADOW


@dataclass(frozen=True)
class AdjacentSpellBodyProfile:
    """This turn's next accepted spell repeats its full text on its neighbors."""
    program_id: str
    card_id: str


def validate_profile(registry, profile):
    if type(profile) is AdjacentSpellBodyProfile:
        if (registry.player_effect(profile.program_id) !=
                PlayerEffectSpec(profile.program_id, profile.card_id, kind='next_spell_adjacent') or
                registry.card(profile.card_id).kind != CardType.SPELL):
            raise ValueError('Adjacent spell bodies require their independent current-turn spell program')
        return
    if type(profile) is not NextSpellBodyProfile or type(profile.school) is not SpellSchool:
        raise ValueError('Next spell body requires a typed source and school profile')
    if registry.player_effect(profile.program_id) != PlayerEffectSpec(profile.program_id, profile.card_id):
        raise ValueError('Next spell body requires an independent stat-free persistent program')
    if registry.card(profile.card_id).kind != CardType.SPELL:
        raise ValueError('Native next spell body requires its real spell source')
    registry.behavior(profile.behavior_id)


def validate_material(rows, turn):
    if type(rows) is not tuple or any(type(e) is not PlayerEffect for e in rows):
        raise ValueError('Next spell bodies require immutable original player programs')
    for e in rows:
        e.__post_init__()
        if (e.created_turn > turn or e.remaining_turns is not None or e.adaptations or e.aura_duration_grants or
                any(getattr(e, key) is not None for key in ('source_allocation', 'source_player_id',
                    'cost_modifier_id', 'aura_duration_cast_id', 'spell_aura_id', 'spell_aura_card_id',
                    'spell_aura_player_id', 'investigation', 'issued_spell_set'))):
            raise ValueError('Next spell body borrowed unrelated player-program material')
    if any(a.id >= b.id or a.entered_order >= b.entered_order for a, b in zip(rows, rows[1:])):
        raise ValueError('Next spell bodies require original unique acquisition order')


def material_json(rows):
    return json.dumps([asdict(e) for e in rows], ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def instance_profile(registry, instance):
    profile = registry.next_spell_body_profiles.get(instance.spec_id)
    if profile is None or instance.source_card_id != profile.card_id:
        raise ValueError('Next spell body lost its original registered source')
    validate_profile(registry, profile)
    return profile


def note_install(r, instance):
    if instance.spec_id not in r.registry.next_spell_body_profiles: return
    from .spell_casts import active_cast
    profile = instance_profile(r.registry, instance)
    cast = active_cast(r.state, instance.source_id, r.state.entities[instance.source_id].controller)
    if (cast is None or cast.card_id != profile.card_id or not cast.payload_started or cast.failure is not None):
        raise ResolutionError('Next spell body requires its actual active source spell')
    validate_material((instance,), r.state.turn)
    r.emit(INSTALLED, source_id=instance.source_id, player_id=cast.player_id, cast_id=cast.id,
        material_json=material_json((instance,)), _capture=False)


def note_removal(r, player_id, instance):
    if instance.spec_id in r.registry.next_spell_body_profiles:
        r.emit(REMOVED, source_id=instance.source_id, player_id=player_id, instance_id=instance.id, _capture=False)


def matches(registry, instance, record):
    profile = instance_profile(registry, instance)
    if type(profile) is AdjacentSpellBodyProfile:
        return instance.created_turn == record.turn
    return record.origin == 'hand' and profile.school == registry.card(record.card_id).spell_school


def presence(fact):
    return tuple(getattr(fact, k) for k in
        ('entity_id', 'card_id', 'kind', 'owner', 'controller', 'zone', 'zone_epoch', 'entered_order'))


def validate_board(record):
    """The original physical board is material, never a later board query."""
    from .allocation_facts import SourceAllocationFact
    from .model import Zone
    board = record.next_spell_body_board
    behaviors = record.next_spell_body_behaviors
    if type(behaviors) is not tuple or any(type(b) is not str or not b for b in behaviors):
        raise ValueError('Adjacent spell bodies require their complete original behavior vector')
    if board is None:
        if behaviors: raise ValueError('Fixed extra bodies cannot borrow an adjacent payload')
        return
    if type(board) is not tuple or any(type(f) is not SourceAllocationFact for f in board):
        raise ValueError('Adjacent bodies require immutable complete original board facts')
    for fact in board:
        fact.__post_init__()
        if fact.zone != Zone.BOARD or fact.kind not in (CardType.MINION, CardType.LOCATION):
            raise ValueError('Adjacent spell board contains a non-board occupant')
    if len({f.entity_id for f in board}) != len(board):
        raise ValueError('Adjacent spell board repeats a physical occupant')
    target = record.target_origin
    if target is None or target.zone != Zone.BOARD or target.kind != CardType.MINION:
        if board: raise ValueError('Untargeted or non-minion spell borrowed an adjacent board')
        return
    roots = tuple(f for f in board if f.entity_id == record.target_id)
    if len(roots) != 1 or presence(roots[0]) != presence(target):
        raise ValueError('Adjacent board lost its original primary minion')
    bounds = (board[0].next_entity_id, board[0].next_order)
    if any(f.controller != target.controller or (f.next_entity_id, f.next_order) != bounds for f in board):
        raise ValueError('Adjacent board changed its original controller or allocation window')


def neighbors(record):
    validate_board(record)
    board = record.next_spell_body_board
    if not board: return ()
    index = next(i for i, f in enumerate(board) if f.entity_id == record.target_id)
    return tuple(board[i] for i in (index-1, index+1) if 0 <= i < len(board)
        and board[i].kind == CardType.MINION)


def body_slots(registry, record):
    validate_board(record)
    profiles = tuple(instance_profile(registry, e) for e in record.next_spell_body_effects)
    adjacent = any(type(p) is AdjacentSpellBodyProfile for p in profiles)
    if adjacent != (record.next_spell_body_board is not None):
        raise ValueError('Extra spell body board differs from its actual source profiles')
    slots = []
    for instance, profile in zip(record.next_spell_body_effects, profiles):
        if not matches(registry, instance, record):
            raise ValueError('Extra body changed its original cast eligibility')
        targets = neighbors(record) if type(profile) is AdjacentSpellBodyProfile else (record.target_origin,)
        slots.extend((instance, target, type(profile) is AdjacentSpellBodyProfile) for target in targets)
    return tuple(slots)


def body_target(registry, record):
    """The physical CAST stays unchanged; an executing body owns its own arrow."""
    if record.next_spell_body_cursor % 2:
        slots = body_slots(registry, record)
        index = record.next_spell_body_cursor // 2
        if index >= len(slots): raise ValueError('Running spell body lost its original slot')
        return slots[index][1]
    return record.target_origin


def body_target_id(registry, record):
    fact = body_target(registry, record)
    return None if fact is None else fact.entity_id


def adjacent_body_index(registry, record):
    """A running adjacent body has one original slot, independent of its CAST."""
    if record.next_spell_body_cursor % 2:
        index = record.next_spell_body_cursor // 2
        slots = body_slots(registry, record)
        if index >= len(slots): raise ValueError('Running adjacent body lost its original slot')
        if slots[index][2]: return index
    return None


def possible_body_target_ids(registry, record):
    return {f.entity_id for f in (record.target_origin, *(s[1] for s in body_slots(registry, record)))
        if f is not None}


def legal_neighbor(r, record, fact):
    from .allocation_facts import SourceAllocationFact
    from .choose_one import effective
    from .spell_casts import CONDITIONS, effective_definition
    from .targeting import accepts_target, effect_target_context
    target = r.state.entities.get(fact.entity_id)
    if target is None or presence(SourceAllocationFact.capture(r.state, target)) != presence(fact):
        return False
    source = r.state.entities[record.source_id]
    definition = effective(effective_definition(r.registry.card(record.card_id),
        {key: getattr(record, key) for key in CONDITIONS}), record.branch_id)
    return accepts_target(r.state, r.registry, source, definition, fact.entity_id,
        context_factory=effect_target_context(r, source), automatic=False)


def claim(r, record):
    if not r.registry.next_spell_body_profiles: return record
    if record.next_spell_body_effects or record.next_spell_body_cursor:
        raise ResolutionError('Next spell bodies require one new physical payload acceptance')
    rows = tuple(sorted((e for e in r.player(record.player_id).player_effects
        if e.spec_id in r.registry.next_spell_body_profiles and
            matches(r.registry, e, record)), key=lambda e: e.id))
    if not rows: return record
    validate_material(rows, record.turn)
    board, behaviors = None, ()
    if any(type(instance_profile(r.registry, e)) is AdjacentSpellBodyProfile for e in rows):
        if record.spell_target_group is not None or record.spell_target_receipt is not None:
            profile = r.registry.spell_target_group_profiles.get(record.card_id)
            if profile is None or profile.count != 2 or record.spell_target_receipt is None:
                from .registry import UnsupportedDefinitionError
                raise UnsupportedDefinitionError('Adjacent grouped bodies require an actual registered two-arrow receipt')
        from .allocation_facts import SourceAllocationFact
        from .lifecycle import active_abilities
        from .model import Zone
        target = r.state.entities.get(record.target_id)
        board = (() if target is None or target.kind != CardType.MINION or target.zone != Zone.BOARD else
            tuple(SourceAllocationFact.capture(r.state, r.state.entities[i])
                for i in r.player(target.controller).board))
        if record.play_id is not None:
            from .play_history import play_record
            behaviors = play_record(r.state, record.play_id).spell_payload.behavior_ids
        else:
            behaviors = tuple(a.behavior_id for a in active_abilities(r.state.entities[record.source_id], 'on_play'))
    accepted = replace(record, next_spell_body_effects=rows, next_spell_body_board=board,
        next_spell_body_behaviors=behaviors)
    r.state.cast_history[record.id-1] = accepted
    ids = {e.id for e in rows}
    r.player(record.player_id).player_effects = [e for e in r.player(record.player_id).player_effects if e.id not in ids]
    extra = {} if board is None else dict(adjacent_board_json=json.dumps([asdict(f) for f in board],
        ensure_ascii=False, sort_keys=True, separators=(',', ':')), adjacent_behaviors=behaviors)
    r.emit(CLAIMED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        material_json=material_json(rows), **extra, _capture=False)
    from .player_effects import public_effect
    for e in rows:
        r.emit('player_effect_removed', source_id=e.source_id, player_id=record.player_id,
            **public_effect(r.registry, e))
    return accepted


@dataclass(frozen=True)
class ContinueNextSpellBodies(Effect):
    cast_id: int
    index: int = 0

    def __post_init__(self):
        _integer(self.cast_id, 'next spell body cast', 1); _integer(self.index, 'next spell body index', 0)


@dataclass(frozen=True)
class FinishNextSpellBody(ContinueNextSpellBodies):
    pass


def original_record(r, effect):
    from .spell_casts import cast_record
    effect.__post_init__(); record = cast_record(r.state, effect.cast_id)
    if (not record.payload_started or record.completed or record.interrupted or record.failure is not None or
            effect.index > len(body_slots(r.registry, record))):
        raise ResolutionError('Next spell body lost its actual unfinished parent cast')
    active = next((c for c in reversed(r.state.cast_history)
        if c.payload_started and not c.completed and not c.interrupted), None)
    if active is None or active.id != record.id:
        raise ResolutionError('Next spell body overtook another active physical cast')
    return record


def advance(r, effect):
    record = original_record(r, effect)
    slots = body_slots(r.registry, record)
    if record.next_spell_body_cursor != 2*effect.index:
        raise ResolutionError('Next spell body changed its original execution cursor')
    if effect.index == len(slots): return ()
    instance, target, adjacent = slots[effect.index]
    profile = instance_profile(r.registry, instance)
    record = replace(record, next_spell_body_cursor=record.next_spell_body_cursor+1)
    r.state.cast_history[record.id-1] = record
    extra = dict(target_id=target.entity_id, valid_target=legal_neighbor(r, record, target)) if adjacent else {}
    r.emit(STARTED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        index=effect.index, instance_id=instance.id, **extra, _capture=False)
    if adjacent:
        from .spell_casts import payload_effects
        from .play_history import play_record
        play = None if record.play_id is None else play_record(r.state, record.play_id)
        work = (payload_effects(r, record, record.next_spell_body_behaviors, play=play, extra_outcome=True)
            if extra['valid_target'] else ())
        return (*work, FinishNextSpellBody(record.id, effect.index), ContinueNextSpellBodies(record.id, effect.index+1))
    return (r.call(profile.behavior_id, record.source_id, record.player_id, record.target_id, cast=record),
        FinishNextSpellBody(record.id, effect.index), ContinueNextSpellBodies(record.id, effect.index+1))


def finish(r, effect):
    record = original_record(r, effect)
    slots = body_slots(r.registry, record)
    if (effect.index == len(slots) or
            record.next_spell_body_cursor != 2*effect.index+1):
        raise ResolutionError('Next spell body completion lost its original running slot')
    instance, target, adjacent = slots[effect.index]
    r.state.cast_history[record.id-1] = replace(record, next_spell_body_cursor=record.next_spell_body_cursor+1)
    r.emit(FINISHED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        index=effect.index, instance_id=instance.id, **(dict(target_id=target.entity_id) if adjacent else {}), _capture=False)


def validate_queued(state, registry, effect):
    from .spell_casts import cast_record
    effect.__post_init__(); record = cast_record(state, effect.cast_id)
    if (not record.payload_started or record.completed or record.interrupted or record.failure is not None or
            effect.index > len(body_slots(registry, record))):
        raise ValueError('Saved next spell body lost its original unfinished parent')
    for row in record.next_spell_body_effects: instance_profile(registry, row)
    cursor = record.next_spell_body_cursor
    if type(effect) is FinishNextSpellBody:
        if not cursor % 2 or effect.index != cursor//2:
            raise ValueError('Saved next spell completion differs from its original running slot')
    elif effect.index != (cursor+1)//2:
        raise ValueError('Saved next spell continuation skipped or repeated its original slot')


def validate_game(game):
    from .hero_health_history import effective_events
    from .serialization import player_effect_from_dict
    from .spell_casts import cast_record
    state, registry = game._state, game.registry
    if not registry.next_spell_body_profiles:
        if any(c.next_spell_body_effects or c.next_spell_body_cursor or c.next_spell_body_board is not None or
                c.next_spell_body_behaviors for c in state.cast_history):
            raise ValueError('Saved next spell bodies have no registered source profiles')
        return
    pending, plans, cursors, installed = {}, {}, {}, set()
    for event in effective_events(game._events):
        if event.kind not in (INSTALLED, CLAIMED, REMOVED, STARTED, FINISHED): continue
        d = dict(event.data)
        if event.kind == INSTALLED:
            rows = tuple(player_effect_from_dict(x) for x in json.loads(d['material_json']))
            if len(rows) != 1: raise ValueError('Next spell installation requires one original program')
            instance, = rows; validate_material(rows, state.turn); profile = instance_profile(registry, instance)
            cast = cast_record(state, d['cast_id'])
            if (instance.id in installed or instance.id >= state.next_attachment_id or instance.entered_order >= state.next_order or
                    instance.source_id != event.source_id or
                    (cast.source_id, cast.player_id, cast.card_id) != (event.source_id, event.player_id, profile.card_id) or
                    not cast.payload_started or cast.failure is not None or event.sequence <= cast.recorded_event):
                raise ValueError('Next spell installation lost its original spell acceptance')
            installed.add(instance.id)
            pending[instance.id] = (event.player_id, instance)
        elif event.kind == REMOVED:
            saved = pending.pop(d['instance_id'], None)
            if saved is None or saved[0] != event.player_id or saved[1].source_id != event.source_id:
                raise ValueError('Next spell removal borrowed another original instance')
        elif event.kind == CLAIMED:
            cast = cast_record(state, d['cast_id'])
            rows = tuple(player_effect_from_dict(x) for x in json.loads(d['material_json']))
            validate_material(rows, cast.turn)
            expected = tuple(e for owner, e in sorted(pending.values(), key=lambda row: row[1].id)
                if owner == cast.player_id and matches(registry, e, cast))
            from .allocation_facts import allocation_from_dict, validate_allocation
            raw_board = json.loads(d['adjacent_board_json']) if 'adjacent_board_json' in d else None
            board = None if raw_board is None else tuple(allocation_from_dict(f) for f in raw_board)
            if board != cast.next_spell_body_board or tuple(d.get('adjacent_behaviors', ())) != cast.next_spell_body_behaviors:
                raise ValueError('Adjacent spell body changed its original board or complete payload')
            for fact in board or (): validate_allocation(state, registry, fact)
            for behavior in cast.next_spell_body_behaviors: registry.behavior(behavior)
            body_slots(registry, cast)
            if (cast.id in plans or not rows or rows != expected or
                    not cast.payload_started or cast.failure is not None or
                    (cast.source_id, cast.player_id) != (event.source_id, event.player_id) or event.sequence <= cast.recorded_event):
                raise ValueError('Next spell claim changed its complete original acceptance plan')
            plans[cast.id] = rows; cursors[cast.id] = 0
            for e in rows: pending.pop(e.id)
        else:
            cast = cast_record(state, d['cast_id']); rows = plans.get(cast.id, ())
            slots = body_slots(registry, cast)
            index = d['index']; cursor = cursors.get(cast.id, 0)
            if type(index) is not int or not 0 <= index < len(slots):
                raise ValueError('Next spell body proof lost its original slot index')
            expected = 2*index + (1 if event.kind == FINISHED else 0)
            instance, target, adjacent = slots[index]
            if adjacent and (event.target_id != target.entity_id or
                    event.kind == STARTED and type(d.get('valid_target')) is not bool):
                raise ValueError('Adjacent spell body changed its original execution target')
            if (instance.id != d['instance_id'] or
                    cursor != expected or (cast.source_id, cast.player_id) != (event.source_id, event.player_id)):
                raise ValueError('Next spell body proof changed its original ordered execution')
            cursors[cast.id] = cursor+1
    for cast in state.cast_history:
        if cast.next_spell_body_effects != plans.get(cast.id, ()) or cast.next_spell_body_cursor != cursors.get(cast.id, 0):
            raise ValueError('Saved next spell bodies differ from their original claim and execution proof')
        if cast.completed and not cast.interrupted and cast.next_spell_body_cursor != 2*len(body_slots(registry, cast)):
            raise ValueError('Completed spell omitted an accepted extra body')
    live = {e.id:(pid,e) for pid,p in state.players.items() for e in p.player_effects
        if e.spec_id in registry.next_spell_body_profiles}
    if pending != live: raise ValueError('Saved pending spell bodies differ from original installations and consumption')


def register(mechanics):
    mechanics.register(ContinueNextSpellBodies, advance)
    mechanics.register(FinishNextSpellBody, finish)
