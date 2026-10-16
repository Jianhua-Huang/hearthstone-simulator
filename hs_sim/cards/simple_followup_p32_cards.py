"""Eight reviewed consumers of native pool, resource and card-entry machinery."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Destroy,GainArmor
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,PaymentType,RewindSpec,SpellSchool,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p32-v1.json'
BATCH_HASH='b0e5dfcbbccfc36a15e712ec027524419af545d09d2f3305195c9f853dea0e67'
IRON='CORE_WON_337';SILVER='CORE_KAR_077';HORN='EDR_270';BLOOD='TIME_612';BIOME='TLC_449';REGROWTH='TIME_033';DETHRONE='TIME_712';GUARD='DINO_433'
ASSIGNED_ROOTS=(IRON,SILVER,HORN,BLOOD,BIOME,REGROWTH,DETHRONE,GUARD);ROOTS=tuple(cid for cid in ASSIGNED_ROOTS if cid!=BIOME);SKIPPED=(BIOME,);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p32.'
IDENTITIES={cid:('WON_337'if cid==IRON else'KAR_077'if cid==SILVER else cid)for cid in ROOTS}
def minion_query(cost,taunt=False):return PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost,keywords_all=(Keyword.TAUNT,)if taunt else())
QUERIES={IRON:minion_query(4),SILVER:minion_query(2),HORN:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',spell_schools=(SpellSchool.NATURE,)),
 BLOOD:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),BIOME:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1,class_mode='current'),
 REGROWTH:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.NATURE,)),DETHRONE:minion_query(8),**{GUARD+'.'+str(n):minion_query(n,True)for n in(6,4,2)}}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P32 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('WON_337','KAR_091','KAR_077')or tuple(x['record']['id']for x in data['skipped'])!=SKIPPED):raise TargetValidationError('Unreviewed P32 recipe set')
    for row in data['cards']+data['skipped']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P32 original row')
    return data

def register_simple_followup_p32_cards(registry):
    def summon(c,key):return SummonFromPool(c.player_id,POOL_ID,QUERIES[key],source_id=c.source_id,cause=SummonCause.capture(c))
    def iron(c):return(GainArmor(c.player_id,4),summon(c,IRON))
    def silver(c):return(Buff(c.target_id,2,2,c.source_id),summon(c,SILVER))
    def horn(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[HORN],source_id=c.source_id,cost=CostSpec(delta=-2)),)
    def blood(c):return(DiscoverFromPool(c.player_id,POOL_ID,QUERIES[BLOOD],source_id=c.source_id),)
    def regrowth(c):return(CastFromPool(c.player_id,POOL_ID,QUERIES[REGROWTH],count=2,source_id=c.source_id),)
    def dethrone(c):return combo(c)if c.spell_conditions.combo else(Destroy(c.target_id,c.source_id),)
    def combo(c):return(Destroy(c.target_id,c.source_id),summon(c,DETHRONE))
    def guard(c):return tuple(summon(c,GUARD+'.'+str(n))for n in(6,4,2))
    bodies=dict(zip(ROOTS,(iron,silver,horn,blood,regrowth,dethrone,guard)))
    registry.register_behavior(PREFIX+'combo',combo)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());school=raw['tags'].get('SPELL_SCHOOL');kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int or school is not None and school not in SCHOOLS:raise TargetValidationError('P32 requires complete reviewed faces')
        registry.register_behavior(PREFIX+cid,bodies[cid])
        if cid==REGROWTH:
            if kind!=CardType.MINION or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('Regrowth requires its actual minion face')
            kwargs.update(attack=raw['attack'],health=raw['health'],battlecry=PREFIX+cid,keywords=(Keyword.REWIND,),rewind=RewindSpec())
        elif kind==CardType.SPELL:kwargs['on_play']=PREFIX+cid
        else:raise TargetValidationError('Unreviewed P32 card type')
        if cid in(SILVER,DETHRONE):kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='any')
        if cid==BLOOD:kwargs['cost_payment']=PaymentType.HEALTH
        if cid==DETHRONE:kwargs['keywords']=(Keyword.COMBO,)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],spell_school=SCHOOLS.get(school),metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
