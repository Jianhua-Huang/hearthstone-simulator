"""Paltry Flutterwing delegates forced pre-entry dormancy to ordinary summons."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/pool-entry-dormancy-v1.json'
BATCH_HASH = '203a058e865fa67e8220ec250028ad15336fbbc12244fe51a47ed4afe4e9fb88'
FLUTTERWING = 'TIME_058'
PREFIX = 'cards.pool_entry_dormancy.'
POOL_ID = 'constructed.cards'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=2, max_cost=2)
ENTRY_POLICY = 'forced-plain-pre-entry-dormancy-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['entry_policy'] != ENTRY_POLICY or
            tuple(x['record']['id'] for x in data['cards']) != (FLUTTERWING,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Flutterwing requires its complete reviewed source and entry policy')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Flutterwing original source row is incomplete')
    return data


def register_pool_entry_dormancy_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
            raw['tags'].get('DEATHRATTLE')) != ('MINION', 1, 1, 1, 12, 1):
        raise TargetValidationError('Flutterwing requires its complete original neutral minion face')
    registry.register_behavior(PREFIX + 'summon', lambda c: (
        SummonFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id,
            cause=SummonCause.capture(c), position=deathrattle_position(c), entry_dormant_turns=2),))
    card = CardDefinition(FLUTTERWING, raw['name'], CardType.MINION, cost=1, attack=1, health=1,
        metadata=metadata_from_record(raw), deathrattle=PREFIX + 'summon')
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
