"""Vault Breaker consumes the original semantic discovery delivery."""
import json
from pathlib import Path

from hs_sim.engine.discovery_delivery import COMPLETED, DiscountDiscoveredCard
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_483'
PREFIX = 'cards.native_discovery_delivery.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discovery-delivery-v1.json'
BATCH_HASH = '487ae20416cc5952d9205dde628770b2f65eb1f14e0443752c07524aa26f2677'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Vault Breaker lost its complete reviewed original source')
    return data


def register_native_discovery_delivery_cards(registry):
    raw = load_batch()['cards'][0]['record']
    def discount(context):
        if context.event.player_id != context.player_id:
            return ()
        return (DiscountDiscoveredCard(context.event, context.source_id),)
    registry.register_behavior(PREFIX + 'discount', discount)
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
        triggers=(TriggerSpec(COMPLETED, PREFIX + 'discount'),))
    registry.register_card(definition)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(definition))
