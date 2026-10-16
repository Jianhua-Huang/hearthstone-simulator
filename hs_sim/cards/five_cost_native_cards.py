"""Reviewed five-cost real roots composed from the shared rules interpreter."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.dark_gifts import public_gifts
from hs_sim.engine.destruction_resources import DestroyMinionsForResources
from hs_sim.engine.effects import Buff, Damage, DoubleStats, Draw, GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.kindred import request as kindred_request
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, CostSpec,
    DamageKind, EndTurnSpec, HandActionSpec, HandProgressSpec, KindredProfile, Keyword, TriggerSpec, Zone)
from hs_sim.engine.owner_turns import owner_turn_index
from hs_sim.engine.physical_draw_groups import DrawGroupReward, DrawGroupSlot, DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import CardReference, ModifyStoredCost
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/five-cost-native-v1.json'
BATCH_HASH = '9150e06b6a1425e635a6c9127b44145a32f61e2d680207eb486fcd4de4dc876c'
RAGER='TIME_048'; SOLDIER='TIME_051'; MATRIARCH='FIR_901'; ANCIENT='EDR_979'
JAILBIRD='JAIL_453'; HOGDRIVER='JAIL_462'; SAWBONES='JAIL_444'; STORM='TLC_107'; BROODLING='FIR_901t'
ROOTS=(RAGER,SOLDIER,MATRIARCH,ANCIENT,JAILBIRD,HOGDRIVER,SAWBONES,STORM)
PREFIX='cards.five_cost_native.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH: raise TargetValidationError('Five-cost native complete source pin changed')
    return data


def register_five_cost_native_cards(registry):
    def matriarch(c):
        if not any(c.state.entities[i].kind==CardType.MINION and public_gifts(c.state.entities[i]) for i in c.state.players[c.player_id].hand): return ()
        request=SummonByCard(c.player_id,(SummonEntryMaterial(BROODLING),),SummonCause.capture(c))
        return request, request
    def jailbird(c):
        return (ModifyStoredCost(CardReference.capture(c.source),CostSpec(delta=-c.event.amount),c.source_id),)
    def hogdriver(c):
        reward=(DrawGroupReward('source_charge_if_both_minions',source=BoardPresenceReference.capture(c.state,c.source_id))
            if c.source.kind==CardType.MINION and c.source.zone==Zone.BOARD else DrawGroupReward())
        return (DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),DrawGroupSlot()),reward),)
    def sawbones(c):
        victims=tuple(MinionReference.capture(c.state.entities[i]) for i in minions(c,registry,c.player_id) if i!=c.source_id)
        return (DestroyMinionsForResources(c.player_id,c.source_id,victims),)
    def storm(c):
        if c.event is None or c.event.kind!='attack_declared' or c.event.source_id!=c.source_id: return ()
        ident=dict(c.event.data)['window_id']
        rows=[row for row in c.state.character_attack_history if row.declaration.id==ident]
        if len(rows)!=1: raise ResolutionError('Stormbrewer lost its original character attack')
        row=rows[0];w=row.declaration
        if (w.source_id,w.target_id,w.player_id,row.declaration_event_cursor+1)!=(c.source_id,c.event.target_id,c.player_id,c.event.sequence):
            raise ResolutionError('Stormbrewer borrowed another attack declaration')
        return (Damage(w.target_id,3,c.source_id,DamageKind.MINION_ABILITY),)
    bodies={
        'rager':lambda c:(Buff(c.source_id,health=owner_turn_index(c.state,c.player_id),source_id=c.source_id),),
        'soldier':lambda c:(DoubleStats(c.source_id,attack=True,source_id=c.source_id),),
        'matriarch':matriarch,'ancient':lambda c:(GainArmor(c.player_id,3),Draw(c.player_id,source_id=c.source_id)),
        'jailbird':jailbird,'hogdriver':hogdriver,'sawbones':sawbones,'storm':storm,
        'storm_kindred':lambda c:kindred_request(c,STORM),
        'storm_rush':lambda c:(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.RUSH,c.source_id),),
    }
    for name,body in bodies.items(): registry.register_behavior(PREFIX+name,body)
    registry.register_trigger_condition(PREFIX+'own_prepare',lambda c:c.event is not None and c.event.player_id==c.player_id)
    data=load_batch()
    if tuple(row['record']['id'] for row in data['cards'])!=ROOTS or tuple(row['record']['id'] for row in data['dependencies'])!=(BROODLING,):
        raise TargetValidationError('Unreviewed five-cost native root/dependency set')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={};keywords=()
        if canonical_digest(raw)!=row['record_sha256'] or raw['type']!='MINION': raise TargetValidationError('Incomplete five-cost native raw face')
        if cid==RAGER: kwargs['battlecry']=PREFIX+'rager'
        elif cid==SOLDIER: kwargs['battlecry']=PREFIX+'soldier';keywords=(Keyword.RUSH,)
        elif cid==MATRIARCH: kwargs['battlecry']=PREFIX+'matriarch'
        elif cid==ANCIENT: kwargs.update(dormant_turns=2,dormant_triggers=(TriggerSpec('turn_ended',PREFIX+'ancient',EndTurnSpec()),))
        elif cid==JAILBIRD:
            keywords=(Keyword.TAUNT,)
            kwargs['hand_progress']=HandProgressSpec('event',1,on_complete=PREFIX+'jailbird',repeat=True,event='card_prepared',condition_id=PREFIX+'own_prepare')
        elif cid==HOGDRIVER: kwargs['battlecry']=PREFIX+'hogdriver'
        elif cid==SAWBONES: kwargs.update(battlecry=PREFIX+'sawbones',hand_actions=(HandActionSpec('prepare','prepare',1),))
        elif cid==STORM: kwargs.update(on_play=PREFIX+'storm_kindred',triggers=(TriggerSpec('attack_declared',PREFIX+'storm'),))
        elif cid==BROODLING: keywords=(Keyword.TAUNT,)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'] or 0,health=raw['health'] or 0,
            keywords=keywords,metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(STORM,'body',wrapper=PREFIX+'storm_kindred',active=PREFIX+'storm_rush'))
