"""Independent current-turn control; exact CN timing remains a local policy."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, EndTurn,
    Game, IllegalAction, Keyword, PlayCard, PlayerSetup, PlayerTargetRuleSpec,
    Rarity, Registry, ResolutionError, Scenario, SelectChoice, SnapshotError,
    SpellSchool, TargetMode, TargetSpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.dormancy import MakeDormant
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion,
    Destroy, GainArmor, GrantKeyword, InvokeBehavior, RemoveEnchantment,
    RequestChoice, ReturnToHand, ShuffleIntoDeck, Silence, Summon, Transform)
from hs_sim.engine.model import Enchantment, TriggerSpec
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from opening_fixtures import metadata
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SHADOW='EX1_334'
PATH=Path(__file__).resolve().parents[1]/'data/support/temporary-control-basics.json'
PIN='a5abd408f5794d51bdd4ee36b41af25e22c5a6a42a2f48a649bf0aaf238bac42'
ENEMY=TargetSpec(TargetMode.REQUIRED,(Zone.BOARD,),(CardType.MINION,),'enemy')

def evidence():
    support=json.loads(PATH.read_text(encoding='utf-8'))
    if canonical_digest(support)!=PIN:raise ValueError('Temporary control evidence changed')
    for row in support['records']:
        if canonical_digest(row['data'])!=row['data_sha256']:raise ValueError('Raw evidence changed')
    return support['records'][0]['data']

def registry():
    r=Registry('isolated-temporary-control-basics-v1');raw=evidence()
    r.register_card(CardDefinition('hero','Hero',CardType.HERO,health=80,metadata=metadata()))
    for cid,attack in (('plain',2),('high',4),('face',1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=attack,health=5,metadata=metadata()))
    def target(c):
        board=next(p['board'] for p in c.observation['players'] if p['id']==c.player_id)
        return (c.target is not None and c.target['attack']<=3 and
            len(board)<c.observation['limits']['max_board'])
    r.register_player_target_rule(PlayerTargetRuleSpec('shadow-target','v1'),target)
    def after_control(c):
        entity=c.state.entities[c.target_id]
        return (GrantKeyword(entity.id,Keyword.CHARGE,source_id=c.source_id,expires_turn=c.state.turn),) if (
            entity.zone==Zone.BOARD and entity.active and entity.controller==c.player_id) else ()
    r.register_behavior('shadow-charge',after_control)
    r.register_behavior('shadow',lambda c:(
        ChangeControl(c.target_id,c.player_id,until_end_of_turn=True,source_id=c.source_id),
        InvokeBehavior('shadow-charge',source_id=c.source_id,player_id=c.player_id,target_id=c.target_id)))
    r.register_card(CardDefinition(SHADOW,raw['name'],CardType.SPELL,cost=raw['cost'],on_play='shadow',
        targeting=ENEMY,target_rule='shadow-target',spell_school=SpellSchool.SHADOW,
        metadata=metadata(CardClass.PRIEST,rarity=Rarity.RARE)))
    def fail(c):raise ValueError('Fixture late failure')
    r.register_behavior('late-fault',fail)
    def end(c):
        return (GainArmor(c.player_id,2),) if c.event.player_id==c.player_id else ()
    def wait(c):
        if c.event.player_id!=c.player_id:return ()
        return (RequestChoice(c.player_id,(
            ChoiceOption('ok','Continue',(GainArmor(c.player_id,2),)),
            ChoiceOption('fault','Fail',(InvokeBehavior('late-fault',source_id=c.source_id,player_id=c.player_id),)),
        ),c.source_id),)
    r.register_behavior('observe-end',end);r.register_behavior('wait-end',wait)
    for cid,body in (('observer','observe-end'),('waiting','wait-end')):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=2,health=5,
            triggers=(TriggerSpec('turn_ended',body),),metadata=metadata()))
    targeted={
        'silence':lambda c:(Silence(c.target_id),),
        'destroy':lambda c:(Destroy(c.target_id,c.source_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'shuffle':lambda c:(ShuffleIntoDeck(c.target_id),),
        'transform':lambda c:(Transform(c.target_id,'face'),),
        'copy':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'base-copy':lambda c:(CopyMinion(c.target_id,c.player_id,mode='base'),),
        'permanent':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'to-other':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'temporary':lambda c:(ChangeControl(c.target_id,c.player_id,True,c.source_id),),
        'buff':lambda c:(Buff(c.target_id,1,1,source_id=c.source_id),),
        'remove-control':lambda c:tuple(RemoveEnchantment(c.target_id,e.id) for e in
            c.state.entities[c.target_id].enchantments if e.control_return_player_id is not None),
        'remove-buff':lambda c:tuple(RemoveEnchantment(c.target_id,e.id) for e in
            c.state.entities[c.target_id].enchantments if e.control_return_player_id is None),
        'sleep':lambda c:(MakeDormant(c.target_id,None),),
        'fault':lambda c:(ChangeControl(c.target_id,c.player_id,True,c.source_id),
            InvokeBehavior('late-fault',source_id=c.source_id,player_id=c.player_id)),
        'unknown-source':lambda c:(ChangeControl(c.target_id,c.player_id,True,999999),),
        'stale-control':lambda c:(ChangeControl(999999,c.player_id,True,c.source_id),),
    }
    scripts={'fill':lambda c:tuple(Summon(2,'plain') for _ in range(7))}
    for name,body in {**targeted,**scripts}.items():
        r.register_behavior(name,body)
        r.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name,
            requires_target=name in targeted,metadata=metadata()))
    return r

class TemporaryControlBasicsTests(unittest.TestCase):
    def game(self,hand=(SHADOW,),board=(),enemy=('plain',),enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero',hand=hand,board=board,deck=('plain',)*4,mana=10,max_mana=10),
            PlayerSetup('hero',hand=enemy_hand,board=enemy,deck=('plain',)*4,mana=10,max_mana=10),
        ),seed=40),registry())
    def target(self,g):return g.state.players[2].board[0]
    def play(self,g,cid=SHADOW,target=None):
        p=g.state.active_player;eid=next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid
    def borrow(self,g):
        target=self.target(g);source=self.play(g,target=target);return target,source
    def controls(self,g,target):return [e for e in g.state.entities[target].enchantments if e.control_return_player_id is not None]
    def end(self,g):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key='ok'):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))
    def roundtrip(self,g):
        snap=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snap,registry()).snapshot(),snap)
        self.assertEqual(g.clone().snapshot(),snap)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),snap)
    def rehash(self,snap):
        snap['state_hash']=canonical_hash({k:v for k,v in snap.items() if k not in ('schema_version','events','events_hash','state_hash')});return snap

    def test_raw_pin_native_spell_and_enchantment_evidence(self):
        raw=evidence();self.assertEqual((raw['id'],raw['dbf_id'],raw['cost']),(SHADOW,220,3))
        self.assertIn('3 or less Attack until end of turn',raw['text_en'])
        self.assertEqual((raw['tags']['CLASS'],raw['tags']['RARITY'],raw['tags']['SPELL_SCHOOL']),(6,3,6))
        self.assertEqual(registry().card(SHADOW).spell_school,SpellSchool.SHADOW)
        extra=json.loads(PATH.read_text(encoding='utf-8'))['records'][1]['data']
        self.assertEqual(extra['id'],'EX1_334e');self.assertNotIn('CHARGE',extra['tags'])

    def test_effect_defaults_preserve_permanent_operation_and_require_typed_source(self):
        self.assertEqual(ChangeControl(1,2),ChangeControl(1,2,False,None))
        for fields in ({'until_end_of_turn':1},{'until_end_of_turn':True},
            {'until_end_of_turn':True,'source_id':True},{'until_end_of_turn':True,'source_id':0},
            {'source_id':3}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):ChangeControl(1,2,**fields)

    def test_control_marker_is_separate_immutable_typed_timed_and_removable(self):
        e=Enchantment(1,source_id=2,expires_turn=1,label='temporary_control',control_return_player_id=2)
        self.assertIsNone(Enchantment(2).control_return_player_id)
        with self.assertRaises(FrozenInstanceError):e.control_return_player_id=1
        for fields in ({'control_return_player_id':True},{'control_return_player_id':3},
            {'control_return_player_id':None},{'source_id':None},{'expires_turn':None},
            {'remove_on_silence':False},{'attack':1},{'health':1},{'cost':1},
            {'set_attack':0},{'label':'buff'},{'magnetic_id':3}):
            with self.subTest(fields=fields),self.assertRaises(ValueError):replace(e,**fields)

    def test_current_attack_and_enemy_domain_define_legal_targets(self):
        g=self.game(board=('plain',),enemy=('plain','high'));target=self.target(g)
        actions=[a for a in g.legal_actions() if type(a) is PlayCard]
        self.assertEqual({a.target_id for a in actions},{target})
        before=g.snapshot()
        for bad in (g.state.players[1].board[0],g.state.players[2].board[1],g.state.players[2].hero_id):
            with self.assertRaises(IllegalAction):self.play(g,target=bad)
            self.assertEqual(g.snapshot(),before)

    def test_attack_modified_before_cast_uses_current_value(self):
        g=self.game(hand=('buff',SHADOW));target=self.target(g);self.play(g,'buff',target)
        self.assertEqual(g.state.entities[target].attack,3);self.play(g,target=target)
        self.assertEqual(g.state.entities[target].controller,1)

    def test_full_destination_excludes_cast_and_preserves_payment(self):
        g=self.game(board=('plain',)*7);before=g.snapshot()
        self.assertFalse(any(type(a) is PlayCard for a in g.legal_actions()))
        with self.assertRaises(IllegalAction):self.play(g,target=self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_native_paid_cast_moves_same_entity_and_records_actual_previous_controller(self):
        g=self.game(board=('plain',));target=self.target(g);entity=g.state.entities[target]
        owner,presence,epoch=entity.owner,entity.board_presence_id,entity.zone_epoch
        target,source=self.borrow(g);entity=g.state.entities[target];e=self.controls(g,target)[0]
        self.assertEqual((entity.owner,entity.board_presence_id,entity.zone_epoch),(owner,presence,epoch))
        self.assertEqual((entity.controller,e.control_return_player_id,e.source_id,e.expires_turn),(1,2,source,g.state.turn))
        self.assertEqual(g.state.players[1].board[-1],target);self.assertNotIn(target,g.state.players[2].board)
        self.assertEqual(g.state.players[1].mana,7);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)

    def test_native_charge_allows_attack_on_borrow_turn(self):
        g=self.game();target,_=self.borrow(g);hero=g.state.players[2].hero_id
        self.assertIn(Keyword.CHARGE,g.state.entities[target].keywords)
        g.apply(Attack(1,target,hero));self.assertEqual(g.state.entities[hero].health,78)

    def test_used_attack_count_is_not_reset_by_transfer(self):
        g=self.game(hand=(SHADOW,'remove-control'));target,_=self.borrow(g)
        g.apply(Attack(1,target,g.state.players[2].hero_id));self.play(g,'remove-control',target)
        self.assertEqual(g.state.entities[target].attacks_this_turn,1)
        self.end(g)
        events=[e for e in g.events if e.kind=='control_changed']
        self.assertEqual(len(events),2);self.assertEqual(g.state.entities[target].controller,2)
        self.assertEqual(g.state.entities[target].attacks_this_turn,0)

    def test_current_turn_end_returns_and_removes_temporary_charge(self):
        g=self.game();target,_=self.borrow(g);self.end(g);entity=g.state.entities[target]
        self.assertEqual(entity.controller,2);self.assertEqual(self.controls(g,target),[])
        self.assertNotIn(Keyword.CHARGE,entity.keywords);self.assertEqual(g.state.active_player,2)

    def test_previous_controller_rather_than_original_owner_is_restored(self):
        g=self.game(hand=('to-other',SHADOW),board=('plain',),enemy=())
        target=g.state.players[1].board[0];self.play(g,'to-other',target);self.play(g,target=target);self.end(g)
        self.assertEqual((g.state.entities[target].owner,g.state.entities[target].controller),(1,2))

    def test_end_trigger_observes_borrowing_controller_before_return(self):
        g=self.game(enemy=('observer',));target,_=self.borrow(g);self.end(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,2)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor,0)
        self.assertEqual(g.state.entities[target].controller,2)
        return_event=next(e for e in g.events if e.kind=='control_changed' and e.player_id==2)
        gain=next(e for e in g.events if e.kind=='armor_gained')
        self.assertLess(gain.sequence,return_event.sequence)

    def test_source_spell_in_graveyard_does_not_disable_pending_return(self):
        g=self.game();target,source=self.borrow(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.roundtrip(g);self.end(g)
        self.assertEqual(g.state.entities[target].controller,2)

    def test_silence_immediately_removes_control_and_charge(self):
        g=self.game(hand=(SHADOW,'silence'));target,_=self.borrow(g);self.play(g,'silence',target)
        self.assertEqual(g.state.entities[target].controller,2);self.assertTrue(g.state.entities[target].silenced)
        self.assertEqual(self.controls(g,target),[]);self.assertNotIn(Keyword.CHARGE,g.state.entities[target].keywords)
        self.end(g);self.assertEqual(g.state.entities[target].controller,2)

    def test_permanent_transfer_is_not_undone_by_silence_or_expiry(self):
        g=self.game(hand=('permanent','silence'));target=self.target(g);self.play(g,'permanent',target)
        self.play(g,'silence',target);self.end(g)
        self.assertEqual(g.state.entities[target].controller,1);self.assertEqual(self.controls(g,target),[])

    def test_manual_control_removal_uses_same_return_entry(self):
        g=self.game(hand=(SHADOW,'remove-control'));target,_=self.borrow(g)
        self.play(g,'remove-control',target);self.assertEqual(g.state.entities[target].controller,2)
        self.assertEqual(self.controls(g,target),[]);self.end(g);self.assertEqual(g.state.entities[target].controller,2)

    def test_removing_unrelated_numeric_attachment_does_not_return_minion(self):
        g=self.game(hand=(SHADOW,'buff','remove-buff'));target,_=self.borrow(g)
        self.play(g,'buff',target);self.play(g,'remove-buff',target)
        self.assertEqual(g.state.entities[target].controller,1);self.assertEqual(len(self.controls(g,target)),1)
        self.end(g);self.assertEqual(g.state.entities[target].controller,2)

    def test_transform_discards_old_return_and_keeps_current_controller(self):
        g=self.game(hand=(SHADOW,'transform'));target,_=self.borrow(g);self.play(g,'transform',target)
        self.assertEqual((g.state.entities[target].card_id,g.state.entities[target].controller),('face',1))
        self.assertEqual(self.controls(g,target),[]);self.end(g);self.assertEqual(g.state.entities[target].controller,1)

    def test_return_to_hand_discards_return_and_belongs_to_current_controller(self):
        g=self.game(hand=(SHADOW,'bounce'));target,_=self.borrow(g);self.play(g,'bounce',target)
        self.assertIn(target,g.state.players[1].hand);self.assertEqual(self.controls(g,target),[])
        self.end(g);self.assertIn(target,g.state.players[1].hand)

    def test_shuffle_into_deck_discards_return_without_reacquiring_old_entity(self):
        g=self.game(hand=(SHADOW,'shuffle'));target,_=self.borrow(g);self.play(g,'shuffle',target)
        self.assertIn(target,g.state.players[1].deck);self.assertEqual(self.controls(g,target),[])
        self.end(g);self.assertIn(target,g.state.players[1].deck)

    def test_death_during_borrow_does_not_return_or_resurrect(self):
        g=self.game(hand=(SHADOW,'destroy'));target,_=self.borrow(g);self.play(g,'destroy',target)
        record=next(r for r in g.state.death_history if r.entity_id==target)
        self.assertEqual(record.controller,1)
        self.assertEqual(next(e.control_return_player_id for e in record.enchantments if e.control_return_player_id is not None),2)
        self.end(g);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertNotIn(target,g.state.players[2].board)

    def test_copy_current_does_not_copy_physical_return_but_copies_charge(self):
        g=self.game(hand=(SHADOW,'copy'));target,_=self.borrow(g);self.play(g,'copy',target)
        copied=next(i for i in g.state.players[1].board if i!=target)
        self.assertEqual(self.controls(g,copied),[]);self.assertIn(Keyword.CHARGE,g.state.entities[copied].keywords)
        self.end(g);self.assertEqual(g.state.entities[copied].controller,1)
        self.assertEqual(g.state.entities[target].controller,2);self.assertNotIn(Keyword.CHARGE,g.state.entities[copied].keywords)

    def test_copy_base_has_no_return_or_granted_charge(self):
        g=self.game(hand=(SHADOW,'base-copy'));target,_=self.borrow(g);self.play(g,'base-copy',target)
        copied=next(i for i in g.state.players[1].board if i!=target)
        self.assertEqual(self.controls(g,copied),[]);self.assertNotIn(Keyword.CHARGE,g.state.entities[copied].keywords)
        self.end(g);self.assertEqual(g.state.entities[copied].controller,1)

    def test_full_return_board_destroys_through_original_death_checkpoint(self):
        g=self.game(hand=(SHADOW,'fill'));target,_=self.borrow(g);self.play(g,'fill');self.end(g)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        record=next(r for r in g.state.death_history if r.entity_id==target)
        self.assertEqual(record.controller,1);self.assertEqual(len(g.state.players[2].board),7)

    def test_full_return_board_on_silence_uses_same_death_policy(self):
        g=self.game(hand=(SHADOW,'fill','silence'));target,_=self.borrow(g);self.play(g,'fill');self.play(g,'silence',target)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
        self.assertEqual(next(r.controller for r in g.state.death_history if r.entity_id==target),1)

    def test_dormant_resident_is_returned_without_active_target_selection(self):
        g=self.game(hand=(SHADOW,'sleep'));target,_=self.borrow(g);self.play(g,'sleep',target);self.end(g)
        self.assertIsNotNone(g.state.entities[target].dormancy);self.assertEqual(g.state.entities[target].controller,2)
        self.assertEqual(self.controls(g,target),[])

    def test_dormant_full_return_board_explicitly_rejects_unimplemented_death_policy(self):
        g=self.game(hand=(SHADOW,'sleep','fill'));target,_=self.borrow(g)
        self.play(g,'sleep',target);self.play(g,'fill');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'Dormant full-board'):self.end(g)
        self.assertEqual(g.snapshot(),before)

    def test_failed_initial_physical_transfer_adds_no_return_layer(self):
        g=self.game(hand=('temporary',),board=('plain',)*7);target=self.target(g);self.play(g,'temporary',target)
        self.assertEqual(g.state.entities[target].controller,2);self.assertEqual(self.controls(g,target),[])
        self.assertTrue(any(e.kind=='control_change_failed' for e in g.events))

    def test_same_controller_noop_adds_no_control_layer(self):
        g=self.game(hand=('temporary',),board=('plain',),enemy=());target=g.state.players[1].board[0]
        self.play(g,'temporary',target);self.assertEqual(self.controls(g,target),[])

    def test_unknown_source_rolls_back_whole_operation(self):
        g=self.game(hand=('unknown-source',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'unknown-source',self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_stale_target_emits_original_stale_effect_without_control(self):
        g=self.game(hand=('stale-control',));self.play(g,'stale-control',self.target(g))
        self.assertEqual(len(g.state.players[1].board),0);self.assertEqual(len(g.state.players[2].board),1)
        self.assertTrue(any(e.kind=='effect_skipped' for e in g.events))

    def test_immediate_failure_after_transfer_rolls_back_state_events_and_payment(self):
        g=self.game(hand=('fault',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'fault',self.target(g))
        self.assertEqual(g.snapshot(),before)

    def test_end_choice_preserves_lease_then_recovers_clones_and_replays(self):
        g=self.game(enemy=('waiting',));target,_=self.borrow(g);self.end(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.entities[target].controller,1)
        self.roundtrip(g);restored=Game.from_snapshot(g.snapshot(),registry());self.choose(g);self.choose(restored)
        self.assertEqual(restored.snapshot(),g.snapshot());self.assertEqual(g.state.entities[target].controller,2)
        self.roundtrip(g)

    def test_failed_end_choice_rolls_back_to_original_waiting_point(self):
        g=self.game(enemy=('waiting',));target,_=self.borrow(g);self.end(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fault')
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.entities[target].controller,1)
        self.choose(g);self.assertEqual(g.state.entities[target].controller,2)

    def test_player_projection_shows_control_but_not_internal_return_or_attachments(self):
        g=self.game();target,_=self.borrow(g);before=g.snapshot()
        for p in (1,2):
            text=json.dumps(g.for_player(p).observe(),sort_keys=True)
            for hidden in ('control_return_player_id','temporary_control','enchantments','source_json','rng_state'):
                self.assertNotIn(hidden,text)
            g.for_player(p).legal_actions()
        self.assertEqual(g.snapshot(),before)
        self.assertEqual(g.observe(1)['players'][0]['board'][0]['controller'],1)

    def test_required_control_field_and_impure_marker_rejected_after_rehash(self):
        g=self.game();target,_=self.borrow(g)
        for key,value,delete in (('control_return_player_id',None,True),('control_return_player_id',True,False),
            ('control_return_player_id',3,False),('attack',1,False),('expires_turn',None,False)):
            snap=deepcopy(g.snapshot());row=snap['state']['entities'][str(target)]['enchantments'][0]
            if delete:row.pop(key)
            else:row[key]=value
            with self.subTest(key=key,value=value,delete=delete),self.assertRaises(SnapshotError):
                Game.from_snapshot(self.rehash(snap),registry())

    def test_control_marker_cannot_be_carried_by_hero(self):
        g=self.game();target,_=self.borrow(g);snap=g.snapshot()
        row=snap['state']['entities'][str(target)];hero=snap['state']['entities'][str(g.state.players[1].hero_id)]
        hero['enchantments']=row['enchantments'];row['enchantments']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())

    def test_control_marker_cannot_move_to_stored_card_or_future_turn(self):
        g=self.game(hand=(SHADOW,'plain'));target,_=self.borrow(g)
        snap=g.snapshot();row=snap['state']['entities'][str(target)]
        held=snap['state']['entities'][str(g.state.players[1].hand[0])]
        held['enchantments']=row['enchantments'];row['enchantments']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())
        snap=g.snapshot();snap['state']['entities'][str(target)]['enchantments'][0]['expires_turn']=g.state.turn+1
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(snap),registry())

    def test_frame_codec_roundtrips_effect_and_marker_and_rejects_missing_field(self):
        g=self.game();codec=FrameCodec(g.mechanics,g.registry)
        for value in (ChangeControl(self.target(g),1,True,g.state.players[1].hand[0]),
            Enchantment(1,source_id=g.state.players[1].hand[0],expires_turn=g.state.turn,label='temporary_control',control_return_player_id=2)):
            encoded=codec.encode(value);self.assertEqual(codec.decode(encoded),value)
        encoded=codec.encode(value);encoded['fields'].pop('control_return_player_id')
        with self.assertRaises(ValueError):codec.decode(encoded)

    def test_all_previous_schemas_nonintegers_and_future_schema_rejected(self):
        g=self.game();snap=g.snapshot();self.assertEqual(snap['schema_version'],265)
        self.assertEqual(snap['ruleset']['id'],'prototype-v302')
        self.assertEqual(snap['mechanics_version']['version'],CORE_EFFECTS_VERSION)
        for schema in (*range(1,218),None,True,188.0,'188',217):
            bad=deepcopy(snap);bad['schema_version']=schema
            with self.subTest(schema=schema),self.assertRaises(SnapshotError):Game.from_snapshot(bad,registry())
