"""King of the Underbelly delegates construction and Discover to sideboards."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sideboards import ContrabandSideboardProfile, DiscoverSideboard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = 'JAIL_831'
BODY = 'cards.contraband_sideboard.discover'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/contraband-sideboard-v1.json'
BATCH_HASH = 'd6d1755a739acc9bf564cffdb33afff6c6b13b254f2d78f2d634622a33c6003c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (ROOT,) or
            any(data[key] for key in ('dependencies', 'existing_dependencies', 'evidence_only')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Contraband requires its complete original King source')
    return data


def register_contraband_sideboard_card(registry):
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 6, 6, 5) or
            any(raw['tags'].get(key) != value for key, value in {
                'BATTLECRY': 1, 'DISCOVER': 1, 'CARDRACE': 20, 'MAX_SIDEBOARD_CARDS': 3,
                'SIDEBOARD_TYPE': 4, 'ALLOWED_SIDEBOARD_SUBSET': 19499,
                'SIDEBOARD_IGNORES_CLASS_RULE': 1}.items())):
        raise TargetValidationError('Contraband source changed its original face or subset declaration')
    registry.register_behavior(BODY, lambda c: (DiscoverSideboard(c.player_id, ROOT, c.source_id),))
    card = CardDefinition(ROOT, raw['name'], CardType.MINION, cost=6, attack=6, health=5,
        battlecry=BODY, metadata=replace(metadata_from_record(raw), deck_identity=ROOT))
    registry.register_card(card)
    registry.register_sideboard(ContrabandSideboardProfile(ROOT))
    if ROOT not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
