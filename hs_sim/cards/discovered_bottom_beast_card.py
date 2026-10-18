"""Kaldorei Cultivator uses original discoveries and ordinary boosted deck creation."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_730'
POOL_ID = 'constructed.cards'
BODY = 'cards.discovered_bottom_beast.discover'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='current', tribes_any=('beast',))
GRANT = CreatedMinionGrant(attack=5, health=5)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/discovered-bottom-beast-card-v1.json'
BATCH_HASH = '4559fe30bb2be8d44db532fa0d9f7af8d19b7a1a66c0ca8e79feb0ab86b60071'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD]
            or [x['record']['id'] for x in data['evidence_only']] != ['TIME_730e']
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Kaldorei Cultivator lost its complete reviewed source')
    return data


def register_discovered_bottom_beast_card(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 2, 2, 3, 1):
        raise TargetValidationError('Kaldorei Cultivator lost its original Battlecry face')
    registry.register_behavior(BODY, lambda c: (DiscoverFromPool(c.player_id, POOL_ID, QUERY,
        source_id=c.source_id, discoveries=2, destination='deck', position='bottom', minion_grant=GRANT),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
