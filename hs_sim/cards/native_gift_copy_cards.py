"""Shadowflame Stalker gets one copy of the original selected enriched recipe."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-gift-copy-v1.json'
BATCH_HASH = '4b5072b047f394fc3909dc6903ec1cfe55ca19fa10afa4de0c4431f10e5a4b9f'
STALKER = 'FIR_924'
POOL_ID = 'constructed.cards'
PREFIX = 'cards.native_gift_copy.'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('demon',), class_mode='current')
COPY_POLICY = 'selected-gift-creation-material-before-acquisition-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (STALKER,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            data['copy_policy'] != COPY_POLICY or data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            tuple(x['record']['id'] for x in data['existing_gift_sources']) != tuple(g.id for g in DARK_GIFTS)):
        raise TargetValidationError('Unreviewed Stalker, selected-copy policy or full gift inventory')
    for row in data['cards'] + data['existing_gift_sources']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Stalker requires complete original source rows')
    return data


def register_native_gift_copy_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
            raw['tags'].get('BATTLECRY')) != ('MINION', 4, 4, 3, 9, 1):
        raise TargetValidationError('Stalker requires its complete original Warlock minion face')
    registry.register_behavior(PREFIX + 'discover', lambda c: (
        DiscoverDarkGift(c.player_id, POOL_ID, QUERY, c.source_id, gift_copy_to_hand=True),))
    card = CardDefinition(STALKER, raw['name'], CardType.MINION, cost=4, attack=4, health=3,
        metadata=metadata_from_record(raw), battlecry=PREFIX + 'discover')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
