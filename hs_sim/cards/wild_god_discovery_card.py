"""Malorne uses the full primary Wild God cycle and ordinary Imbue/cost facts."""
import json
from pathlib import Path

from hs_sim.engine.imbue import imbue_count
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, Rarity
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_888'
GODS = ('EDR_031','EDR_209','EDR_259','EDR_421','EDR_430','EDR_471',
        'EDR_480','EDR_489','EDR_527','EDR_819','EDR_895')
POOL_ID = 'constructed.cards'
BODY = 'cards.wild_god_discovery.malorne'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/wild-god-discovery-v1.json'
BATCH_HASH = '62539f1a4ad8801b3d89225c272915d7ee28f7f04ebd25a12b78a58d76988500'
QUERY = PoolQuery(kinds=(CardType.MINION,), collectible=True, class_mode='any',
    rarities=(Rarity.LEGENDARY,), card_ids=GODS)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['pool_inventory']) != GODS or
            data['dependencies'] or data['existing_dependencies'] or data['evidence_only'] or data['skipped']):
        raise TargetValidationError('Malorne requires its complete original face and eleven Wild Gods')
    inventory = data['pool_inventory']+data['related_non_candidates']
    for row in data['cards']+inventory:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Wild God inventory record')
    children = {row['record']['dbf_id'] for row in inventory}
    if (len(inventory) != 15 or len(children) != 15 or
            len(data['official_observations']) != 2 or
            any(set(x['face']['childIds']) != children for x in data['official_observations'])):
        raise TargetValidationError('Wild Gods differ from the complete bilingual primary related-card inventory')
    roots = [row['record'] for row in inventory if row['record']['type'] == 'MINION' and
        row['record']['collectible'] and row['record']['tags'].get('RARITY') == 5]
    if (tuple(sorted(x['id'] for x in roots)) != GODS or
            len({x['tags'].get('CLASS') for x in roots}) != 11):
        raise TargetValidationError('Malorne lost its original one-Wild-God-per-class cycle')
    return data


def register_wild_god_discovery_card(registry):
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION',8,8,6) or
            raw['tags'].get('BATTLECRY') != 1 or raw['tags'].get('ENTITY_TAG_THRESHOLD_VALUE') != 4):
        raise TargetValidationError('Malorne changed its complete original body or Imbue threshold')
    registry.register_behavior(BODY, lambda c: (DiscoverFromPool(c.player_id, POOL_ID, QUERY,
        source_id=c.source_id, cost=CostSpec(set_to=1) if imbue_count(c.state,c.player_id) >= 4 else None),))
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=8,attack=8,health=6,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
