"""Three actual Webspinners and one ordinary-plus-Kindred pool summon."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.kindred import repeat_components
from hs_sim.engine.model import CardDefinition,CardType,KindredProfile,Keyword,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p38-v1.json'
BATCH_HASH='ddbfdd365550df2e013a1f00a2c3d1d895089caf311a4e0acbbea1c464a64f5e'
SPIDERS='CORE_AT_062';BULB='TLC_815';SPINNER='FP1_011';ROOTS=(SPIDERS,BULB);DEPENDENCIES=(SPINNER,);EXISTING_DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p38.'
IDENTITIES={SPIDERS:'AT_062',BULB:BULB,SPINNER:SPINNER}
QUERIES={SPINNER:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('beast',)),
 BULB:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('AT_062','TLC_815e')or data['skipped']):raise TargetValidationError('P38 complete reviewed recipe set changed')
    for row in data['cards']+data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P38 original row')
    return data

def register_simple_followup_p38_cards(registry):
    data=load_batch()
    def spiders(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(SPINNER),),SummonCause.capture(c))
        return request,request,request
    def spinner(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[SPINNER],source_id=c.source_id),)
    def summon(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[BULB],source_id=c.source_id,cause=SummonCause.capture(c),entry_keywords=(Keyword.TAUNT,)),)
    def prepare(c):return(*summon(c),*repeat_components(c))
    for name,body in((SPIDERS,spiders),(SPINNER,spinner),('wrapper',lambda c:()),('prepare',prepare),('active',summon)):registry.register_behavior(PREFIX+name,body)
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int:raise TargetValidationError('P38 requires complete collectible faces')
        if cid==SPINNER:
            if raw['type']!='MINION'or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P38 actual Webspinner stats required')
            kwargs.update(attack=raw['attack'],health=raw['health'],deathrattle=PREFIX+SPINNER)
        elif cid==SPIDERS:
            if raw['type']!='SPELL'or raw['tags'].get('SPELL_SCHOOL')is not None:raise TargetValidationError('P38 unschooled Spiders face changed')
            kwargs['on_play']=PREFIX+SPIDERS
        elif raw['type']=='SPELL'and raw['tags'].get('SPELL_SCHOOL')==6 and raw['tags'].get('KINDRED')==1:kwargs.update(on_play=PREFIX+'wrapper',spell_school=SpellSchool.SHADOW)
        else:raise TargetValidationError('P38 native Shadow Kindred face changed')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(BULB,'body',wrapper=PREFIX+'wrapper',prepare=PREFIX+'prepare',active=PREFIX+'active'))
