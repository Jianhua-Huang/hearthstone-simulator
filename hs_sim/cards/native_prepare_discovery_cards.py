"""Wanted Poster grants the original discovered physical minion Prepare."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

WANTED_POSTER = 'CAP_407'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), min_cost=5, collectible=True, class_mode='current')
GRANT = CreatedMinionGrant(special='prepare')
PREFIX = 'cards.native_prepare_discovery.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-prepare-discovery-v1.json'
BATCH_HASH = 'dbbeb5391fe40a5e38709a98e2b9ae90e4eab3c52afea5c22cf3527f1e727f3d'
POLICY = 'selected-created-minion-prepare-grant-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['policy'] != POLICY or
            tuple(x['record']['id'] for x in data['cards']) != (WANTED_POSTER,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Wanted Poster requires its complete original source and grant declaration')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Wanted Poster original source row is incomplete')
    return data


def register_native_prepare_discovery_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('RARITY')) != ('SPELL', 2, 12, 4):
        raise TargetValidationError('Wanted Poster requires its printed neutral two-mana Epic spell')
    registry.register_behavior(PREFIX + 'discover', lambda c: (
        DiscoverFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id, minion_grant=GRANT),))
    definition = CardDefinition(WANTED_POSTER, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata_from_record(raw), on_play=PREFIX + 'discover')
    registry.register_card(definition)
    if WANTED_POSTER not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(definition))
