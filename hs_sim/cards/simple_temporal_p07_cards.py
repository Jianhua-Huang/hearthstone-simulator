"""P07 owner-clock resources and real public three-turn Aura objectives."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import ChangeManaCrystals, GainTemporaryMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (
    CardDefinition, CardType, EndTurnSpec, Keyword, PlayerEffectSpec, SpellSchool, TriggerSpec,
)
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-temporal-p07-v1.json'
BATCH_HASH = 'e19d8ce38e010b944cdd4c03bfad297fe9b593a24fceca775239f23e212ee7e6'
POWER = 'EDR_483'
ACCELERATION = 'END_011'
CHRONOLOGICAL = 'TIME_700'
DRAKE = 'TIME_700t'
ROOTS = (POWER, ACCELERATION, CHRONOLOGICAL)
PREFIX = 'cards.simple_temporal_p07.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('P07 lost its complete reviewed source pin')
    if (tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            tuple(x['record']['id'] for x in data['dependencies']) != (DRAKE,) or
            data['existing_dependencies'] or data['skipped']):
        raise TargetValidationError('Unreviewed P07 roots or dependencies')
    for key in ('cards', 'dependencies', 'existing_dependencies', 'evidence_only', 'skipped'):
        for row in data[key]:
            if canonical_digest(row['record']) != row['record_sha256']:
                raise TargetValidationError('P07 complete source row changed')
    links = [o['face'].get('childIds') for o in data['official_observations']['observations']
             if o['card_id'] == CHRONOLOGICAL]
    if links != [[122736], [122736]]:
        raise TargetValidationError('Chronological Aura lost its exact official child identity')
    return data


def register_simple_temporal_p07_cards(registry):
    data = load_batch()

    def power_stage(c, first):
        if c.event is None or c.event.kind != 'turn_started' or c.event.player_id != c.player_id:
            return ()
        if c.player_effect is None:
            raise ResolutionError('Fractured Power lost its accepted independent stage')
        reward = (AddPlayerEffect(c.player_id, PREFIX+'power_second', c.source_id) if first else
                  ChangeManaCrystals(c.player_id, 2, filled=True))
        return RemovePlayerEffect(c.player_id, c.player_effect.id), reward

    registry.register_behavior(PREFIX+'power', lambda c: (
        ChangeManaCrystals(c.player_id, -1), AddPlayerEffect(c.player_id, PREFIX+'power_first', c.source_id)))
    for name, first in (('power_first', True), ('power_second', False)):
        registry.register_behavior(PREFIX+name, lambda c, first=first: power_stage(c, first))
        # Finite native persistent stages reuse the original captured-start
        # inventory and do not occupy the Objective/secret area.
        registry.register_player_effect(PlayerEffectSpec(PREFIX+name, POWER,
            triggers=(TriggerSpec('turn_started', PREFIX+name),)))
    registry.register_behavior(PREFIX+'acceleration', lambda c: (
        (GainTemporaryMana(c.player_id, 1),) if c.event.player_id == c.player_id else ()))
    registry.register_behavior(PREFIX+'drake', lambda c: (
        SummonByCard(c.player_id, (SummonEntryMaterial(DRAKE),), SummonCause.capture(c)),))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'acceleration', ACCELERATION,
        kind='aura', duration=3, tick_event='turn_started',
        triggers=(TriggerSpec('turn_started', PREFIX+'acceleration'),)))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'chronological', CHRONOLOGICAL,
        kind='aura', duration=3, tick_event='turn_ended',
        triggers=(TriggerSpec('turn_ended', PREFIX+'drake', EndTurnSpec()),)))
    for row in data['cards'] + data['dependencies']:
        raw = row['record'];cid = raw['id']
        kwargs = {}
        if cid == DRAKE:
            if (raw['dbf_id'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CARDRACE'),
                    raw['tags'].get('TAUNT'), raw['collectible']) != (122736, 4, 3, 5, 24, 1, False):
                raise TargetValidationError('Unknown complete Chronological Drake face')
            kind = CardType.MINION
            kwargs.update(attack=3, health=5, keywords=(Keyword.TAUNT,))
        else:
            if raw['type'] != 'SPELL' or raw['collectible'] is not True:
                raise TargetValidationError('P07 requires the complete collectible spell face')
            kind = CardType.SPELL
            if cid == POWER:
                if 'OBJECTIVE' in raw['tags'] or raw['tags'].get('SPELL_SCHOOL') != 6:
                    raise TargetValidationError('Fractured Power is an ordinary Shadow spell')
                kwargs.update(on_play=PREFIX+'power', spell_school=SpellSchool.SHADOW)
            else:
                if tuple(raw['tags'].get(k) for k in ('OBJECTIVE','PALADIN_AURA',
                        'TAG_SCRIPT_DATA_NUM_1','QUEST_PROGRESS_TOTAL','SPELL_SCHOOL')) != (1,1,3,3,5):
                    raise TargetValidationError('P07 Aura lost its real three-turn Objective face')
                kwargs.update(ongoing_effect_id=PREFIX+('acceleration' if cid == ACCELERATION else 'chronological'),
                              spell_school=SpellSchool.HOLY)
        card = CardDefinition(cid, raw['name'], kind, cost=raw['cost'],
            metadata=replace(metadata_from_record(raw), deck_identity=cid), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
