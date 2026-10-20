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


def validate_profile(registry, profile):
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


def claim(r, record):
    if record.origin != 'hand' or not r.registry.next_spell_body_profiles: return record
    if record.next_spell_body_effects or record.next_spell_body_cursor:
        raise ResolutionError('Next spell bodies require one new physical payload acceptance')
    school = r.registry.card(record.card_id).spell_school
    rows = tuple(sorted((e for e in r.player(record.player_id).player_effects
        if e.spec_id in r.registry.next_spell_body_profiles and
            instance_profile(r.registry, e).school == school), key=lambda e: e.id))
    if not rows: return record
    validate_material(rows, record.turn)
    accepted = replace(record, next_spell_body_effects=rows)
    r.state.cast_history[record.id-1] = accepted
    ids = {e.id for e in rows}
    r.player(record.player_id).player_effects = [e for e in r.player(record.player_id).player_effects if e.id not in ids]
    r.emit(CLAIMED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        material_json=material_json(rows), _capture=False)
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
            effect.index > len(record.next_spell_body_effects)):
        raise ResolutionError('Next spell body lost its actual unfinished parent cast')
    active = next((c for c in reversed(r.state.cast_history)
        if c.payload_started and not c.completed and not c.interrupted), None)
    if active is None or active.id != record.id:
        raise ResolutionError('Next spell body overtook another active physical cast')
    return record


def advance(r, effect):
    record = original_record(r, effect)
    if record.next_spell_body_cursor != 2*effect.index:
        raise ResolutionError('Next spell body changed its original execution cursor')
    if effect.index == len(record.next_spell_body_effects): return ()
    instance = record.next_spell_body_effects[effect.index]
    profile = instance_profile(r.registry, instance)
    record = replace(record, next_spell_body_cursor=record.next_spell_body_cursor+1)
    r.state.cast_history[record.id-1] = record
    r.emit(STARTED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        index=effect.index, instance_id=instance.id, _capture=False)
    return (r.call(profile.behavior_id, record.source_id, record.player_id, record.target_id, cast=record),
        FinishNextSpellBody(record.id, effect.index), ContinueNextSpellBodies(record.id, effect.index+1))


def finish(r, effect):
    record = original_record(r, effect)
    if (effect.index == len(record.next_spell_body_effects) or
            record.next_spell_body_cursor != 2*effect.index+1):
        raise ResolutionError('Next spell body completion lost its original running slot')
    instance = record.next_spell_body_effects[effect.index]
    r.state.cast_history[record.id-1] = replace(record, next_spell_body_cursor=record.next_spell_body_cursor+1)
    r.emit(FINISHED, source_id=record.source_id, player_id=record.player_id, cast_id=record.id,
        index=effect.index, instance_id=instance.id, _capture=False)


def validate_queued(state, registry, effect):
    from .spell_casts import cast_record
    effect.__post_init__(); record = cast_record(state, effect.cast_id)
    if (not record.payload_started or record.completed or record.interrupted or record.failure is not None or
            effect.index > len(record.next_spell_body_effects)):
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
        if any(c.next_spell_body_effects or c.next_spell_body_cursor for c in state.cast_history):
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
                if owner == cast.player_id and instance_profile(registry, e).school == registry.card(cast.card_id).spell_school)
            if (cast.id in plans or not rows or rows != expected or cast.origin != 'hand' or
                    not cast.payload_started or cast.failure is not None or
                    (cast.source_id, cast.player_id) != (event.source_id, event.player_id) or event.sequence <= cast.recorded_event):
                raise ValueError('Next spell claim changed its complete original acceptance plan')
            plans[cast.id] = rows; cursors[cast.id] = 0
            for e in rows: pending.pop(e.id)
        else:
            cast = cast_record(state, d['cast_id']); rows = plans.get(cast.id, ())
            index = d['index']; cursor = cursors.get(cast.id, 0)
            if type(index) is not int or not 0 <= index < len(rows):
                raise ValueError('Next spell body proof lost its original slot index')
            expected = 2*index + (1 if event.kind == FINISHED else 0)
            if (rows[index].id != d['instance_id'] or
                    cursor != expected or (cast.source_id, cast.player_id) != (event.source_id, event.player_id)):
                raise ValueError('Next spell body proof changed its original ordered execution')
            cursors[cast.id] = cursor+1
    for cast in state.cast_history:
        if cast.next_spell_body_effects != plans.get(cast.id, ()) or cast.next_spell_body_cursor != cursors.get(cast.id, 0):
            raise ValueError('Saved next spell bodies differ from their original claim and execution proof')
        if cast.completed and not cast.interrupted and cast.next_spell_body_cursor != 2*len(cast.next_spell_body_effects):
            raise ValueError('Completed spell omitted an accepted extra body')
    live = {e.id:(pid,e) for pid,p in state.players.items() for e in p.player_effects
        if e.spec_id in registry.next_spell_body_profiles}
    if pending != live: raise ValueError('Saved pending spell bodies differ from original installations and consumption')


def register(mechanics):
    mechanics.register(ContinueNextSpellBodies, advance)
    mechanics.register(FinishNextSpellBody, finish)
