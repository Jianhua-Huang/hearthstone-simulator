"""Legendary Vendor keeps its original unselected discovery recipes."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Rarity
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_514'
BODY = 'cards.legendary_vendor.discover_and_shuffle_remainder'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discovery-remainders-v1.json'
BATCH_HASH = 'dce775f9f3781c53ab425a772a790e34533fdd578c4c0c4b4ecdc3a78170c0f3'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', rarities=(Rarity.LEGENDARY,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Legendary Vendor requires its complete reviewed source')
    return data


def register_native_discovery_remainder_cards(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (DiscoverFromPool(c.player_id, 'constructed.cards', QUERY,
        source_id=c.source_id, shuffle_unselected_into_deck=True),))
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
