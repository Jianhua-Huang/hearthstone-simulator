"""Actual public paid roots and their original source-role restoration limits.

No private label assertions, no simulator modification, no fixture file writes.
PROBE_RECORDS is an optional runner-owned capture sink, empty by default.
"""
from copy import deepcopy
import unittest
from hs_sim.engine import (AddBattlecryRepeatModifier, AddComboRepeatModifier,
    BattlecryRepeatSpec, ComboRepeatSpec, CardDefinition, CardType, Game,
    GrantBattlecryRepeatAura, GrantComboRepeatAura, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Registry, RemoveBattlecryRepeatModifier,
    RemoveComboRepeatModifier, Scenario, SelectChoice, SnapshotError)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Silence
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash

PROBE_RECORDS=None
PAID='hs_sim.engine.paid_hand_acceptance.FinishPaidHandAcceptance'


def registry():
    result=Registry('role-boundary-probe-v118')
    result.register_card(CardDefinition('role.hero','Hero',CardType.HERO,health=30))
    result.register_card(CardDefinition('role.blank','Blank',CardType.MINION,health=3))
    result.register_behavior('role.prime',lambda c:[])
    result.register_card(CardDefinition('role.prime','Prime',CardType.SPELL,on_play='role.prime'))
    def ask(context):
        return [RequestChoice(context.player_id,(ChoiceOption('ok','Continue',
            (GainArmor(context.player_id,1),)),),source_id=context.source_id)]
    result.register_behavior('role.ask',ask)
    for family,spec,add,remove,grant,keyword in (
            ('battlecry',BattlecryRepeatSpec,AddBattlecryRepeatModifier,
                RemoveBattlecryRepeatModifier,GrantBattlecryRepeatAura,None),
            ('combo',ComboRepeatSpec,AddComboRepeatModifier,
                RemoveComboRepeatModifier,GrantComboRepeatAura,Keyword.COMBO)):
        result.register_card(CardDefinition('role.'+family+'.donor','Donor',CardType.MINION,
            health=3,**{family+'_repeats':(spec(),)}))
        result.register_card(CardDefinition('role.'+family+'.child','Child',CardType.MINION,
            cost=1,health=2,keywords=(() if keyword is None else (keyword,)),**{family:'role.ask'}))
        def make_grant(effect,specification):
            def behavior(c):return [effect(player,specification(),c.source_id,uses=None)
                for player in (1,2)]
            return behavior
        def make_remove(effect,kind):
            def behavior(c):return [effect(c.player_id,
                getattr(c.state.players[c.player_id],kind+'_modifiers')[0].id)]
            return behavior
        def make_aura(effect,specification):
            def behavior(c):return [effect(c.state.players[c.player_id].board[0],
                specification(),source_id=c.source_id)]
            return behavior
        for suffix,behavior in (('grant',make_grant(add,spec)),
                ('remove',make_remove(remove,family)),('aura',make_aura(grant,spec))):
            name='role.'+family+'.'+suffix
            result.register_behavior(name,behavior)
            result.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    def erase(c):return [Silence(c.state.players[c.player_id].board[0])]
    result.register_behavior('role.erase',erase)
    result.register_card(CardDefinition('role.erase','Erase',CardType.SPELL,on_play='role.erase'))
    return result


def play(game,card):
    source=next(i for i in game.state.players[1].hand if game.state.entities[i].card_id==card)
    game.apply(PlayCard(1,source))


def finish_choices(game):
    while game.state.pending_choice is not None:
        pending=game.state.pending_choice
        game.apply(SelectChoice(pending.player_id,pending.id,('ok',)))


def rehash(snapshot):
    frame=snapshot['resolution_frame']
    if frame is not None:
        proof=frame['fields']['paid_hand_choice_boundary']
        event=proof['fields']['event']['event']
        snapshot['events'][event['sequence']-1]['data']['_paid_hand_choice_boundary']=canonical_hash(proof)
    snapshot['events_hash']=canonical_hash(snapshot['events'])
    snapshot['state_hash']=canonical_hash({key:value for key,value in snapshot.items()
        if key not in ('schema_version','events','events_hash','state_hash')})
    return snapshot


def forge_plan(snapshot,old_id,new_id,*,make_finite=False):
    """Coordinate live/accepted plan copies while preserving original pay tail."""
    result=deepcopy(snapshot)
    def walk(value):
        if isinstance(value,dict):
            if value.get('type')==PAID:return
            if set(value)=={'repetitions','contributors','consumable_ids'}:
                typed=isinstance(value['contributors'],dict)
                contributors=value['contributors']['tuple'] if typed else value['contributors']
                consumables=value['consumable_ids']['tuple'] if typed else value['consumable_ids']
                if old_id in contributors:
                    contributors[:]=[new_id if identity==old_id else identity for identity in contributors]
                    consumables[:]=[new_id if identity==old_id else identity for identity in consumables]
                    if make_finite and new_id not in consumables:consumables.append(new_id);consumables.sort()
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(result)
    return result


