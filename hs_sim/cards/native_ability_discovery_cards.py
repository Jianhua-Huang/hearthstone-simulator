"""Native printed ability discoveries use independent complete pool facts."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-ability-discovery-v1.json'
BATCH_HASH = 'ce9676fffedc1447fa38e5de02531535be9fba1199d740c9bc939bd4af6eb0bf'
GARDENING = 'EDR_488'
SYMBIOSIS = 'EDR_273'
ROOTS = (GARDENING, SYMBIOSIS)
POOL_ID = 'constructed.cards'
PREFIX = 'cards.native_ability_discovery.'
QUERIES = {
    GARDENING: PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', deathrattle=True),
    SYMBIOSIS: PoolQuery(collectible=True, class_mode='other', include_neutral=False, choose_one=True),
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != ROOTS or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            tuple(x['record']['id'] for x in data['existing_gift_sources']) != tuple(g.id for g in DARK_GIFTS)):
        raise TargetValidationError('Unreviewed printed-ability discovery sources or existing gift inventory')
    for row in data['cards'] + data['existing_gift_sources']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Printed-ability discovery requires complete source rows')
    return data


def register_native_ability_discovery_cards(registry):
    for row in load_batch()['cards']:
        raw = row['record']
        cid = raw['id']
        expected = (2, 9, None) if cid == GARDENING else (1, 2, 4)
        if (raw['type'] != 'SPELL' or (raw['cost'], raw['tags'].get('CLASS'),
                raw['tags'].get('SPELL_SCHOOL')) != expected):
            raise TargetValidationError('Printed-ability discovery requires its complete original spell face')
        if cid == GARDENING:
            behavior = lambda c: (DiscoverDarkGift(c.player_id, POOL_ID, QUERIES[GARDENING], c.source_id),)
        else:
            behavior = lambda c: (DiscoverFromPool(c.player_id, POOL_ID, QUERIES[SYMBIOSIS], source_id=c.source_id),)
        registry.register_behavior(PREFIX + cid, behavior)
        card = CardDefinition(cid, raw['name'], CardType.SPELL, cost=raw['cost'], metadata=metadata_from_record(raw),
            spell_school=SpellSchool.NATURE if cid == SYMBIOSIS else None, on_play=PREFIX + cid)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
