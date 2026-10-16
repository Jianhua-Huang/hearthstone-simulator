"""Real spell continuations over original draw, health, death and spent material."""
from hs_sim.engine.deck_shuffles import shuffled
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.draw_beneficiaries import DrawMatchingWithFollowup
from hs_sim.engine.effects import ChoiceOption,Damage,GainArmor,RequestChoice
from hs_sim.engine.health_followups import InvokeHealthResult
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,HandProgressSpec,
    Keyword,PlayerEffectSpec,SpellSchool,SummonStats,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_targets import ApplySpellTarget
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference,CopyCard,DiscardMatching,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_beneficiary_cards import drawn_card
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/original-material-spells-v1.json'
BATCH_HASH='7dd248ded52126d35d8547b790cadc6cc960d047064d556af829d28cf7b33b05'
PREFIX='cards.original_material.'
SCRIPTS={'FIR_941':'image','CATA_978':'victory','JAIL_225':'hijack','END_025':'eternal','FIR_910':'wind','TIME_702':'tide'}
RETURN_ID=PREFIX+'eternal_return'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Original-material cards lost their complete reviewed pin')
    return data


def direct_death(c):
    result=c.health_result
    return next((d for d in c.state.death_history if result.target_id==result.original_target_id and d.entity_id==result.original_target_id
        and d.cause.kind in('damage','poison')and d.cause.result==result.payload()),None)


def register_original_material_cards(registry):
    def image_copy(c):
        entity=drawn_card(c)
        return (CopyStoredMinion(CardReference.capture(entity),c.player_id,stats=SummonStats(8,8),
            cause=SummonCause.capture(c),minion_grant=CreatedMinionGrant(keywords=(Keyword.DIVINE_SHIELD,))),)
    def victory_reduce(c):
        result=c.health_result;amount=max(0,result.damage_dealt-max(0,result.health_before))
        if not amount:return ()
        options=[]
        for eid in c.state.players[c.player_id].hand:
            reference=CardReference.capture(c.state.entities[eid]);material=dict(card=asdict(reference),amount=amount)
            material['card']['zone']=reference.zone.value
            options.append(ChoiceOption(json.dumps(material,sort_keys=True,separators=(',',':')),'Random hand card',entity_id=eid))
        return (RequestChoice(c.player_id,tuple(options),c.source_id,min_count=0,max_count=0,sample_size=1,on_select=PREFIX+'victory_selected'),)if options else ()
    def victory_selected(c):
        result=c.choice
        if result is None or result.selected_ids or len(result.choice.options)!=1:raise TargetValidationError('Excess damage lost its original sampled hand beneficiary')
        option=result.choice.options[0];data=json.loads(option.id)
        if set(data)!={'card','amount'}or type(data['amount'])is not int or data['amount']<=0:raise TargetValidationError('Excess damage lost its accepted positive amount')
        reference=CardReference(**dict(data['card'],zone=Zone(data['card']['zone'])))
        if(reference.player_id,reference.entity_id,reference.zone)!=(c.player_id,option.entity_id,Zone.HAND):raise TargetValidationError('Excess damage changed its original hand reference')
        return (ModifyStoredCost(reference,CostSpec(delta=-data['amount']),c.source_id),)
    def hijack_after(c):
        row=direct_death(c)
        return shuffled(c,(CopyCard(row,c.player_id,Zone.DECK,mode='base',source_id=c.source_id,cost=CostSpec(set_to=2)),))if row is not None else ()
    def eternal_after(c):
        return (AddPlayerEffect(c.player_id,RETURN_ID,c.source_id,capture_health_source=True),)if direct_death(c)is not None else ()
    def eternal_return(c):
        if c.event is None or c.event.player_id!=c.player_id:return ()
        instance=c.player_effect
        if instance is None or instance.source_allocation is None or instance.source_player_id!=c.player_id:
            raise TargetValidationError('Delayed return lost its original captured spell and beneficiary')
        return (RemovePlayerEffect(c.player_id,instance.id),ReturnSpentSpell(allocation_from_payload(instance.source_allocation),c.player_id))
    def wind_result(c):
        entity=c.state.entities[c.health_result.original_target_id]
        target=MinionReference.capture(entity)if entity.kind==CardType.MINION else entity.id
        return (DiscardMatching(c.player_id,PoolQuery(kinds=(CardType.SPELL,),spell_schools=(SpellSchool.FIRE,)),source_id=c.source_id,
            on_success=(ApplySpellTarget(target,c.source_id,'damage',3),)),)
    def tide(c):
        complete=any(a.kind=='hand_progress'and a.hand_progress==registry.card('TIME_702').hand_progress and a.progress_completions>0 for a in c.source.abilities)
        return (Damage(c.target_id,3,c.source_id,DamageKind.SPELL),*((GainArmor(c.player_id,5),)if complete else ()))
    def minion_committed(c):
        if c.event is None or c.event.player_id!=c.player_id:return False
        number=dict(c.event.data).get('play_id')
        if number is None:return False
        row=play_record(c.state,number)
        return row.player_id==c.player_id and row.kind==CardType.MINION and row.source_id!=c.source_id
    registry.register_trigger_condition(PREFIX+'held_minion',minion_committed)
    bodies=dict(image=lambda c:(DrawMatchingWithFollowup(c.player_id,PoolQuery(kinds=(CardType.MINION,)),c.source_id,PREFIX+'image_copy'),),image_copy=image_copy,
        victory=lambda c:(Damage(c.target_id,8,c.source_id,DamageKind.SPELL,PREFIX+'victory_result'),),
        victory_result=lambda c:(InvokeHealthResult(PREFIX+'victory_reduce',c.event),),victory_reduce=victory_reduce,victory_selected=victory_selected,
        hijack=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'hijack_result'),),
        hijack_result=lambda c:(InvokeHealthResult(PREFIX+'hijack_after',c.event),),hijack_after=hijack_after,
        eternal=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'eternal_result'),),
        eternal_result=lambda c:(InvokeHealthResult(PREFIX+'eternal_after',c.event),),eternal_after=eternal_after,eternal_return=eternal_return,
        wind=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL,PREFIX+'wind_result'),),wind_result=wind_result,
        tide=tide,held_ready=lambda c:())
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];kwargs={};target=recipe['target']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(raw['id'])!=recipe['script']:
            raise TargetValidationError('Original-material recipe lost its complete reviewed spell face')
        if target=='minion':kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        elif target=='character':kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
        elif target is not None:raise TargetValidationError('Unknown original-material target domain')
        if raw['id']=='TIME_702':kwargs['hand_progress']=HandProgressSpec('event',event='card_committed',condition_id=PREFIX+'held_minion',on_complete=PREFIX+'held_ready')
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],
            keywords=(Keyword.LIFESTEAL,)if raw['tags'].get('LIFESTEAL')==1 else (),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(RETURN_ID,'END_025',triggers=(TriggerSpec('turn_ended',PREFIX+'eternal_return'),)))
