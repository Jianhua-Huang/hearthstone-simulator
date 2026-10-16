"""Two actual minion pool recipes use the existing Temporary hand executor."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/temporary-pool-minion-v1.json'
BATCH_HASH='1c613af873d063376fd9971745acfa8c4153dcdf1f79926ff8947cc524632542'
BIOME='TLC_449';TERROR='TLC_469';ROOTS=(BIOME,TERROR)
POOL_ID='constructed.cards';PREFIX='cards.temporary_pool_minion.'
QUERIES={BIOME:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1,class_mode='current'),
         TERROR:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or
            any(data[key]for key in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Unreviewed complete Temporary pool source')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete Temporary pool raw row')
    return data

def register_temporary_pool_minion_cards(registry):
    registry.register_behavior(PREFIX+'biome',lambda c:(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[BIOME],
        source_id=c.source_id,temporary_until_turn=c.state.turn),))
    registry.register_behavior(PREFIX+'terror',lambda c:(GenerateFromPool(c.player_id,POOL_ID,QUERIES[TERROR],
        count=2,source_id=c.source_id,temporary_until_turn=c.state.turn),))
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if cid==BIOME:
            if(raw['type'],raw['cost'],raw['health'])!=('LOCATION',1,2):raise TargetValidationError('Biome requires its actual Location face')
            kwargs=dict(durability=2,on_use=PREFIX+'biome')
        else:
            if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',3,4,3):raise TargetValidationError('Terror requires its actual minion face')
            kwargs=dict(attack=4,health=3,deathrattle=PREFIX+'terror')
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
