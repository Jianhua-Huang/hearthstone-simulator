"""Native on-play Kindred/Deathrattle Get and healing before two fresh summons."""
import json
from pathlib import Path
from hs_sim.engine.effects import Heal,HealBatch
from hs_sim.engine.kindred import request as kindred_request
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,HealingKind,KindredProfile,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p40-v1.json'
BATCH_HASH='67ea830a586675526b1cd28fa44ad48598740327880676f78d6135a2f37124fe'
REX='END_015';BLOOM='MEND_042';ROOTS=(REX,BLOOM);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p40.'
QUERIES={REX:PoolQuery(kinds=(CardType.MINION,),collectible=True,deathrattle=True),BLOOM:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=8,max_cost=8)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P40 complete reviewed recipe set changed')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P40 original row')
    return data

def register_simple_followup_p40_cards(registry):
    def get(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[REX],source_id=c.source_id,cost=CostSpec(delta=-2,card_types=(CardType.MINION,))),)
    def bloom(c):
        healing=HealBatch(tuple(Heal(i,8,c.source_id,HealingKind.SPELL)for i in characters(c,registry,c.player_id)))
        request=SummonFromPool(c.player_id,POOL_ID,QUERIES[BLOOM],source_id=c.source_id,cause=SummonCause.capture(c))
        return healing,request,request
    for name,body in(('wrapper',lambda c:kindred_request(c,REX)),('get',get),(BLOOM,bloom)):registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int:raise TargetValidationError('P40 requires complete collectible faces')
        if cid==REX:
            if(raw['type'],raw['tags'].get('DEATHRATTLE'),raw['tags'].get('KINDRED'),raw['tags'].get('BATTLECRY'))!=('MINION',1,1,None)or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P40 native Kindred and Deathrattle face changed')
            kwargs.update(attack=raw['attack'],health=raw['health'],on_play=PREFIX+'wrapper',deathrattle=PREFIX+'get')
        elif raw['type']=='SPELL'and raw['tags'].get('SPELL_SCHOOL')==4:kwargs.update(on_play=PREFIX+BLOOM,spell_school=SpellSchool.NATURE)
        else:raise TargetValidationError('P40 native Nature spell face changed')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(REX,'body',wrapper=PREFIX+'wrapper',active=PREFIX+'get'))
