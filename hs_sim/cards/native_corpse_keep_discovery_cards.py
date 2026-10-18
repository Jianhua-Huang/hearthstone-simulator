"""Paleomancy pays once to retain its original unselected Undead menu cards."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PALEOMANCY = 'TLC_434'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('undead',))
PREFIX = 'cards.native_corpse_keep_discovery.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-corpse-keep-discovery-v1.json'
BATCH_HASH = 'bdfca7a88a0d0fd889ee63ff62de6a1eca0f9df0c3f71675ffb138d7182f96d4'
POLICY = 'original-actual-pick-corpse-keep-remainder-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['policy'] != POLICY or
            tuple(x['record']['id'] for x in data['cards']) != (PALEOMANCY,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Paleomancy requires its complete original source and timing declaration')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Paleomancy original source row is incomplete')
    return data


def register_native_corpse_keep_discovery_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['tags'].get('CLASS'), raw['tags'].get('SPELL_SCHOOL'),
            raw['tags'].get('COST_UNHOLY'), raw['tags'].get('CORPSE_SPENDER')) != ('SPELL', 3, 1, 6, 1, 1):
        raise TargetValidationError('Paleomancy requires its printed Shadow spell and Unholy rune')
    registry.register_behavior(PREFIX + 'discover', lambda c: (
        DiscoverFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id, keep_all_corpse_cost=5),))
    card = CardDefinition(PALEOMANCY, raw['name'], CardType.SPELL, cost=3,
        spell_school=SpellSchool.SHADOW, metadata=metadata_from_record(raw), on_play=PREFIX + 'discover')
    registry.register_card(card)
    if PALEOMANCY not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
