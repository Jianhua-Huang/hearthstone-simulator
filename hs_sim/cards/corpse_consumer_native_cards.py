"""Four real corpse consumers and all six fixed child faces, not a formal pool."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.corpse_gains import CorpseGainProfile
from hs_sim.engine.effects import AddToHand, Buff, Damage, SpendResource
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.locations import PlaceLocation
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType, ChooseBranch,
    ChooseOneSpec, DamageKind, Keyword, PaymentType, QuestSpec, QuestStageSpec, Resource, TargetSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.engine.quests import AdvanceQuest
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.resources import corpse_spend_from_event
from hs_sim.engine.spell_targets import DamageResidentSpellTarget
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/corpse-consumer-native-v1.json'
BATCH_HASH = '3972421895b503b4e83ed8d9519a5d4f725fe4cad02469625cbe0182f9aa25f2'
PREFIX = 'cards.corpse_consumer.'
SWARM='EDR_813'; ANTS='EDR_813a'; BITES='EDR_813b'; ANT='EDR_813at'; FALRIC='CORE_EDR_003'
QUEST='TLC_433'; TYRAX='TLC_433t'; GRAVE='TLC_433t2'; THALENA='JAIL_446'; KISS='JAIL_446hp'
MINION = TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Corpse consumer complete source pin changed')
    return data


def register_corpse_consumer_native_cards(registry):
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards']) != (SWARM,FALRIC,QUEST,THALENA):
        raise TargetValidationError('Unreviewed corpse consumer root set')
    if tuple(x['record']['id']for x in data['dependencies']) != (ANTS,BITES,ANT,TYRAX,GRAVE,KISS):
        raise TargetValidationError('Incomplete fixed corpse consumer dependency loop')
    for row in data['cards']+data['dependencies']+data['evidence_only']+data['corpse_spender_records']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete corpse consumer source row')
    spender_ids=frozenset(x['record']['id']for x in data['corpse_spender_records'])
    if len(spender_ids)!=len(data['corpse_spender_records']) or any(x['record']['tags'].get('CORPSE_SPENDER')!=1 for x in data['corpse_spender_records']):
        raise TargetValidationError('Corpse spender physical draw membership changed')

    def ants(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(ANT),),SummonCause.capture(c))
        return(request,request)
    def bites(c):
        damage=DamageResidentSpellTarget(BoardPresenceReference.capture(c.state,c.target_id),c.source_id,4)
        return(SpendResource(c.player_id,Resource.CORPSES,2,on_success=(damage,)),)
    def both(c):return(*ants(c),*bites(c))
    def draw_spender(c):
        actual=tuple(sorted({c.state.entities[i].card_id for i in c.state.players[c.player_id].deck
            if c.state.entities[i].card_id in spender_ids}))
        return(DrawMatching(c.player_id,PoolQuery(),'skip',source_id=c.source_id,card_ids=actual),)if actual else()
    def quest_progress(c):
        row=corpse_spend_from_event(c.event)
        if row is None or row.player_id!=c.player_id or not row.amount:return()
        progress=c.source.quest_progress
        return(AdvanceQuest(c.source_id,progress.id,progress.stage,row.amount),)
    def reward(c):return(AddToHand(c.player_id,TYRAX,c.source_id),)
    def open_grave(c):
        return(PlaceLocation(c.player_id,GRAVE,c.death.position if c.death is not None else None),)
    def resummon(c):
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TYRAX),),SummonCause.capture(c)),)
    def thalena(c):
        player=c.state.players[c.player_id]
        if any(i!=player.hero_power_id for i in player.hero_power_ids):
            raise UnsupportedDefinitionError('Thalena second-slot replacement/refresh with an existing additional Hero Power awaits official evidence')
        return(AddHeroPower(c.player_id,KISS,c.source_id),)
    bodies=dict(ants=ants,bites=bites,both=both,draw_spender=draw_spender,quest_progress=quest_progress,reward=reward,
        open_grave=open_grave,resummon=resummon,thalena=thalena,
        grave_damage=lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.EFFECT),),
        kiss=lambda c:(Buff(c.target_id,3,0,c.source_id),))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    choose=ChooseOneSpec((ChooseBranch('ants','召唤两只蚂蚁',PREFIX+'ants'),
        ChooseBranch('bites','消耗2份残骸，造成4点伤害',PREFIX+'bites',MINION)),
        ChooseBranch('both','召唤蚂蚁，然后消耗残骸造成伤害',PREFIX+'both',MINION))
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        metadata=replace(metadata_from_record(raw),deck_identity='EDR_003'if cid==FALRIC else cid)
        if kind==CardType.MINION:
            kwargs.update(attack=raw['attack'],health=raw['health'])
        if cid==SWARM:kwargs['choose_one']=choose
        elif cid==ANTS:kwargs['on_play']=PREFIX+'ants'
        elif cid==BITES:kwargs.update(on_play=PREFIX+'bites',targeting=MINION)
        elif cid==FALRIC:kwargs['battlecry']=PREFIX+'draw_spender'
        elif cid==QUEST:
            kwargs.update(keywords=(Keyword.QUEST,),quest=QuestSpec('quest',(
                QuestStageSpec(QUEST,15,('resource_spent','corpses_spent'),PREFIX+'quest_progress',PREFIX+'reward'),)))
        elif cid==TYRAX:kwargs['deathrattle']=PREFIX+'open_grave'
        elif cid==GRAVE:kwargs.update(durability=raw['health'],requires_target=True,on_use=PREFIX+'grave_damage',deathrattle=PREFIX+'resummon')
        elif cid==THALENA:kwargs['battlecry']=PREFIX+'thalena'
        elif cid==KISS:kwargs.update(targeting=MINION,on_use=PREFIX+'kiss',cost_payment=PaymentType.CORPSES)
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata,**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_corpse_gain_profile(CorpseGainProfile(FALRIC))
