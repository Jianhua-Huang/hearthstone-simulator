"""Successful Fel self-destruction/current burst and an ordinary granted DR."""
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Damage,DamageBatch,Destroy,GrantDeathrattle,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters,deathrattle_position

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p43-v1.json'
BATCH_HASH='5edf2a096f0dfd24ec0b9a4227bafd1bdc5047e5c51a7209e480879b3792949d'
BLAZE='FIR_904';BLESSING='TLC_477';ROOTS=(BLAZE,BLESSING);DEPENDENCIES=();EVIDENCE_ONLY=('TLC_477e',);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p43.';PAYLOAD=PREFIX+'summon'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4)

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['evidence_only'])!=EVIDENCE_ONLY or any(data[k]for k in('dependencies','existing_dependencies','skipped')):raise TargetValidationError('P43 complete reviewed recipe set changed')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P43 original row')
    return data

def register_simple_followup_p43_cards(registry):
    def blaze(c):
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):raise ResolutionError('Felfire Blaze lost original completed spell linkage')
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:raise ResolutionError('Felfire Blaze requires actual successful spell completion')
        if cast.player_id!=c.player_id or not living_source(c)or registry.card(cast.card_id).spell_school!=SpellSchool.FEL:return()
        return(Destroy(c.source_id,c.source_id),InvokeBehavior(PREFIX+'burst',c.source_id,c.player_id))
    def burst(c):return(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)for i in characters(c,registry,3-c.player_id))),)
    def grant(c):return(Buff(c.target_id,4,4,c.source_id),GrantDeathrattle(c.target_id,PAYLOAD,c.source_id))
    def summon(c):return(SummonFromPool(c.player_id,POOL_ID,QUERY,source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),)
    for name,body in((BLAZE,blaze),('burst',burst),(BLESSING,grant),('summon',summon)):registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int:raise TargetValidationError('P43 requires complete collectible faces')
        if cid==BLAZE:
            if raw['type']!='MINION'or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P43 native Fel listener lost its minion body')
            kwargs.update(attack=raw['attack'],health=raw['health'],triggers=(TriggerSpec('spell_cast_finished',PREFIX+BLAZE),))
        elif raw['type']=='SPELL'and raw['tags'].get('SPELL_SCHOOL')==5:kwargs.update(on_play=PREFIX+BLESSING,spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']],targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        else:raise TargetValidationError('P43 Blessing lost its Holy spell face')
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
