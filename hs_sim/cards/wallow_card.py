"""Wallow listens only while physically in its controller's hand or deck."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dark_gift_echo import CopyReceivedDarkGift, original_gift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_487'
PREFIX = 'cards.wallow.'
PROGRESS = HandProgressSpec('event', 1, on_complete=PREFIX + 'copy', repeat=True,
    event='dark_gift_granted', condition_id=PREFIX + 'own', zone=(Zone.HAND, Zone.DECK))
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/wallow-v1.json'
BATCH_HASH = 'c9e2a54e5b1ff43c90eccd2f7b9542c1fb6cef54b12eef79b0f0fb51f186b1b8'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'evidence_only', 'skipped')) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != tuple(g.id for g in DARK_GIFTS) or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS])):
        raise TargetValidationError('Wallow requires its complete original face and all ten real gifts')
    for row in (*data['cards'], *data['existing_dependencies']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Wallow or a complete gift source changed')
    return data


def register_wallow_card(registry):
    def own(c):
        if c.event is None or c.event.player_id != c.player_id:
            return False
        original_gift(c.state, c.event)
        return True
    def copy(c):
        if c.trigger is None or c.trigger.hand_progress != PROGRESS:
            raise ValueError('Wallow requires its actual native hand/deck listener')
        return (CopyReceivedDarkGift(CardReference.capture(c.source), c.event),)
    registry.register_trigger_condition(PREFIX + 'own', own)
    registry.register_behavior(PREFIX + 'copy', copy)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CLASS']) != ('MINION', 7, 6, 6, 9):
        raise TargetValidationError('Wallow lost its original seven-mana Warlock face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=6, health=6,
        hand_progress=PROGRESS, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
