"""Source-specific discarded cards, delegated to the ordinary five executors.

Occurrence-weighted sampling without replacement and material inheritance are
local policies pending CN calibration. Summoned minions do not run Battlecries.
"""
from dataclasses import asdict, dataclass, replace
import json
from random import Random

from .effects import Effect, _integer
from .model import CardType, PrisonPlaybackState, Zone

MATERIAL = 'prison_discard_material'
ACCEPTED = 'prison_play_accepted'
FINISHED = 'prison_play_finished'


def pack(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


@dataclass(frozen=True)
class PrisonProfile:
    prison_card_id: str
    released_card_id: str
    guard_card_id: str
    end_behavior_id: str


def validate_profile(registry, profile):
    if type(profile) is not PrisonProfile: raise ValueError('Typed Prison profile required')
    prison, released, guard = (registry.card(cid) for cid in
        (profile.prison_card_id, profile.released_card_id, profile.guard_card_id))
    if (prison.kind != CardType.LOCATION or prison.deathrattle is None or prison.on_use is None
            or released.kind != CardType.MINION or guard.kind != CardType.MINION
            or len([t for t in released.triggers if t.behavior_id == profile.end_behavior_id
                and t.event == 'turn_ended' and t.end_turn is not None]) != 1):
        raise ValueError('Prison profile lost its actual location and classified released minion')


def prison_death(state, registry, death_id):
    _integer(death_id, 'original Prison death', 1)
    if death_id > len(state.death_history): raise ValueError('Unknown original Prison death')
    death = state.death_history[death_id-1]
    if death.card_id not in registry.prison_profiles or registry.card(death.card_id).kind != CardType.LOCATION:
        raise ValueError('Prison playback borrowed a different death')
    return death


def discards(state, registry, death_id):
    death = prison_death(state, registry, death_id)
    return tuple(row for row in state.discard_history if row.source is not None and
        (row.source.entity_id, row.source.card_id) == (death.entity_id, death.card_id) and
        (row.source.zone == Zone.BOARD and row.source.zone_epoch == death.cause.target_zone_epoch or
         row.source.zone == Zone.GRAVEYARD and row.source.zone_epoch == death.cause.target_zone_epoch+1
         and row.source.entered_order == death.cause.target_entered_order))


def validate_binding(state, registry, binding):
    if type(binding) is not PrisonPlaybackState: raise ValueError('Typed Prison playback required')
    binding.__post_init__()
    available = {row.id for row in discards(state, registry, binding.prison_death_id)}
    if not set(binding.consumed_discard_ids) <= available:
        raise ValueError('Prison memory contains another physical Prison discard')


def validate_entry_face(registry, material):
    material.__post_init__()
    if registry.card(material.card_id).kind != CardType.MINION:
        raise ValueError('Prison summon requires an actual minion')
    if material.prison_death_id is not None and material.card_id not in {
            p.released_card_id for p in registry.prison_profiles.values()}:
        raise ValueError('Prison release lost its registered minion')


def validate_entry(state, registry, material):
    validate_entry_face(registry, material)
    if material.prison_death_id is not None:
        death = prison_death(state, registry, material.prison_death_id)
        if material.card_id != registry.prison_profiles[death.card_id].released_card_id:
            raise ValueError('Prison release borrowed a different location death')
    else:
        from .discard_history import validate_base_copy
        if material.discard_id > len(state.discard_history): raise ValueError('Unknown Prison discard')
        row = state.discard_history[material.discard_id-1]
        validate_base_copy(state, registry, row)
        if row.card_id != material.card_id or row.source is None or row.source.card_id not in registry.prison_profiles:
            raise ValueError('Prison summon changed the original discarded minion')


def seed_entry(r, material, entity):
    validate_entry(r.state, r.registry, material)
    if material.prison_death_id is not None:
        death = prison_death(r.state, r.registry, material.prison_death_id)
        profile = r.registry.prison_profiles[death.card_id]
        entity.abilities = [replace(a, prison_playback=PrisonPlaybackState(death.id))
            if a.kind == 'trigger' and a.behavior_id == profile.end_behavior_id else a
            for a in entity.abilities]
    else:
        row = r.state.discard_history[material.discard_id-1]
        if row.jade_size is not None:
            from .jade import imprint
            imprint(entity, row.jade_size)
    r.refresh_auras()


def synchronize(r, event):
    """Freeze spell material after actual discard cleanup, before reactions."""
    if event.kind != 'card_discarded' or not r.registry.prison_profiles: return
    row = next((x for x in reversed(r.state.discard_history) if x.event_sequence == event.sequence), None)
    if row is None or row.source is None or row.source.card_id not in r.registry.prison_profiles: return
    if row.kind != CardType.SPELL: return
    from .copy_materials import CapturedCardCopyMaterial
    material = CapturedCardCopyMaterial.capture(r.state, r.state.entities[row.entity_id])
    r.emit(MATERIAL, source_id=row.source_id, player_id=row.player_id, discard_id=row.id,
        material=pack(asdict(material)), _capture=False)


@dataclass(frozen=True)
class PlayPrisonDiscard(Effect):
    end_turn_id: int
    def __post_init__(self): _integer(self.end_turn_id, 'Prison end-turn execution', 1)


@dataclass(frozen=True)
class FinishPrisonPlay(Effect):
    acceptance_event: int
    def __post_init__(self): _integer(self.acceptance_event, 'Prison acceptance event', 1)


def original_spell(game, row):
    from .hero_health_history import effective_events
    from .copy_materials import CapturedCardCopyMaterial, from_dict, validate_captured_card_copy
    events = [e for e in effective_events(game._events) if e.kind == MATERIAL and dict(e.data)['discard_id'] == row.id]
    if len(events) != 1: raise ValueError('Prison spell lost its complete original discarded material')
    material = from_dict(CapturedCardCopyMaterial, json.loads(dict(events[0].data)['material']))
    validate_captured_card_copy(game._state, game.registry, material)
    if (material.origin.entity_id, material.origin.card_id, material.origin.zone, material.origin.zone_epoch) != (
            row.entity_id, row.card_id, Zone.GRAVEYARD, row.card.zone_epoch+1):
        raise ValueError('Prison spell material changed its original discard')
    return material


def current_binding(game, subject):
    """Accepted repetitions share remaining occurrences, even if carrier leaves."""
    from .hero_health_history import effective_events
    binding = subject.ability.prison_playback
    for event in effective_events(game._events):
        if event.kind == ACCEPTED:
            data = json.loads(dict(event.data)['receipt'])
            if (event.source_id, data['ability_id']) == (subject.source_id, subject.ability.id):
                binding = PrisonPlaybackState(data['death_id'], tuple(data['after']))
    return binding


def play(r, effect):
    effect.__post_init__()
    from .end_turns import record
    execution = record(r.state, effect.end_turn_id)
    subject = execution.capture.subject
    if execution.execution_order is None or execution.completed or execution.skipped or subject.ability is None:
        raise ValueError('Prison play requires its actual executing end-turn body')
    profiles = [p for p in r.registry.prison_profiles.values() if p.end_behavior_id == subject.ability.behavior_id]
    if len(profiles) != 1: raise ValueError('Unknown Prison end-turn body')
    if any(e.kind == ACCEPTED and json.loads(dict(e.data)['receipt'])['end_turn_id'] == effect.end_turn_id
            for e in r.game._events): raise ValueError('Prison end-turn execution accepted twice')
    binding = current_binding(r.game, subject)
    if binding is None: return ()  # A separately generated printed Zuramat has no Prison.
    validate_binding(r.state, r.registry, binding)
    candidates = tuple(x for x in discards(r.state, r.registry, binding.prison_death_id)
        if x.id not in binding.consumed_discard_ids)
    before = r.game._rng.getstate()
    selected = None if not candidates else candidates[0] if len(candidates) == 1 else r.game._rng.choice(candidates)
    updated = binding if selected is None else replace(binding,
        consumed_discard_ids=(*binding.consumed_discard_ids, selected.id))
    entity = r.state.entities.get(subject.source_id)
    if entity is not None:
        entity.abilities = [replace(a, prison_playback=updated) if a.id == subject.ability.id else a for a in entity.abilities]
    receipt = dict(end_turn_id=effect.end_turn_id, ability_id=subject.ability.id,
        death_id=binding.prison_death_id, before=binding.consumed_discard_ids,
        after=updated.consumed_discard_ids, candidates=tuple(x.id for x in candidates),
        selected=None if selected is None else selected.id, rng_before=before, rng_after=r.game._rng.getstate(),
        discard_frontier=r.state.next_discard_id)
    accepted = r.emit(ACCEPTED, source_id=subject.source_id, player_id=subject.player_id,
        receipt=pack(receipt), _capture=False)
    tail = (FinishPrisonPlay(accepted.sequence),)
    if selected is None: return tail
    from .discard_history import validate_base_copy
    validate_base_copy(r.state, r.registry, selected)
    if selected.kind == CardType.MINION:
        from .allocation_facts import SourceAllocationFact
        from .summon_quantities import SummonByCard, PrisonEntryMaterial, SummonCause
        cause = SummonCause(SourceAllocationFact.capture(r.state, r.state.entities[subject.source_id]),
            subject.player_id, r.state.turn, r.state.action_number)
        return (SummonByCard(subject.player_id, (PrisonEntryMaterial(selected.card_id, discard_id=selected.id),), cause), *tail)
    if selected.kind == CardType.SPELL:
        from .spell_casts import automatic, CastSpell
        from .zones import copy_current_stored_state
        material = original_spell(r.game, selected)
        spell = r.create_entity(subject.player_id, selected.card_id, Zone.GRAVEYARD)
        copy_current_stored_state(r.state, material.entity(), spell)
        return (*automatic(r, CastSpell(subject.player_id, selected.card_id, subject.source_id), spell, None), *tail)
    if selected.kind in (CardType.WEAPON, CardType.LOCATION):
        from .generated_placement import InstallGeneratedPlacement, install_generated_placement
        install_generated_placement(r, InstallGeneratedPlacement(subject.player_id, selected.card_id, subject.source_id))
        return tail
    if selected.kind == CardType.HERO:
        from .generated_heroes import InstallGeneratedHeroCard, install_generated_hero_card
        install_generated_hero_card(r, InstallGeneratedHeroCard(subject.player_id, selected.card_id, subject.source_id))
        return tail
    raise ValueError('Unsupported actual Prison discard kind')


def finish(r, effect):
    event = r.game._events[effect.acceptance_event-1]
    if event.kind != ACCEPTED or any(e.kind == FINISHED and dict(e.data)['acceptance_event'] == event.sequence
            for e in r.game._events): raise ValueError('Prison Finish lost its unique original acceptance')
    r.emit(FINISHED, source_id=event.source_id, player_id=event.player_id,
        acceptance_event=event.sequence, _capture=False)
    return ()


def validate_boundary(game):
    if not game.registry.prison_profiles: return
    from .hero_health_history import effective_events
    from .end_turns import record
    from .serialization import rng_from_json
    timeline = effective_events(game._events)
    seen = {}; finished = set(); material_ids = []; executed = set()
    for event in timeline:
        if event.kind == MATERIAL: material_ids.append(dict(event.data)['discard_id'])
        if event.kind == ACCEPTED:
            data = json.loads(dict(event.data)['receipt']); execution = record(game._state, data['end_turn_id'])
            subject = execution.capture.subject
            if (execution.execution_order is None or subject.ability is None or
                    (subject.source_id, subject.player_id, subject.ability.id) !=
                    (event.source_id, event.player_id, data['ability_id'])):
                raise ValueError('Prison acceptance lost its original executing subject')
            key = (event.source_id, data['ability_id'])
            before = PrisonPlaybackState(data['death_id'], tuple(data['before']))
            validate_binding(game._state, game.registry, before)
            if key in seen and seen[key]['after'] != data['before']:
                raise ValueError('Prison playback restarted already consumed discards')
            if (subject.ability.prison_playback is None or
                    subject.ability.prison_playback.prison_death_id != before.prison_death_id or
                    data['discard_frontier'] != 1+sum(x.event_sequence < event.sequence for x in game._state.discard_history)):
                raise ValueError('Prison acceptance changed its original source or discard frontier')
            available = [x.id for x in discards(game._state, game.registry, before.prison_death_id)
                if x.event_sequence < event.sequence and x.id not in before.consumed_discard_ids]
            if available != data['candidates']: raise ValueError('Prison playback changed its complete original candidates')
            rng = Random(); rng.setstate(rng_from_json(data['rng_before']))
            selected = None if not available else available[0] if len(available) == 1 else rng.choice(available)
            after = list(before.consumed_discard_ids) + ([] if selected is None else [selected])
            if (data['selected'] != selected or data['after'] != after or
                    rng.getstate() != rng_from_json(data['rng_after'])):
                raise ValueError('Prison playback changed its original random selection or consumption')
            if data['end_turn_id'] in executed:
                raise ValueError('Prison execution accepted more than once')
            executed.add(data['end_turn_id'])
            seen[key] = data
        elif event.kind == FINISHED:
            origin = dict(event.data)['acceptance_event']
            if origin in finished or origin >= event.sequence or game._events[origin-1].kind != ACCEPTED:
                raise ValueError('Prison Finish borrowed or duplicated its original acceptance')
            finished.add(origin)
    expected = [x.id for x in game._state.discard_history if x.kind == CardType.SPELL and x.source is not None
        and x.source.card_id in game.registry.prison_profiles]
    if material_ids != expected: raise ValueError('Prison lost its complete original discarded spell material inventory')
    for value in expected: original_spell(game, game._state.discard_history[value-1])
    for entity in game._state.entities.values():
        for ability in entity.abilities:
            if ability.prison_playback is None: continue
            validate_binding(game._state, game.registry, ability.prison_playback)
            if not any(p.end_behavior_id == ability.behavior_id for p in game.registry.prison_profiles.values()):
                raise ValueError('Prison memory attached to a different behavior')
            latest = seen.get((entity.id, ability.id))
            if latest is not None and (ability.prison_playback.prison_death_id,
                    ability.prison_playback.consumed_discard_ids) != (latest['death_id'], tuple(latest['after'])):
                raise ValueError('Prison carrier changed its accepted remaining discards')
            for root in game._state.card_summon_history:
                from .summon_quantities import PrisonEntryMaterial
                if root.selected is None: continue
                material = root.request.materials[root.selected]
                if type(material) is not PrisonEntryMaterial or material.prison_death_id is None: continue
                if any(d.entity is not None and d.entity.entity_id == entity.id for d in root.deliveries) and (
                        material.prison_death_id != ability.prison_playback.prison_death_id):
                    raise ValueError('Released Prison minion borrowed another location memory')
    for execution in game._state.end_turn_history:
        ability = execution.capture.subject.ability
        if execution.completed and ability is not None and ability.prison_playback is not None and execution.id not in executed:
            raise ValueError('Completed Prison end-turn body lost its original acceptance')
    for event in timeline:
        if event.kind != ACCEPTED or event.sequence in finished: continue
        data = json.loads(dict(event.data)['receipt'])
        execution = record(game._state, data['end_turn_id'])
        if execution.completed: raise ValueError('Completed Prison body lost its original Finish')
        if game._state.status != 'playing': continue
        work = () if game._frame is None else (*game._frame.prefix, *game._frame.continuation)
        if sum(type(x) is FinishPrisonPlay and x.acceptance_event == event.sequence for x in work) != 1:
            raise ValueError('Waiting Prison body lost its unique pending Finish')


def register(mechanics):
    mechanics.register(PlayPrisonDiscard, play)
    mechanics.register(FinishPrisonPlay, finish)
