"""Hounds of Fury uses fixed original deliveries and ordinary forced combat."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_attack_groups import AttackSummonedGroup, SummonAttackProfile
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_443'
TOKENS = ('TIME_443t', 'TIME_443t2')
PREFIX = 'cards.lowest_health_demons.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/lowest-health-demons-v1.json'
BATCH_HASH = '9b2f187b9a33a66ae74c56aef516213de061e15538e9223b1ddca31dd9a4fed8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != TOKENS):
        raise TargetValidationError('Unreviewed complete Hounds of Fury source')
    for row in data['cards'] + data['dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Hounds of Fury face')
    return data


def register_lowest_health_demons_card(registry):
    def hounds(c):
        cause = SummonCause.capture(c)
        return (*(SummonByCard(c.player_id, (SummonEntryMaterial(cid),), cause) for cid in TOKENS),
            AttackSummonedGroup(c))
    registry.register_behavior(PREFIX+'hounds', hounds)
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; root = raw['id'] == CARD
        if not root and (raw['attack'], raw['health'], raw['text'], raw['tags']['CARDRACE']) != (3, 2, '', 15):
            raise TargetValidationError('Unreviewed original Felhound native material')
        card = CardDefinition(raw['id'], raw['name'], CardType.SPELL if root else CardType.MINION,
            cost=raw['cost'], attack=raw.get('attack') or 0, health=raw.get('health') or 0,
            metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            on_play=PREFIX+'hounds' if root else None)
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_summon_attack_profile(SummonAttackProfile(CARD, TOKENS[0], 2,
        request_card_ids=TOKENS, target_policy='lowest_health_enemy_if_no_deck_minions'))
