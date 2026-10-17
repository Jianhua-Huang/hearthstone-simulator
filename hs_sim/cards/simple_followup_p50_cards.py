"""Reviewed reachable child bodies and native damage, health and power effects."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.effects import ChoiceOption,Damage,DamageBatch,Heal,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,EndTurnSpec,
    HealthFlow,Keyword,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference,live_minion
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p50-v1.json'
BATCH_HASH='dfe7d4db7d43065faffa8e03c9f73e10075392ad3e48f03f6c865195321034cd'
GHOST='CAP_802t';POWER='EX1_tk33';BLOOD='CATA_300t1';PLUME='CATA_488t2';BODY='CATA_550t'
STRIKER='CATA_551t';GOLD='JAIL_801t';STORM='JAIL_805t';JUVENILE='TLC_831t';IMP='UNG_829t3';INFERNAL='EX1_tk34'
ROOTS=(GHOST,POWER,BLOOD,PLUME,BODY,STRIKER,GOLD,STORM,JUVENILE,IMP)
DEPENDENCIES=(INFERNAL,);PARENTS=('CAP_802','CORE_EX1_323','CATA_300','CATA_488','CATA_550','CATA_551','JAIL_801','JAIL_805','TLC_831','TLC_466')
PREFIX='cards.simple_followup_p50.';POOL_ID='constructed.cards'
FIRE_QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.FIRE,))

def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS
            or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES
            or tuple(x['record']['id']for x in d['evidence_only'])!=PARENTS or d['skipped']):
        raise TargetValidationError('P50 complete reviewed child/parent scope changed')
    for row in d['cards']+d['dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('P50 original full source row changed')
    return d

def sampled(c,options,callback):
    return(RequestChoice(c.player_id,tuple(options),c.source_id,min_count=0,max_count=0,
        sample_size=1,on_select=callback),)if options else()

def original_option(c):
    if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:
        raise ResolutionError('P50 random effect lost its original single sampled material')
    return json.loads(c.choice.choice.options[0].id)

def register_simple_followup_p50_cards(registry):
    data=load_batch()
    def blood(c):
        options=[]
        for i in characters(c,registry,c.player_id):
            e=c.state.entities[i]
            if e.health>=e.max_health:continue
            material=dict(minion=asdict(MinionReference.capture(e)))if e.kind==CardType.MINION else dict(hero=i,player=c.player_id)
            options.append(ChoiceOption(json.dumps(material,sort_keys=True),'Original wounded friendly character'))
        return sampled(c,options,PREFIX+'heal_selected')
    def heal_selected(c):
        material=original_option(c)
        if set(material)=={'minion'}:
            ref=MinionReference(**material['minion']);e=live_minion(c.state,ref)
            if ref.player_id!=c.player_id:raise ResolutionError('Healing material changed its original friendly controller')
        elif set(material)=={'hero','player'}:
            if material['player']!=c.player_id:raise ResolutionError('Healing material changed its original hero player')
            e=c.state.entities.get(material['hero'])
            if e is None or(e.id,e.controller,e.zone)!=(c.state.players[c.player_id].hero_id,c.player_id,Zone.HERO)or e.health<=0:return()
        else:raise ResolutionError('Unreviewed original healing material')
        return(Heal(e.id,3,c.source_id),)if e is not None else()
    def plume(c):
        result=c.health_result
        if result is None:raise ResolutionError('Plume requires its original actual damage result')
        if(result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0 or
                (result.target_id,result.target_controller,result.target_kind)!=(c.source_id,c.player_id,CardType.MINION.value)or
                (result.target_zone_epoch,result.target_entered_order)!=(c.source.zone_epoch,c.source.entered_order)):
            return()
        return(GenerateFromPool(c.player_id,POOL_ID,FIRE_QUERY,source_id=c.source_id,cost=CostSpec(delta=-3)),)
    def body(c):
        options=tuple(ChoiceOption(json.dumps(asdict(MinionReference.capture(c.state.entities[i])),sort_keys=True),
            'Original friendly minion')for i in minions(c,registry,c.player_id))
        return sampled(c,options,PREFIX+'buff_selected')
    def buff_selected(c):
        ref=MinionReference(**original_option(c))
        if ref.player_id!=c.player_id:raise ResolutionError('Deathrattle changed its original friendly beneficiary')
        return(BuffCapturedMinion(ref,2,0,c.source_id),)
    bodies={'blood':blood,'heal_selected':heal_selected,'plume':plume,'body':body,'buff_selected':buff_selected,
        'gold':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None else(),
        'storm':lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)
            for i in minions(c,registry,3-c.player_id))),),
        'power':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(INFERNAL),),SummonCause.capture(c)),)}
    for name,callback in bodies.items():registry.register_behavior(PREFIX+name,callback)
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not False or type(raw['cost'])is not int:raise TargetValidationError('P50 children must retain exact noncollectible faces')
        if cid==GHOST:kwargs['keywords']=(Keyword.REBORN,)
        if cid==STRIKER:kwargs['keywords']=(Keyword.TAUNT,)
        if cid==BLOOD:kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+'blood',EndTurnSpec()),)
        if cid==PLUME:kwargs['triggers']=(TriggerSpec('health_resolved',PREFIX+'plume'),)
        if cid==BODY:kwargs['deathrattle']=PREFIX+'body'
        if cid==GOLD:kwargs.update(battlecry=PREFIX+'gold',targeting=TargetSpec(TargetMode.IF_AVAILABLE))
        if cid==STORM:kwargs.update(battlecry=PREFIX+'storm',keywords=(Keyword.LIFESTEAL,))
        if cid==POWER:kwargs.update(on_use=PREFIX+'power',requires_board_space=True)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kwargs)
        registry.register_card(card)
        if kind==CardType.MINION:registry.register_pool_card(PoolCard.from_definition(card))