def forge_physical_id(snapshot,old_id,new_id,family,physical):
    """Retain genuine original payment states, rewrite only later actual views."""
    result=forge_plan(snapshot,old_id,new_id)
    def walk(value):
        if isinstance(value,dict):
            if value.get('type')==PAID:return
            if 'entities' in value and 'players' in value and 'play_history' in value:
                items=(value['players']['1'][family+'_modifiers'] if physical=='player' else
                    [a for entity in value['entities'].values() for a in entity['abilities']])
                for item in items:
                    if item['id']==old_id:item['id']=new_id
            for child in value.values():walk(child)
        elif isinstance(value,list):
            for child in value:walk(child)
    walk(result)
    return rehash(result)


class IdOnlyRepeatRoleTests(unittest.TestCase):
    def game(self,family,hand,board):
        return Game.from_scenario(Scenario((
            PlayerSetup('role.hero',hand=tuple(hand),board=tuple(board),mana=10,max_mana=10),
            PlayerSetup('role.hero')),seed=118),registry())

    def portable(self,game):
        saved=game.snapshot()
        self.assertIsNotNone(game.state.pending_choice)
        branches=(Game.from_snapshot(saved,registry()),game.clone(),replay(build_replay(game),registry()))
        for branch in branches:self.assertEqual(branch.snapshot(),saved)
        pending=game.state.pending_choice
        with self.assertRaises(IllegalAction):game.apply(SelectChoice(pending.player_id,pending.id+100,('ok',)))
        self.assertEqual(game.snapshot(),saved)
        if PROBE_RECORDS is not None:
            PROBE_RECORDS.append({'label':'actual-original-wait','original':saved,
                'actual_replay':build_replay(game)})
        return saved

    def reject(self,saved,label):
        record={'label':label,'forged':saved,'actual_restored':False}
        if PROBE_RECORDS is not None:PROBE_RECORDS.append(record)
        with self.assertRaises(SnapshotError) as caught:
            Game.from_snapshot(saved,registry())
            record['actual_restored']=True
        record['actual_rejection_type']=type(caught.exception).__name__
        record['actual_rejection_message']=str(caught.exception)

    def test_gone_board_id_cannot_return_as_unlimited_player_policy(self):
        family='battlecry';child='role.'+family+'.child'
        game=self.game(family,(child,'role.erase','role.'+family+'.grant',child),('role.'+family+'.donor',))
        donor=game.state.players[1].board[0]
        old=next(a.id for a in game.state.entities[donor].abilities if a.kind==family+'_repeat')
        play(game,child);finish_choices(game);play(game,'role.erase')
        self.assertFalse(any(a.id==old for entity in game.state.entities.values() for a in entity.abilities))
        play(game,'role.'+family+'.grant')
        new=getattr(game.state.players[1],family+'_modifiers')[0].id
        self.assertNotEqual(old,new)
        play(game,child);saved=self.portable(game)
        forged=forge_physical_id(saved,new,old,family,'player')
        self.reject(forged,'gone-board-to-unlimited-player')

    def test_gone_player_id_cannot_return_as_same_family_board_ability(self):
        family='combo';child='role.'+family+'.child'
        game=self.game(family,('role.'+family+'.grant',child,'role.'+family+'.remove',
            'role.'+family+'.aura',child),('role.blank',))
        play(game,'role.'+family+'.grant')
        old=getattr(game.state.players[1],family+'_modifiers')[0].id
        play(game,child);finish_choices(game);play(game,'role.'+family+'.remove')
        self.assertFalse(getattr(game.state.players[1],family+'_modifiers'))
        play(game,'role.'+family+'.aura')
        new=next(a.id for a in game.state.entities[game.state.players[1].board[0]].abilities if a.kind==family+'_repeat')
        self.assertNotEqual(old,new)
        play(game,child);saved=self.portable(game)
        self.reject(forge_physical_id(saved,new,old,family,'board'),'gone-player-to-board')

    def test_unlimited_source_cannot_be_forged_as_finite_in_original_wait(self):
        for family in ('battlecry','combo'):
            with self.subTest(family=family):
                child='role.'+family+'.child'
                game=self.game(family,('role.'+family+'.grant',child),())
                play(game,'role.'+family+'.grant')
                identity=getattr(game.state.players[1],family+'_modifiers')[0].id
                play(game,child);saved=self.portable(game)
                forged=forge_plan(saved,identity,identity,make_finite=True)
                self.reject(rehash(forged),family+'-unlimited-as-finite')

    def test_enemy_unlimited_policy_cannot_replace_own_original_plan_source(self):
        for family in ('battlecry','combo'):
            with self.subTest(family=family):
                child='role.'+family+'.child'
                game=self.game(family,('role.'+family+'.grant',child),())
                play(game,'role.'+family+'.grant')
                own=getattr(game.state.players[1],family+'_modifiers')[0].id
                enemy=getattr(game.state.players[2],family+'_modifiers')[0].id
                self.assertNotEqual(own,enemy)
                play(game,child);saved=self.portable(game)
                self.reject(rehash(forge_plan(saved,own,enemy)),family+'-borrow-enemy-source')
