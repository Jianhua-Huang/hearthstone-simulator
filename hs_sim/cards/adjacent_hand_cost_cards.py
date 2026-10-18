"""Stickybomb Saboteur gives a native physical hand cost provider to the opponent."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand
from hs_sim.engine.model import CardDefinition, CardType, CostAuraSpec, CostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, SABOTAGE = 'CATA_186', 'CATA_186t'
PREFIX = 'cards.adjacent_hand_cost.'
AURA = CostAuraSpec(CostSpec(delta=1), hand_adjacent=True)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/adjacent-hand-cost-v1.json'
BATCH_HASH = 'f95f976c99df53d894023e9c905712f2f365ad5134c6836d00d0b5c0b24f6ec9'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (SABOTAGE,)):
        raise TargetValidationError('Unreviewed complete Stickybomb Saboteur source')
    for row in data['cards'] + data['dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Sabotage source')
    return data


def register_adjacent_hand_cost_cards(registry):
    registry.register_behavior(PREFIX+'give', lambda c: (AddToHand(3-c.player_id, SABOTAGE, c.source_id),))
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; root = raw['id'] == CARD
        card = CardDefinition(raw['id'], raw['name'], CardType.MINION if root else CardType.SPELL,
            cost=raw['cost'], attack=raw['attack'] or 0, health=raw['health'] or 0,
            metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            battlecry=PREFIX+'give' if root else None, cost_auras=() if root else (AURA,))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
