"""Six ordinary structural-pool consumers and their native card entries."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import Overload
from hs_sim.engine.model import CardAbilityCondition,CardDefinition,CardType,CostSpec,Keyword,RewindSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p33-v1.json'
BATCH_HASH='ae5b9f4aaaceab6c633a2eca85268fa7156262630d9a3df605ea77b7545bd60c'
STONE='Core_UNG_072';INVOCATION='CORE_GIL_836';MACHINE='TIME_035';CLASH='CATA_569';WIZARD='TIME_002';HOOK='CAP_105';CANNON='CAP_107t'
ROOTS=(STONE,INVOCATION,MACHINE,CLASH,WIZARD,HOOK);DEPENDENCIES=();EXISTING_DEPENDENCIES=(CANNON,);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p33.'
IDENTITIES={cid:('UNG_072'if cid==STONE else'GIL_836'if cid==INVOCATION else cid)for cid in ROOTS}
QUERIES={STONE:PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.TAUNT,),class_mode='current'),
 INVOCATION:PoolQuery(kinds=(CardType.MINION,),collectible=True,ability=CardAbilityCondition(ability='battlecry',present=True,basis='printed'),class_mode='current'),
 MACHINE:PoolQuery(collectible=True,keywords_all=(Keyword.REWIND,)),
 WIZARD:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',include_neutral=False),
 HOOK:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('pirate',),class_mode='current'),
 **{CLASH+'.'+str(n):PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=n,max_cost=n)for n in(3,2,1)}}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P33 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or tuple(x['record']['id']for x in data['existing_dependencies'])!=EXISTING_DEPENDENCIES or tuple(x['record']['id']for x in data['evidence_only'])!=('UNG_072','GIL_836')or data['skipped']):raise TargetValidationError('Unreviewed P33 recipe set')
    for row in data['cards']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P33 original row')
    for row in data['existing_dependencies']:
        if canonical_digest(row['definition'])!=row['definition_sha256']:raise TargetValidationError('Incomplete P33 existing dependency definition')
    return data

def register_simple_followup_p33_cards(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:raise TargetValidationError('P33 requires the unchanged complete Cannoneer dependency')
    def stone(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[STONE],source_id=c.source_id),)
    def invocation(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[INVOCATION],source_id=c.source_id,cost=CostSpec(delta=-1)),)
    def machine(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[MACHINE],source_id=c.source_id),)
    def clash(c):return tuple(SummonFromPool(c.player_id,POOL_ID,QUERIES[CLASH+'.'+str(n)],source_id=c.source_id,cause=SummonCause.capture(c))for n in(3,2,1))+(Overload(c.player_id,1),)
    def wizard(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[WIZARD],count=2,source_id=c.source_id),)
    def hook(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(CANNON),),SummonCause.capture(c))
        return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[HOOK],source_id=c.source_id),request,request)
    bodies=dict(zip(ROOTS,(stone,invocation,machine,clash,wizard,hook)))
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());school=raw['tags'].get('SPELL_SCHOOL');kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int or school is not None and school not in SCHOOLS:raise TargetValidationError('P33 requires complete reviewed faces')
        registry.register_behavior(PREFIX+cid,bodies[cid])
        if kind==CardType.MINION:
            if any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P33 minion stats must be explicit')
            kwargs.update(attack=raw['attack'],health=raw['health']);kwargs['deathrattle'if cid==MACHINE else'battlecry']=PREFIX+cid
            if cid in(STONE,MACHINE):kwargs['keywords']=(Keyword.TAUNT,)
            if cid==WIZARD:kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        elif kind==CardType.SPELL:kwargs['on_play']=PREFIX+cid
        else:raise TargetValidationError('Unreviewed P33 card type')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],spell_school=SCHOOLS.get(school),metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
