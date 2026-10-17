"""Native Legendary/one-cost discoveries reuse the complete Dark Gift pipeline."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType, Rarity
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-dark-gift-generation-v1.json'
BATCH_HASH = '215bd10d60197b37c765c39a24213e526a0714db65ab06390bba55665944cbbb'
TORMENTOR = 'EDR_102'
ENDMAW = 'END_013'
ROOTS = (TORMENTOR, ENDMAW)
POOL_ID = 'constructed.cards'
PREFIX = 'cards.native_dark_gift_generation.'
QUERIES = {
    TORMENTOR: PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current',
                         rarities=(Rarity.LEGENDARY,)),
    ENDMAW: PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current',
                      min_cost=1, max_cost=1),
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            tuple(x['record']['id'] for x in data['existing_gift_sources']) != tuple(g.id for g in DARK_GIFTS)):
        raise TargetValidationError('Unreviewed native Dark Gift generation source or gift inventory')
    for row in data['cards'] + data['existing_gift_sources']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete native Dark Gift generation source row')
    return data


def register_native_dark_gift_generation_cards(registry):
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        if (raw['type'], raw['cost'], raw['attack'], raw['health']) != (
                ('MINION', 4, 5, 4) if cid == TORMENTOR else ('MINION', 3, 3, 3)):
            raise TargetValidationError('Native Dark Gift source requires its complete minion face')
        registry.register_behavior(PREFIX + cid, lambda c, q=QUERIES[cid]: (
            DiscoverDarkGift(c.player_id, POOL_ID, q, c.source_id),))
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
            attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw),
            battlecry=PREFIX + cid)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
