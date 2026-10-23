"""Rangari Scout uses qualified genuine-discovery copy material."""
import json
from pathlib import Path

from hs_sim.engine.discovered_card_copies import request
from hs_sim.engine.discovery_delivery import COMPLETED
from hs_sim.engine.discovery_trigger_sources import DiscoveryTriggerProfile
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

SCOUT = 'GDB_841'
LEAVES = DEPENDENCIES = (SCOUT,)
COLLECTIBLE_ROOTS = ()
BEHAVIOR = 'cards.past_discovery_copy.'+SCOUT
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-discovery-copy-v1.json'
BATCH_HASH = 'd491a832e96a0295fa4c80ac36080b0a7e3ac9b084f2fe3fb35a25dca31aeec9'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(r['record']['id'] for r in data['dependencies']) != LEAVES or
            any(data[k] for k in ('cards','existing_dependencies','evidence_only','choice_only','skipped',
                                 'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in data['dependencies'])):
        raise TargetValidationError('Rangari Scout lost its complete original record')
    return data


def register_past_discovery_copy_card(registry):
    raw = load_batch()['dependencies'][0]['record']
    if (raw['id'], raw['type'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('CARDRACE'), raw['tags'].get('TRIGGER_VISUAL'), raw['tags'].get('CLASS')) != (
            SCOUT, 'MINION', 1, 1, 2, 2, 1, 3):
        raise TargetValidationError('Rangari Scout lost its native Hunter Draenei trigger face')
    registry.register_behavior(BEHAVIOR, lambda c: request(c, registry))
    card = CardDefinition(SCOUT, raw['name'], CardType.MINION, cost=1, attack=1, health=2,
        metadata=metadata_from_record(raw), triggers=(TriggerSpec(COMPLETED, BEHAVIOR),))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_discovery_trigger_profile(DiscoveryTriggerProfile(SCOUT, BEHAVIOR))
