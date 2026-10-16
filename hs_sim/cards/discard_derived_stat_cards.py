"""Duke of Below derives both stats from existing committed discard facts."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import (CardDefinition, CardType, Keyword, StatReference,
    StatRelationLayer, StatRelationOperand, StatRelationSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/discard-derived-stats-v1.json'
BATCH_HASH = '98a3acf6a355f6006dcd587df0ee79db60af80f0ffec02eee20d60b72c5dfc01'
DUKE = 'CATA_493'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Discard derived stats source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != (DUKE,) or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed discard derived stat family')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Discard derived stat full source record changed')
    return data


def register_discard_derived_stat_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'MINION' or not raw['collectible'] or raw['tags'].get('RUSH') != 1:
        raise TargetValidationError('Duke requires its actual native Rush minion face')
    card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], keywords=(Keyword.RUSH,),
        stat_relations=(StatRelationSpec(operand=StatRelationOperand.CONTROLLER_DISCARD_COUNT,
            layer=StatRelationLayer.CONDITIONAL_ATTACK, amount=2),
            StatRelationSpec(target=StatReference.HEALTH, operand=StatRelationOperand.CONTROLLER_DISCARD_COUNT,
                layer=StatRelationLayer.CONDITIONAL_HEALTH, amount=2)),
        metadata=replace(metadata_from_record(raw), deck_identity=raw['id']))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
