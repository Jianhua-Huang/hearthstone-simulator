"""Simple class, printed-cost and weapon consumers of an explicit format pool."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardClass,CardDefinition,CardType
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p27-v1.json'
BATCH_HASH='7959e6d2c5202e457909f05c509c1e02af0786ad03e8c8424bc6002e2ff7e67a'
BOOK='CORE_EDR_001';PIRATE='CORE_KAR_069';NURSE='DINO_434';CAKE='JAIL_460'
ROOTS=(BOOK,PIRATE,NURSE,CAKE);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p27.'
IDENTITIES={BOOK:BOOK,PIRATE:'KAR_069',NURSE:NURSE,CAKE:CAKE}
QUERIES={BOOK+'.bc':PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False),
 PIRATE+'.bc':PoolQuery(collectible=True,class_mode='other',include_neutral=False),
 NURSE+'.bc':PoolQuery(kinds=(CardType.MINION,),min_cost=1,max_cost=1,collectible=True),
 NURSE+'.dr':PoolQuery(kinds=(CardType.SPELL,),min_cost=1,max_cost=1,collectible=True),
 CAKE+'.dr':PoolQuery(kinds=(CardType.WEAPON,),collectible=True)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P27 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('EDR_001','KAR_069')or data['skipped']):raise TargetValidationError('Unreviewed P27 recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P27 original row')
    return data

def register_simple_followup_p27_cards(registry):
    data=load_batch()
    for key,query in QUERIES.items():
        registry.register_behavior(PREFIX+key,lambda c,q=query,n=2 if key==BOOK+'.bc'else 1:(GenerateFromPool(c.player_id,POOL_ID,q,count=n,source_id=c.source_id,replacement=True),))
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION'or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):raise TargetValidationError('P27 requires complete reviewed minion faces')
        kwargs={name:PREFIX+cid+suffix for name,suffix in(('battlecry','.bc'),('deathrattle','.dr'))if cid+suffix in QUERIES}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
