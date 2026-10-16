"""Native granted Deathrattle, own-discard batch and two ordinary Choose One roots."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import GrantDeathrattle
from hs_sim.engine.model import CardClass,CardDefinition,CardType,ChooseBranch,ChooseOneSpec
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p35-v1.json'
BATCH_HASH='c716030af878ad7f136591c4ccca133063a9bcc58aaa9470ba0f27f7ab9ed7bd'
STAND='CATA_471';ACOLYTES='CATA_499';IDOL='Core_LOE_115';SPARK='EDR_872'
MINION='LOE_115a';SPELL='LOE_115b';MAGE='EDR_872A';DRUID='EDR_872B'
ROOTS=(STAND,ACOLYTES,IDOL,SPARK);DEPENDENCIES=(MINION,SPELL,MAGE,DRUID);CHOICE_ONLY=DEPENDENCIES;EXISTING_DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p35.'
IDENTITIES={cid:'LOE_115'if cid==IDOL else cid for cid in ROOTS+DEPENDENCIES}
QUERIES={STAND:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4),
 ACOLYTES:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1),
 MINION:PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current'),
 SPELL:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),
 MAGE:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False),
 DRUID:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.DRUID,),include_neutral=False)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P35 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or tuple(data['choice_only_ids'])!=CHOICE_ONLY or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('LOE_115','CATA_471e')or data['skipped']):raise TargetValidationError('Unreviewed P35 root/dependency set')
    for row in data['cards']+data['dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P35 original row')
    return data

def register_simple_followup_p35_cards(registry):
    data=load_batch();raws={row['record']['id']:row['record']for row in data['cards']+data['dependencies']}
    def stand(c):return tuple(GrantDeathrattle(i,PREFIX+'rattle',c.source_id)for i in minions(c,registry,c.player_id))
    def rattle(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[STAND],source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),)
    def acolytes(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[ACOLYTES],count=2,destination='board',source_id=c.source_id,cause=SummonCause.capture(c)),)
    def discover(c,branch):return DiscoverFromPool(c.player_id,POOL_ID,QUERIES[branch],source_id=c.source_id)
    bodies={STAND:stand,'rattle':rattle,ACOLYTES:acolytes,
        **{branch:(lambda c,key=branch:(discover(c,key),))for branch in CHOICE_ONLY},
        IDOL+':combined':lambda c:(discover(c,MINION),discover(c,SPELL)),
        SPARK+':combined':lambda c:(discover(c,MAGE),discover(c,DRUID))}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];choice=cid in CHOICE_ONLY;school=raw['tags'].get('SPELL_SCHOOL');kwargs={}
        if raw['type']!='SPELL'or raw['collectible']!=(cid in ROOTS)or type(raw['cost'])is not int or school is not None and school not in SCHOOLS:raise TargetValidationError('P35 requires complete reviewed spell faces')
        if cid in(STAND,ACOLYTES):kwargs['on_play']=PREFIX+cid
        if cid==ACOLYTES:kwargs['on_discard']=PREFIX+cid
        if cid in(IDOL,SPARK):
            branches=(MINION,SPELL)if cid==IDOL else(MAGE,DRUID)
            kwargs['choose_one']=ChooseOneSpec(tuple(ChooseBranch(key,raws[key]['name'],PREFIX+key)for key in branches),ChooseBranch(cid+':combined','兼得',PREFIX+cid+':combined'))
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=0 if choice else raw['cost'],choice_only=choice,spell_school=SCHOOLS.get(school),metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card)
        if not choice:registry.register_pool_card(PoolCard.from_definition(card))
