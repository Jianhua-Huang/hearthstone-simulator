"""Odd Map queries printed Beast attack and uses the original physical offer."""
import json
from pathlib import Path

from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD,BODY,POOL='TLC_824','cards.odd_map.body','constructed.cards'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-odd-map-v1.json'
BATCH_HASH='68866a3192409b0be1b21de8d6ce687f52d2cf8c11fc72181d58451a591ddc19'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or len(data['cards'])!=1 or
            data['cards'][0]['record']['id']!=CARD or
            canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']):
        raise TargetValidationError('Odd Map lost its complete printed source')
    return data


def register_native_odd_map_cards(registry):
    data=load_batch()
    registry.register_behavior(BODY,lambda c:(DiscoverForPlayFollowup(DiscoverFromPool(c.player_id,POOL,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',tribes_any=('beast',),
                  attack_parity='odd'),source_id=c.source_id)),))
    raw=data['cards'][0]['record']
    if raw['type']!='SPELL' or 'SPELL_SCHOOL'in raw['tags']:
        raise TargetValidationError('Odd Map requires its original spell identity')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
