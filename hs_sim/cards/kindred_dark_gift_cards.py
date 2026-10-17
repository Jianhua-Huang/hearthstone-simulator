"""Raptor Herald prepares one paired discovery with the accepted Kindred price."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, KindredProfile, Keyword, RewindSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/kindred-dark-gift-v1.json'
BATCH_HASH = '2649c42afe8355c96cf447faf652fa14bb2004de0dd578fa7c04619b25557776'
RAPTOR = 'CORE_EDR_004_2026'
IDENTITY = 'CORE_EDR_004'
POOL_ID = 'constructed.cards'
PREFIX = 'cards.kindred_dark_gift.'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('beast',), class_mode='current')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (RAPTOR,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != (IDENTITY,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(g) for g in DARK_GIFTS]) or
            tuple(x['record']['id'] for x in data['existing_gift_sources']) != tuple(g.id for g in DARK_GIFTS)):
        raise TargetValidationError('Unreviewed Raptor or existing Dark Gift inventory')
    for row in data['cards'] + data['evidence_only'] + data['existing_gift_sources']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete Raptor or existing gift source')
    return data


def register_kindred_dark_gift_cards(registry):
    def prepare(c):
        if c.kindred is None or c.kindred.card_id != RAPTOR:
            raise ValueError('Raptor requires its actual accepted native Kindred preparation')
        cost = CostSpec(delta=-c.kindred.repetitions, card_types=(CardType.MINION,)) if c.kindred.condition.matched else None
        return (DiscoverDarkGift(c.player_id, POOL_ID, QUERY, c.source_id, cost=cost),)

    data = load_batch()
    raw = data['cards'][0]['record']
    legacy = data['evidence_only'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS')) != ('MINION', 3, 4, 2, 12) or
            (raw['tags'].get('REWIND'), raw['tags'].get('KINDRED'), raw['tags'].get('BATTLECRY')) != (1, 1, 1) or
            raw['tags'].get('858') != legacy['dbf_id'] or raw['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID') != legacy['dbf_id']):
        raise TargetValidationError('Raptor requires its complete current face and explicit edition identity')
    registry.register_behavior(PREFIX + 'wrapper', lambda c: ())
    registry.register_behavior(PREFIX + 'prepare', prepare)
    card = CardDefinition(RAPTOR, raw['name'], CardType.MINION, cost=3, attack=4, health=2,
        metadata=replace(metadata_from_record(raw), deck_identity=IDENTITY), keywords=(Keyword.REWIND,),
        rewind=RewindSpec(), battlecry=PREFIX + 'wrapper')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(RAPTOR, 'body', wrapper=PREFIX + 'wrapper', prepare=PREFIX + 'prepare'))
