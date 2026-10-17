"""Actual old Quest reward reachable from Standard, using existing hero stats."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-amara-reward-v1.json'
BATCH_HASH = 'a51e4c9efc15f5b35a2bf05d1edb2e2b8fce8f2f5f57486de2e89f22320cb997'
REWARD, EXISTING, BODY = 'UNG_940t8', 'TLC_835', 'cards.public_consumers.amara'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (REWARD,)):
        raise TargetValidationError('Native Amara reward lost its complete source pin')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native Amara complete source row changed')
    return data


def register_native_amara_reward_cards(registry):
    data = load_batch()
    existing = registry.card(EXISTING)
    if (canonical_digest(asdict(existing)) != data['existing_dependency_definition_pins'][EXISTING]
            or existing.on_play != BODY or data['reuse_behavior_id'] != BODY):
        raise TargetValidationError('Native Amara requires the exact existing full Story of Amara')
    registry.behavior(BODY)
    raw = data['cards'][0]['record']
    card = CardDefinition(REWARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.TAUNT,),
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
