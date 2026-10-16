"""Real hand/deck consumers; all mutation stays in existing public effects."""
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.summon_quantities import card_summon
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import (Buff,CopyMinion,Damage,Draw,GrantKeyword,InvokeBehavior,
    SpendResource,Summon)
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,EndTurnSpec,Keyword,
    Resource,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import (CardReference,CopyCard,CopyMatching,DestroyDeckCard,
    DiscardCard,MoveCard)
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .health_cards import SCHOOLS

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/zone-effects-v1.json'
BATCH_HASH='76803d85a6a5b64e82fabf9776e799e291e97651b1bd7aa331ecf0fe206af8e9'
PREFIX='cards.zones.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Zone content differs from its reviewed source pin')
    return data


def stored_target(c):
    e=c.state.entities.get(c.target_id)
    return e if e is not None and e.zone==Zone.HAND and e.controller==c.player_id else None


def invoke(c,name):
    return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id)


def selected_hand(c,operation):
    e=stored_target(c)
    if e is None:return ()
    ref=CardReference.capture(e)
    if operation=='copy':return (CopyCard(ref,c.player_id,source_id=c.source_id),)
    if operation=='shuffle':return shuffled(c,(MoveCard(ref,c.player_id,Zone.DECK,'random',source_id=c.source_id),))
    if operation=='discard':return (DiscardCard(ref,c.source_id),)
    return (BuffStoredCard(ref,2,2,c.source_id),)


def hand_shuffle_draw(c,r):
    return (*selected_hand(c,'shuffle'),Draw(c.player_id,1,c.source_id))


def leftmost_hand_shuffle(c,r):
    hand=c.state.players[c.player_id].hand
    return () if not hand else shuffled(c,(MoveCard(CardReference.capture(c.state.entities[hand[0]]),
        c.player_id,Zone.DECK,'random',source_id=c.source_id),))


def stored_buffs(c,zones,amount,first=None):
    cards=[c.state.entities[eid] for zone in zones for eid in getattr(c.state.players[c.player_id],zone.value)
           if c.state.entities[eid].kind==CardType.MINION]
    if first is not None:cards=cards[:first]
    return tuple(BuffStoredCard(CardReference.capture(e),amount,amount,c.source_id) for e in cards)


def kindred_copy(c,r):
    match=query_previous_owner_turn(c.state,c.player_id,query_for_definition(r.card(c.source.card_id)))
    return (CopyMinion(c.source_id,c.player_id),) if match.matched else ()


def original_minion_result(c):
    result=c.health_result
    return result if result is not None and result.target_kind==CardType.MINION.value and (
        result.original_target_id==result.target_id and result.health_before>0 and not result.doomed_before) else None


def killed_followup(c,r,copy=False):
    result=original_minion_result(c)
    if result is None or result.flow!='damage' or not (result.health_after<=0 or result.doomed_after):return ()
    return (card_summon(c,c.player_id,result.target_card_id),) if copy else (Draw(c.player_id,1,c.source_id),)


def survived_draw(c,r):
    result=original_minion_result(c)
    return (Draw(c.player_id,1,c.source_id),) if result is not None and result.health_after>0 and not result.doomed_after else ()


def enemy_top(c,destroy=False,count=1):
    deck=c.state.players[3-c.player_id].deck
    refs=tuple(CardReference.capture(c.state.entities[e]) for e in deck[:count])
    return tuple(DestroyDeckCard(ref,c.source_id) for ref in refs) if destroy else (
        () if not refs else (RemoveFromGame(refs,c.source_id),))


