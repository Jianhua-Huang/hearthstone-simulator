"""Actual original Neutral deck cards into the full Druid card pool."""
import json
from pathlib import Path

from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.jade import printed_definition
from hs_sim.engine.model import CardClass, CardDefinition, CardType
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.stored_pool_transforms import TransformStoredFromPool
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-deck-pool-transform-v1.json'
BATCH_HASH = '0b016aea832240e6e3023651499ec94863b04fa08f34458ffda9a9e05b2548ad'
ENVOY = 'EDR_873'
POOL_ID = 'constructed.cards'
BODY = 'cards.native_deck_pool_transform.envoy'
DRUID = PoolQuery(collectible=True, class_mode='specified', classes=(CardClass.DRUID,), include_neutral=False)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (ENVOY,):
        raise TargetValidationError('Envoy complete original source and policies changed')
    row, = data['cards']
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Envoy complete original row changed')
    return data


def register_native_deck_pool_transform_cards(registry):
    data = load_batch(); row, = data['cards']; raw = row['record']
    if (raw['cost'], raw['attack'], raw['health'], raw['type'], raw['collectible']) != (4, 3, 6, 'MINION', True):
        raise TargetValidationError('Envoy original physical face changed')

    def envoy(c):
        refs = []
        for entity_id in c.state.players[c.player_id].deck:
            entity = c.state.entities[entity_id]
            definition = printed_definition(registry, entity)
            classes = definition.metadata.classes if definition.metadata is not None else None
            if classes is None:
                raise ResolutionError('Envoy requires complete original deck class metadata')
            if classes == (CardClass.NEUTRAL,):
                refs.append(CardReference.capture(entity))
        return tuple(TransformStoredFromPool(ref, POOL_ID, DRUID, c.source_id) for ref in refs)

    registry.register_behavior(BODY, envoy)
    card = CardDefinition(ENVOY, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], metadata=metadata_from_record(raw), battlecry=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
