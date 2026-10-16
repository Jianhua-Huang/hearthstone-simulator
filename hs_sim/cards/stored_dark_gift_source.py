"""Nightmare Lord Xavius uses original deck cards, not generated copies."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.stored_gift_discovery import DiscoverDeckDarkGift
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/stored-dark-gift-source-v1.json'
BATCH_HASH = '05c2d6138bea93d97b70e6ab7f2460e69d1d5fc2dd2c7d2d3c167a676c7c42b2'
XAVIUS = 'EDR_856'
BEHAVIOR = 'cards.stored_dark_gift.xavius'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Stored Dark Gift source lost its complete reviewed pin')
    return data


def register_stored_dark_gift_source(registry):
    data = load_batch(); row, = data['cards']; raw = row['record']
    if (raw['id'] != XAVIUS or raw['type'] != 'MINION' or raw['collectible'] is not True or data['dependencies'] or
            data['gift_version'] != DARK_GIFT_VERSION or data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            {x['record']['id'] for x in data['existing_gift_sources']} != {g.id for g in DARK_GIFTS}):
        raise TargetValidationError('Unreviewed stored gift source or existing gift inventory')
    for item in data['cards'] + data['existing_gift_sources'] + data['evidence_only']:
        if canonical_digest(item['record']) != item['record_sha256']:
            raise TargetValidationError('Stored gift full source row changed')
    registry.register_behavior(BEHAVIOR, lambda c: (DiscoverDeckDarkGift(c.player_id, c.source_id),))
    card = CardDefinition(XAVIUS, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
                          metadata=replace(metadata_from_record(raw), deck_identity=XAVIUS), battlecry=BEHAVIOR)
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
