"""A real discovered Legendary is summoned, then its original stats are set."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Rarity, SummonStats
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'DINO_424'
BODY = 'cards.heros_welcome.discover_summon_set_stats'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discovered-set-stats-v1.json'
BATCH_HASH = '1ccf9822fe4a3efd9355f435abded1dbd52a8277a93dd2ed5c3a6af8732bd4c5'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', rarities=(Rarity.LEGENDARY,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Hero\'s Welcome requires its complete reviewed source pin')
    return data


def register_native_discovered_set_stats_cards(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (DiscoverFromPool(c.player_id, 'constructed.cards', QUERY,
        source_id=c.source_id, destination='board', cause=SummonCause.capture(c),
        set_summoned_stats=SummonStats(10, 10)),))
    definition = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=BODY, metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
