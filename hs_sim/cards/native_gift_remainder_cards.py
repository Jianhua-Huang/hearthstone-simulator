"""Actual Jumpscare uses the existing paired-gift and semantic shuffle pipes."""
import json
from pathlib import Path
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='EDR_882'
BODY='cards.native_gift_remainders.jumpscare'
QUERY=PoolQuery(kinds=(CardType.MINION,),min_cost=5,collectible=True,
    class_mode='current',tribes_any=('demon',))
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-gift-remainders-v1.json'
BATCH_HASH='308c6d66797ce949d2230bd7a53b864b98857a472983e9bc099419a2ba2db74f'

def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or len(d['cards'])!=1 or
            d['cards'][0]['record']['id']!=CARD or
            canonical_digest(d['cards'][0]['record'])!=d['cards'][0]['record_sha256']):
        raise TargetValidationError('Jumpscare requires its complete reviewed original source')
    return d

def register_native_gift_remainder_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,None,None,None):
        raise TargetValidationError('Jumpscare printed face changed')
    registry.register_behavior(BODY,lambda c:(DiscoverDarkGift(c.player_id,'constructed.cards',QUERY,
        c.source_id,shuffle_unselected_into_deck=True),))
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=2,on_play=BODY,
        metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
