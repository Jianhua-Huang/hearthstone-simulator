"""Uldir locks only its own in-play entry, then uses ordinary location rules."""
import json
from pathlib import Path

from hs_sim.engine.location_rune_locks import RULE, register_rule
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_780'
BODY = 'cards.uldir_quarantine.use'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/uldir-quarantine-v1.json'
BATCH_HASH = 'fa8b97f334a14cdc9deb9ae76ec6d7ca2eebaee08bc3100b5ad14ffd3b63b601'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256'] or
            data['official_faces_verified'] != 2):
        raise TargetValidationError('Uldir requires its complete original source and two full primary faces')
    return data


def register_uldir_quarantine_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['health'], raw['tags'].get('ULDIR_QUARANTINE_TRACKER'),
            raw['tags'].get('COST_BLOOD'), raw['tags'].get('COST_FROST'), raw['tags'].get('COST_UNHOLY'),
            raw['tags'].get('LOCATION_ACTION_COOLDOWN')) != ('LOCATION', 3, 3, 1, 1, 1, 1, 2):
        raise TargetValidationError('Uldir lost its actual three-durability triple-Rune locked location')
    register_rule(registry)
    registry.register_behavior(BODY, lambda c: (SummonFromPool(c.player_id, 'constructed.cards',
        PoolQuery(kinds=(CardType.MINION,), min_cost=5, max_cost=5, collectible=True),
        source_id=c.source_id, cause=SummonCause.capture(c)),))
    card = CardDefinition(CARD, raw['name'], CardType.LOCATION, cost=3, durability=3,
        metadata=metadata_from_record(raw), on_use=BODY, use_rule=RULE, requires_board_space=True)
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
