"""Five native Undead effects using shared turn, health, summon and combat rules."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,Heal,InvokeBehavior,RandomBuff,RandomDamage
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.hero_health_targets import HeroHealthChangedTargetProfile,changed_this_turn
from hs_sim.engine.model import(AttackPolicySpec,CardDefinition,CardType,DamageKind,EndTurnSpec,
    HealingKind,HealthFlow,Keyword,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/undead-native-v1.json'
BATCH_HASH='7ebd39f46f128e3aa7cbde3f75e09fcbc397069b5d0182e2472907f0fc2a75ff'
ASCENDANT='CORE_ICC_210';TOWER='JAIL_440';SPECTER='JAIL_942';LIFERENDER='TIME_614';SPIRIT='CAP_803';GHOUL='HERO_11bpt'
PREFIX='cards.undead_native.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Undead native complete source pin changed')
    return data


def register_undead_native_cards(registry):
    def invoke(c,name):return(InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),)
    def ascend(c):
        candidates=tuple(i for i in minions(c,registry,c.player_id)if i!=c.source_id)
        return(RandomBuff(candidates,1,1,c.source_id),)
    def tower(c):
        if c.event is None or c.event.kind!='damage_dealt' or c.event.target_id!=c.source_id or c.event.amount<=0:return()
        request=SummonByCard(c.player_id,(SummonEntryMaterial(GHOUL),),SummonCause.capture(c))
        return(request,request)
    def liferender(c):
        return(Damage(c.target_id,6,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None and changed_this_turn(c.state,c.player_id)else()
    def spirit(c):return(Heal(c.state.players[c.player_id].hero_id,3,c.source_id,HealingKind.EFFECT,PREFIX+'spirit_result'),)
    def spirit_result(c):
        return(InvokeHealthResult(PREFIX+'spirit_excess',c.event),)if c.health_result.overheal>0 else()
    def spirit_excess(c):
        result=c.health_result
        if result.original_flow!=HealthFlow.HEALING.value or result.overheal<=0:return()
        return(RandomDamage(characters(c,registry,3-c.player_id),result.overheal,c.source_id,DamageKind.MINION_ABILITY),)
    for name,body in(('ascendant',lambda c:invoke(c,'ascend_now')),('ascend_now',ascend),('tower',tower),
        ('liferender',lambda c:invoke(c,'liferender_now')),('liferender_now',liferender),
        ('spirit',spirit),('spirit_result',spirit_result),('spirit_excess',spirit_excess)):
        registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(ASCENDANT,TOWER,SPECTER,LIFERENDER,SPIRIT):
        raise TargetValidationError('Unreviewed native Undead root set')
    for row in data['cards']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete Undead native raw record')
    dependency,=data['existing_dependencies']
    if dependency['record']['id']!=GHOUL or canonical_digest(asdict(registry.card(GHOUL)))!=dependency['definition_sha256']:
        raise TargetValidationError('Frail Ghoul differs from its complete existing native definition')
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if cid==ASCENDANT:kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+'ascendant',EndTurnSpec()),)
        elif cid==TOWER:kwargs['triggers']=(TriggerSpec('damage_dealt',PREFIX+'tower'),)
        elif cid==SPECTER:kwargs.update(keywords=(Keyword.TAUNT,),attack_policies=(AttackPolicySpec('cannot_attack'),))
        elif cid==LIFERENDER:
            kwargs.update(battlecry=PREFIX+'liferender',targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'))
        elif cid==SPIRIT:kwargs.update(keywords=(Keyword.REBORN,),deathrattle=PREFIX+'spirit')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity='ICC_210'if cid==ASCENDANT else cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_hero_health_target_profile(HeroHealthChangedTargetProfile(LIFERENDER))
