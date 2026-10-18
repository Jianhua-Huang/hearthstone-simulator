"""Alara'shi transforms original hand minions with their local numeric material."""
import json
from pathlib import Path

from hs_sim.engine.costs import local_cost
from hs_sim.engine.model import CardDefinition, CardType, SummonStats
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.stats import enchantment_stats
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ALARASHI = 'EDR_493'
POOL_ID = 'constructed.cards'
DEMONS = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('demon',))
BODY = 'cards.native_retained_demon_transform.alarashi'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-retained-demon-transform-v1.json'
BATCH_HASH = 'e5d05d785993b23a5dca936af0c38802b3768d98dcc78a14dca757bcdeb86fe4'
POLICY = 'original-hand-local-numbers-demon-transformation-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['policy'] != POLICY or
            tuple(x['record']['id'] for x in data['cards']) != (ALARASHI,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Alarashi requires its complete original source and retention policy')
    row, = data['cards']
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Alarashi complete original source row changed')
    return data


def register_native_retained_demon_transform_cards(registry):
    raw = load_batch()['cards'][0]['record']
    metadata = metadata_from_record(raw)
    if ((raw['cost'], raw['attack'], raw['health'], raw['type'], raw['tags'].get('CLASS')) !=
            (5, 5, 5, 'MINION', 14) or metadata.tribes != ('beast', 'demon')):
        raise TargetValidationError('Alarashi requires its original Demon Hunter dual-tribe Legendary face')

    def alarashi(c):
        work = []
        for entity_id in c.state.players[c.player_id].hand:
            entity = c.state.entities[entity_id]
            if entity.kind != CardType.MINION:
                continue
            attack, health = enchantment_stats(entity)
            work.append(TransformStoredFromPool(CardReference.capture(entity), POOL_ID, DEMONS, c.source_id,
                retained_stats=SummonStats(max(0, attack), max(0, health)), retained_cost=local_cost(entity)[0]))
        return tuple(work)

    registry.register_behavior(BODY, alarashi)
    card = CardDefinition(ALARASHI, raw['name'], CardType.MINION, cost=5, attack=5, health=5,
        metadata=metadata, battlecry=BODY)
    registry.register_card(card)
    if ALARASHI not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