SCRIPTS={
 'enemy_deck_copy':lambda c,r:(CopyMatching(c.player_id,3-c.player_id,Zone.DECK,source_id=c.source_id),),
 'lowest_enemy_hand_copy':lambda c,r:(CopyMatching(c.player_id,3-c.player_id,Zone.HAND,
     selection='lowest_cost',source_id=c.source_id),),
 'own_tribal_hand_copy':lambda c,r:(CopyMatching(c.player_id,c.player_id,Zone.HAND,
     PoolQuery(kinds=(CardType.MINION,),tribes_any=('elemental','dragon')),source_id=c.source_id),),
 'selected_hand_copy':lambda c,r:selected_hand(c,'copy'),
 'selected_hand_shuffle_draw':hand_shuffle_draw,
 'selected_hand_discard':lambda c,r:selected_hand(c,'discard'),
 'selected_hand_buff':lambda c,r:selected_hand(c,'buff'),
 'leftmost_hand_shuffle':leftmost_hand_shuffle,
 'draw_two':lambda c,r:(Draw(c.player_id,2,c.source_id),),
 'corpse_end_copy':lambda c,r:(SpendResource(c.player_id,Resource.CORPSES,4,
     on_success=(CopyMinion(c.source_id,c.player_id),)),),
 'pupil':lambda c,r:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL,on_result=PREFIX+'killed_copy'),),
 'coil':lambda c,r:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL,on_result=PREFIX+'killed_draw'),),
 'slam':lambda c,r:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL,on_result=PREFIX+'survived_draw'),),
 'killed_copy':lambda c,r:killed_followup(c,r,True),
 'killed_draw':killed_followup,
 'survived_draw':survived_draw,
 'enemy_top_remove':lambda c,r:enemy_top(c),
 'top_three_minion_buff':lambda c,r:stored_buffs(c,(Zone.DECK,),4,3),
 'attack_four_copy':lambda c,r:(CopyMinion(c.source_id,c.player_id),) if c.source.attack>=4 else (),
 'kindred_copy':kindred_copy,
 'all_stored_minion_buff':lambda c,r:stored_buffs(c,(Zone.HAND,Zone.DECK),3),
 'self_attack_hand_buff':lambda c,r:stored_buffs(c,(Zone.HAND,),1) if c.event.source_id==c.source_id else (),
 'empty_deck_enemy_top_destroy':lambda c,r:enemy_top(c,True,5) if not c.state.players[c.player_id].deck else (),
}


def register_zone_cards(registry):
    for name,handler in SCRIPTS.items():
        registry.register_behavior(PREFIX+name,lambda c,handler=handler:handler(c,registry))
    def hand_target(c,fel=False):
        if c.target is None or c.source['ref']==c.target['ref']:return False
        return not fel or registry.card(c.target['card_id']).spell_school==SpellSchool.FEL
    registry.register_target_rule(PREFIX+'hand',lambda c:hand_target(c),visibility='player')
    registry.register_target_rule(PREFIX+'hand_fel',lambda c:hand_target(c,True),visibility='player')
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Zone card record changed')
        script=recipe['script'];entry=recipe['entry'];kind=CardType(raw['type'].lower())
        if script not in SCRIPTS:raise TargetValidationError('Unknown zone card script')
        kwargs={}
        if entry=='on_trigger':
            trigger=recipe['trigger']
            if trigger not in ('own_turn_end','self_attack'):raise TargetValidationError('Unreviewed zone trigger')
            kwargs['triggers']=(TriggerSpec('turn_ended' if trigger=='own_turn_end' else 'attack_declared',
                PREFIX+script,EndTurnSpec() if trigger=='own_turn_end' else None),)
        elif entry in ('on_play','battlecry','deathrattle','on_use'):kwargs[entry]=PREFIX+script
        else:raise TargetValidationError('Unreviewed zone body entry')
        if recipe['deathrattle'] is not None:
            if recipe['deathrattle'] not in SCRIPTS:raise TargetValidationError('Unknown zone deathrattle')
            kwargs['deathrattle']=PREFIX+recipe['deathrattle']
        target=recipe['target']
        if target is not None:
            if target not in ('hand_any','hand_minion','hand_fel','board_minion'):
                raise TargetValidationError('Unreviewed zone target domain')
            hand=target.startswith('hand_')
            kinds=(CardType.SPELL,) if target=='hand_fel' else (CardType.MINION,) if target!='hand_any' else (
                CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO)
            kwargs['targeting']=TargetSpec(TargetMode.IF_AVAILABLE if kind==CardType.MINION else TargetMode.REQUIRED,
                zones=(Zone.HAND,) if hand else (Zone.BOARD,),kinds=kinds,relation='friendly' if hand else 'any')
            if hand:kwargs['target_rule']=PREFIX+'hand_fel' if target=='hand_fel' else PREFIX+'hand'
        cost=raw['cost'];school=raw['tags'].get('SPELL_SCHOOL')
        if type(cost) is not int or cost<0:raise TargetValidationError('Unreviewed zone printed cost')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unreviewed zone spell school')
        definition=CardDefinition(raw['id'],raw['name'],kind,cost=cost,attack=raw['attack'] or 0,
            health=raw['health'] if kind==CardType.MINION else 0,
            durability=raw['health'] if kind in (CardType.WEAPON,CardType.LOCATION) else 0,
            keywords=tuple(Keyword(k) for k in recipe['keywords']),spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
