"""Reviewed native effects needed by the untrimmed six-cost summon inventory."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (CopyMinion,Damage,DamageBatch,Draw,GrantKeyword,InvokeBehavior,
    RandomDamage,RandomDamageBatch,RandomDestroy,RandomForceAttack,SwapStats)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (AttackPolicySpec,CardDefinition,CardType,CostSpec,DamageKind,
    BoardPresenceReference,EndTurnSpec,HealthFlow,Keyword,Resource,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.resource_operations import SpendUpToResource
from hs_sim.engine.sacrifice import MinionReference,SetCapturedMinionStats
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect,death_candidates
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/six-cost-native-effects-v1.json'
BATCH_HASH='ba2794da29a97030434e05691221e732f30461dcd8b2faccac2cf3a2aebd613b'
PREFIX='cards.six_cost_native.'
SCRIPTS={'CORE_RLK_505':'marrow','EDR_238':'merithra','FIR_940':'flamebinder','RLK_720':'gnome',
 'TIME_043':'infinitizer','TIME_050':'hourglass','TIME_605':'stalker','TLC_401':'stegodon',
 'TLC_454':'kodo','TLC_522':'opu','TLC_624':'nablya','EX1_129':'fan'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Six-cost native complete reviewed pin changed')
    return data


def register_six_cost_native_cards(registry):
    def invoke(c,name):
        return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,
            None if c.play is None else c.play.id)

    def marrow_result(c):
        result=c.resource_result
        if result is None or(result.player_id,result.source_id,result.resource,result.cap)!=(c.player_id,c.source_id,Resource.CORPSES,5):
            raise ResolutionError('Marrow Manipulator requires its actual capped corpse debit')
        return tuple(invoke(c,'marrow_hit')for _ in range(result.actual_amount))

    def merithra(c):
        query=DeathQuery(cards=PoolQuery(min_cost=8))
        count=len({r.card_id for r in death_candidates(c.state,registry,c.player_id,query,c.source_id)})
        return (Resurrect(c.player_id,count,query,distinct='card',source_id=c.source_id,
            cause=SummonCause.capture(c)),)if count else ()

    def flamebinder(c):
        cards=tuple(c.state.entities[i]for i in c.state.players[c.player_id].hand)
        prices=tuple(quote_unselected_cost(c.state,registry,e).amount for e in cards)
        return tuple(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-2),c.source_id)
            for e in cards)if len(set(prices))==len(prices)else ()

    def gnome(c):
        ids=characters(c,registry,3-c.player_id)
        if c.source_id not in minions(c,registry,c.player_id)or not ids:return ()
        lowest=min(c.state.entities[i].health for i in ids)
        return (RandomForceAttack((c.source_id,),tuple(i for i in ids if c.state.entities[i].health==lowest),c.source_id),)

    def infinitizer(c):
        if c.target_id is None:return ()
        original=MinionReference.capture(c.state.entities[c.target_id])
        return (SetCapturedMinionStats(original,8,8,c.source_id),GrantAttackPolicy(c.target_id,
            AttackPolicySpec('cannot_attack_heroes'),c.source_id,c.state.turn,recipient=original))

    def hourglass(c):
        result=c.health_result
        if result is None:raise ResolutionError('Sentient Hourglass requires its original health outcome')
        source=c.source
        if(result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0 or result.target_id!=c.source_id
                or result.health_after<=0 or result.doomed_after or source.zone!=Zone.BOARD
                or not source.active or source.health<=0 or source.doomed
                or(result.target_zone_epoch,result.target_entered_order)!=(source.zone_epoch,source.entered_order)):
            return ()
        return (SwapStats(c.source_id,c.source_id),)

    def kodo(c):
        ids=minions(c,registry,3-c.player_id)
        if not ids:return ()
        related=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card(c.source.card_id)))
        extreme=(max if related.matched else min)(c.state.entities[i].attack for i in ids)
        return (RandomDestroy(tuple(i for i in ids if c.state.entities[i].attack==extreme),c.source_id),)

    def nablya(c):
        cause=SummonCause.capture(c)
        # Capture eligibility now; each copy accepts material in its own real window.
        return tuple(CopyMinion(BoardPresenceReference.capture(c.state,i),c.player_id,
            cause=cause,on_summon=PREFIX+'rush')
            for i in minions(c,registry,c.player_id)
            if c.state.entities[i].health<c.state.entities[i].max_health)

    def stalker(c):
        if c.deathrattle is not None:
            from hs_sim.engine.death_self_copies import copy_body
            return copy_body(c)
        return (CopyMinion(c.source_id,c.player_id,cause=SummonCause.capture(c)),)

    bodies=dict(marrow=lambda c:(SpendUpToResource(c.player_id,Resource.CORPSES,5,c.source_id,PREFIX+'marrow_result'),),
        marrow_result=marrow_result,
        marrow_hit=lambda c:(RandomDamage(characters(c,registry,3-c.player_id),2,c.source_id,DamageKind.MINION_ABILITY),),
        merithra=lambda c:(invoke(c,'merithra_now'),),merithra_now=merithra,
        flamebinder=lambda c:(invoke(c,'flamebinder_now'),),flamebinder_now=flamebinder,
        gnome=lambda c:(invoke(c,'gnome_now'),),gnome_now=gnome,infinitizer=infinitizer,hourglass=hourglass,
        stalker=stalker,
        stegodon=lambda c:(RandomDamageBatch(characters(c,registry,3-c.player_id),3,6,c.source_id,DamageKind.MINION_ABILITY),),
        kodo=lambda c:(invoke(c,'kodo_now'),),kodo_now=kodo,
        opu=lambda c:(CastSpell(c.player_id,'EX1_129',c.source_id),),
        nablya=lambda c:(invoke(c,'nablya_now'),),nablya_now=nablya,
        rush=lambda c:(GrantKeyword(c.target_id,Keyword.RUSH,c.source_id),),
        fan=lambda c:(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.SPELL)
            for i in minions(c,registry,3-c.player_id))),Draw(c.player_id,source_id=c.source_id)))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    for row in data['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Six-cost original identity changed')
    alias=next(x['record']for x in data['cards']if x['record']['id']=='CORE_RLK_505')
    if alias['tags']['858']!=data['historical_identity_evidence'][0]['record']['dbf_id']:
        raise TargetValidationError('Core Marrow Manipulator lost its original deck identity')
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if(canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=script
                or raw['collectible']is not True or raw['type']!=('SPELL'if script=='fan'else'MINION')):
            raise TargetValidationError('Unreviewed native six-cost face')
        kwargs={};body=PREFIX+script
        if script=='fan':kwargs['on_play']=body
        elif script=='hourglass':kwargs['triggers']=(TriggerSpec('health_resolved',body),)
        elif script=='gnome':kwargs['triggers']=(TriggerSpec('turn_ended',body,EndTurnSpec()),)
        elif script=='stegodon':kwargs['deathrattle']=body
        else:kwargs['battlecry']=body
        if script=='opu':kwargs.update(combo=body,deathrattle=body)
        if script=='infinitizer':kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,
            zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
        card=CardDefinition(raw['id'],raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],
            attack=raw['attack']or 0,health=raw['health']or 0,
            keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
