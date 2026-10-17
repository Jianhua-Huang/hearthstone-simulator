"""Actual Conflux faces compose native generation, discoveries and locations."""
import json
from pathlib import Path

from hs_sim.engine.locations import AdvanceLocationFace, LocationFaceReference
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

FACES = ('TIME_436', 'TIME_436t1', 'TIME_436t2')
BODY = 'cards.conflux_location.body'
QUERY = PoolQuery(kinds=(CardType.MINION,), min_cost=5, collectible=True, tribes_any=('dragon',))
DISCOVER_QUERY = PoolQuery(kinds=(CardType.MINION,), min_cost=5, collectible=True,
                          tribes_any=('dragon',), class_mode='current')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-timeway-locations-v1.json'
BATCH_HASH = '536724e366d798ec21b050bd0c359c1c1c9191e1d8c6791025c2e8af9499a06c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != FACES or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Conflux requires all three complete reviewed location faces')
    return data


def register_native_timeway_location_cards(registry):
    def body(c):
        ref = LocationFaceReference.capture(c.state, c.source_id)
        if ref.card_id not in FACES:
            raise ValueError('Conflux requires its original actual location face')
        cause = SummonCause.capture(c)
        index = FACES.index(ref.card_id)
        request = (GenerateFromPool(c.player_id, 'constructed.cards', QUERY,
            source_id=c.source_id, destination='board', cause=cause) if index == 0 else
            DiscoverFromPool(c.player_id, 'constructed.cards', DISCOVER_QUERY,
                source_id=c.source_id, destination='board', cause=cause,
                copy_selected_to_hand=index == 2))
        advance = () if index == 2 else (AdvanceLocationFace(ref, FACES[index+1], c.source_id),)
        return (request, *advance)

    registry.register_behavior(BODY, body)
    for row in load_batch()['cards']:
        raw = row['record']
        definition = CardDefinition(raw['id'], raw['name'], CardType.LOCATION, cost=raw['cost'],
            durability=raw['health'], on_use=BODY, metadata=metadata_from_record(raw))
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
