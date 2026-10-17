"""Smoke Bomb uses one explicitly provisional union-based gift discovery."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardAbilityCondition, CardDefinition, CardType, Keyword, SpellSchool
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-smoke-discovery-v1.json'
BATCH_HASH = '35c2622b297a504b642d1b5bd0c7b0f0c40097e071e220246881fe0a6cfae634'
SMOKE = 'FIR_920'
PREFIX = 'cards.native_smoke_discovery.'
POOL_ID = 'constructed.cards'
OFFER_POLICY = 'experimental-uniform-eligibility-union-v1'
CLAUSES = (
    PoolQuery(keywords_all=(Keyword.COMBO,)),
    PoolQuery(ability=CardAbilityCondition(basis='printed')),
    PoolQuery(keywords_all=(Keyword.STEALTH,)),
)
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', any_of=CLAUSES)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (SMOKE,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            data['offer_policy'] != OFFER_POLICY or data['cn_calibrated'] is not False or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            tuple(x['record']['id'] for x in data['existing_gift_sources']) != tuple(g.id for g in DARK_GIFTS)):
        raise TargetValidationError('Unreviewed Smoke Bomb source, explicit preview policy or full gift inventory')
    for row in data['cards'] + data['existing_gift_sources']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Smoke Bomb requires complete original source rows')
    return data


def register_native_smoke_discovery_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL')) != ('SPELL', 2, 7, 2):
        raise TargetValidationError('Smoke Bomb requires its original Rogue Fire spell face')
    registry.register_behavior(PREFIX + 'discover', lambda c: (
        DiscoverDarkGift(c.player_id, POOL_ID, QUERY, c.source_id),))
    card = CardDefinition(SMOKE, raw['name'], CardType.SPELL, cost=2, spell_school=SpellSchool.FIRE,
        metadata=metadata_from_record(raw), on_play=PREFIX + 'discover')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
