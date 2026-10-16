"""Eight complete real conditional consumers, using native public executors."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage,DamageBatch,Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,HandActionSpec,Keyword,
    StatRelationLayer,StatRelationOperand,StatRelationSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import starting_deck_identity
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.spell_target_sequences import FreezeAdjacentThenDestroyDamaged
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference,DiscardMatching,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/conditional-consumers-v1.json'
BATCH_HASH='0c630186bd5d9e317bafc2229883da4218758601119cb32385bcdbd8178fc7df'
CULTIST='TLC_101';TYRANT='TLC_605';KEEPER='TIME_062';BITTER='END_023';AXE='TLC_478';CLAWS='END_016';AUCTIONEER='JAIL_718';WAYGATE='TLC_364'
ROOTS=(CULTIST,TYRANT,KEEPER,BITTER,AXE,CLAWS,AUCTIONEER,WAYGATE)
PREFIX='cards.conditional_consumers.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Conditional consumers lost their complete source pin')
    return data


def register_conditional_consumer_cards(registry):
    def keeper(c):
        if not living_source(c):return ()
        if not any(has_any_tribe(registry,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand):return ()
        original=MinionReference.capture(c.source)
        return tuple(GrantCapturedKeyword(original,k,c.source_id)for k in(Keyword.TAUNT,Keyword.DIVINE_SHIELD))
    def bitter(c):
        if c.cast is None or c.cast.source_id!=c.source_id:raise ResolutionError('Bitter End requires its actual spell cast')
        target=c.state.entities[c.target_id]
        if target.zone!=Zone.BOARD or target.kind!=CardType.MINION or not target.active or target.health<=0 or target.doomed:return ()
        return(FreezeAdjacentThenDestroyDamaged(c.player_id,c.cast.id,c.source_id,MinionReference.capture(target)),)
    def hero_attack(c):
        row=completed_attack(c)
        return row is not None and row.source_kind==CardType.HERO and row.declaration.player_id==c.player_id
    def axe(c):
        if not hero_attack(c):return ()
        ids=tuple(i for player in c.state.players.values()for i in player.board
            if(e:=c.state.entities[i]).kind==CardType.MINION and e.active and e.health>0 and not e.doomed)
        return(DamageBatch(tuple(Damage(i,1,c.source_id,DamageKind.EFFECT)for i in ids)),)
    def claws(c):
        return(DiscardMatching(c.player_id,selection='highest_cost',source_id=c.source_id),)if hero_attack(c)else()
    def auctioneer(c):
        record=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):raise ResolutionError('Auctioneer lost its original actual cast')
        if not living_source(c)or record.player_id!=c.player_id or record.failure not in(None,'countered'):return ()
        return(Draw(c.player_id,source_id=c.source_id),)
    def waygate(c):
        originals,_=starting_deck_identity(c.state);original_ids=set(originals[c.player_id-1])
        return tuple(ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=-1),c.source_id)
            for i in c.state.players[c.player_id].hand for entity in(c.state.entities[i],)
            if i not in original_ids or entity.face_replaced)
    for name,body in(('keeper',keeper),('bitter',bitter),('axe',axe),('claws',claws),('auctioneer',auctioneer),('waygate',waygate)):
        registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    if tuple(row['record']['id']for row in data['cards'])!=ROOTS or data['dependencies']:raise TargetValidationError('Unreviewed conditional consumer set')
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or not raw['collectible']:raise TargetValidationError('Incomplete conditional consumer face')
        if cid in(CULTIST,TYRANT):
            kwargs['keywords']=(Keyword.TAUNT,Keyword.REBORN if cid==CULTIST else Keyword.LIFESTEAL)
            kwargs['stat_relations']=(StatRelationSpec(operand=StatRelationOperand.SELF_DAMAGED if cid==CULTIST else StatRelationOperand.CONTROLLER_OPPONENT_TURN,
                layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=3 if cid==CULTIST else 6),)
        elif cid==KEEPER:kwargs['battlecry']=PREFIX+'keeper'
        elif cid==BITTER:kwargs.update(on_play=PREFIX+'bitter',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        elif cid in(AXE,CLAWS):kwargs.update(durability=raw['health'],triggers=(TriggerSpec('attack_finished',PREFIX+('axe'if cid==AXE else'claws')),))
        elif cid==AUCTIONEER:kwargs.update(hand_actions=(HandActionSpec('prepare','prepare',1),),triggers=(TriggerSpec('spell_cast_started',PREFIX+'auctioneer'),))
        elif cid==WAYGATE:kwargs['on_play']=PREFIX+'waygate'
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']if kind==CardType.MINION else 0,
            metadata=replace(metadata_from_record(raw),deck_identity=cid),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
