"""Unshackle Soul: real paid entry, physical copy credit, and held condition."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_held_opponent_copy_cards import CARD, load_batch, register_native_held_opponent_copy_cards
from hs_sim.cards.native_opponent_deck_fill_cards import CARD as ASHAMANE, register_native_opponent_deck_fill_cards
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup,
    Registry, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.costs import quote_generated_cost, quote_unselected_cost
from hs_sim.engine.counter_policies import GrantCounterPolicy
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, CopyMinion,
    Draw, GainArmor, InvokeBehavior, RandomDamage, RequestChoice, ReturnToHand, Transform)
from hs_sim.engine.errors import IllegalAction, ResolutionError, SnapshotError
from hs_sim.engine.held_opponent_copies import ability
from hs_sim.engine.model import (CardClass, CardMetadata, CostAuraSpec, CostSpec,
    CounterPolicySpec, Keyword, LimitedTriggerSpec, RewindSpec, ShatterSpec, SpellSchool)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastStoredSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import CopyStoredMinion
from hs_sim.engine.zones import CardReference, CopyCard, CopyMatching, ModifyStoredCost, MoveCard

P='k195.'; HERO=P+'hero'; A=P+'minion'; B=P+'spell'; C=P+'other_spell'; D=P+'other_minion'
WATCH=P+'watch'; AURA=P+'aura'; SPLIT=P+'split'; RETAIN=P+'retain'
MINION_TARGET=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))


@lru_cache(maxsize=None)
def registry(mode=None):
    r=Registry(P+str(mode));register_native_held_opponent_copy_cards(r);register_native_opponent_deck_fill_cards(r)
    priest=CardMetadata(False,(CardClass.PRIEST,),None);mage=CardMetadata(False,(CardClass.MAGE,),None)
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K195 deliberate failure')))
    def spell(c):
        if mode=='failure':return(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))
        if mode=='acquire':return(AddToHand(c.player_id,CARD,c.source_id),)
        return(GainArmor(c.player_id,1),)
    r.register_behavior(P+'spell',spell)
    r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=priest))
    r.register_card(CardDefinition(A,A,CardType.MINION,cost=1,attack=2,health=4,metadata=priest))
    r.register_card(CardDefinition(D,D,CardType.MINION,cost=2,attack=3,health=5,metadata=mage))
    fields={'keywords':(Keyword.REWIND,),'rewind':RewindSpec(1)}if mode in('rewind','retain')else{}
    r.register_card(CardDefinition(B,B,CardType.SPELL,cost=1,on_play=P+'spell',metadata=priest,**fields))
    r.register_card(CardDefinition(C,C,CardType.SPELL,cost=1,on_play=P+'noop',metadata=mage))
    r.register_card(CardDefinition(AURA,AURA,CardType.MINION,health=20,
        cost_auras=(CostAuraSpec(CostSpec(delta=2,card_types=(CardType.SPELL,))),)))
    if mode=='shatter':
        for cid in(SPLIT,SPLIT+'L',SPLIT+'R'):
            root=cid==SPLIT
            r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=P+'noop',
                keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,),
                shatter=ShatterSpec(SPLIT+'L',SPLIT+'R')if root else None))
    if mode=='retain':
        r.register_card(CardDefinition(RETAIN,RETAIN,CardType.MINION,health=20,retain_rewind_outcomes=True))
    def held(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==CARD)
    def copied(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].copy_origin is not None)
    def source(c):return c.state.entities[c.state.players[3-c.player_id].deck[0]]
    def copy_pair(c):
        ref=CardReference.capture(held(c))
        return(CopyCard(ref,c.player_id,mode='current',source_id=c.source_id),CopyCard(ref,c.player_id,mode='base',source_id=c.source_id))
    def reenter(c):
        return(MoveCard(CardReference.capture(held(c)),c.player_id,Zone.DECK,'top',source_id=c.source_id),Draw(c.player_id,source_id=c.source_id))
    def transform_copy(c):
        e=copied(c)
        return(TransformStoredCard(CardReference.capture(e),C if e.kind==CardType.SPELL else D,c.source_id),)
    def arm(c):
        e=c.state.entities[c.state.players[3-c.player_id].board[0]]
        return(GrantCounterPolicy(MinionReference.capture(e),CounterPolicySpec(CardType.SPELL),c.source_id),)
    bodies={
        'copy':lambda c:(CopyMatching(c.player_id,3-c.player_id,Zone.DECK,source_id=c.source_id),),
        'copy_own':lambda c:(CopyMatching(c.player_id,c.player_id,Zone.DECK,source_id=c.source_id),),
        'pair':copy_pair,'reenter':reenter,'change_copy':transform_copy,
        'move_source':lambda c:(MoveCard(CardReference.capture(source(c)),c.player_id,Zone.HAND,source_id=c.source_id),),
        'generate':lambda c:(AddToHand(c.player_id,C,c.source_id),),
        'automatic':lambda c:(CastStoredSpell(CardReference.capture(copied(c)),c.player_id,c.source_id),),
        'price':lambda c:(ModifyStoredCost(CardReference.capture(held(c)),CostSpec(delta=2),c.source_id),),
        'arm':arm,
        'copy_board':lambda c:(CopyMinion(c.target_id,c.player_id),),
        'copy_board_quantity':lambda c:(CopyMinion(c.target_id,c.player_id,cause=SummonCause.capture(c)),),
        'copy_stored_board':lambda c:(CopyStoredMinion(CardReference.capture(source(c)),c.player_id),),
        'bounce':lambda c:(ReturnToHand(c.target_id),),
        'control':lambda c:(ChangeControl(c.target_id,c.player_id),),
        'change_board':lambda c:(Transform(c.target_id,D),),
        'change_held':lambda c:(TransformStoredCard(CardReference.capture(held(c)),B,c.source_id),),
    }
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        fields={'targeting':MINION_TARGET}if name in('copy_board','copy_board_quantity','bounce','control','change_board')else{}
        r.register_card(CardDefinition(P+name,P+name,CardType.SPELL,on_play=P+name,**fields))
    if mode=='wait':
        def eligible(c):
            e=c.state.entities.get(c.event.source_id)
            return e is not None and e.copy_origin is not None and e.copy_origin.controller!=c.player_id and c.event.player_id==c.player_id
        def pause(c):
            return(RequestChoice(c.player_id,(
                ChoiceOption('ok','Continue',(GainArmor(c.player_id,2),)),
                ChoiceOption('fail','Rollback',(RandomDamage((c.state.players[3-c.player_id].hero_id,),1,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id))),
            ),c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible);r.register_behavior(P+'pause',pause)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec('card_committed',P+'pause',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeHeldOpponentCopyTests(unittest.TestCase):
    def game(self,hand=(CARD,P+'copy'),enemy_deck=(B,),mode=None,actor=1,own_board=(),enemy_board=(A,),enemy_hand=()):
        self.mode=mode
        if mode=='wait':own_board=(*own_board,WATCH)
        if mode=='retain':own_board=(*own_board,RETAIN)
        own=PlayerSetup(HERO,hand=hand,deck=(B,)*6,board=own_board,mana=100,max_mana=100,mana_cap=100)
        enemy=PlayerSetup(HERO,hand=enemy_hand,deck=enemy_deck,board=enemy_board,mana=100,max_mana=100,mana_cap=100)
        return Game.from_scenario(Scenario((own,enemy)if actor==1 else(enemy,own),active_player=actor,seed=195),registry(mode))

    def play(self,g,cid,target=None,entity=None):
        p=g.state.active_player
        eid=entity if entity is not None else next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(p,eid,target));return eid

    def held(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].card_id==CARD]

    def copied(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].copy_origin is not None]

    def price(self,g,p=None):return[g.quote_cost(e.id).amount for e in self.held(g,p)]

    def choose(self,g,key):
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(key,)))

    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertIsNot(reader,g.registry)
        self.assertEqual(Game.from_snapshot(deepcopy(saved),reader).snapshot(),saved)
        self.assertEqual(g.clone().snapshot(),saved);self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in(1,2):
            public=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for key in('copy_origin','progress_keys','play_ids','resolution_frame','rng_state'):
                self.assertNotIn(key,public)

    def reject(self,s,g):
        keys=('ruleset','registry_fingerprint','mechanics_version','state','rng_state','resolution_frame','rewind_session','match_setup','generation_context','information')
        s['state_hash']=canonical_hash({k:s[k]for k in keys})
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(s,g.registry)
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_original_face_and_unqualified_five_cost_destroy(self):
        g=self.game();raw=load_batch()['cards'][0]['record'];d=g.registry.card(CARD)
        self.assertEqual((d.name,d.cost,d.spell_school,d.metadata.classes),(raw['name'],5,SpellSchool.SHADOW,(CardClass.PRIEST,)))
        self.assertEqual(self.price(g),[5]);target=g.state.players[2].board[0];before=g.state.players[1].mana
        self.play(g,CARD,target);self.assertEqual(g.state.players[1].mana,before-5)
        self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.portable(g)

    def test_acquisition_only_does_not_satisfy_condition(self):
        g=self.game();self.play(g,P+'copy');self.assertTrue(self.copied(g));self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_same_class_opponent_spell_play_marks_and_pays_one(self):
        g=self.game();self.play(g,P+'copy');e=self.copied(g)[0];self.assertEqual(e.copy_origin.controller,2)
        self.play(g,B,entity=e.id);self.assertEqual(self.price(g),[1]);self.assertEqual(ability(self.held(g)[0]).progress_keys,('play:2',))
        before=g.state.players[1].mana;target=g.state.players[2].board[0];self.play(g,CARD,target)
        self.assertEqual(g.state.players[1].mana,before-1);self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)

    def test_opponent_minion_play_uses_same_paid_append_projection(self):
        g=self.game(enemy_deck=(A,));self.play(g,P+'copy');e=self.copied(g)[0]
        self.play(g,A,entity=e.id);self.assertEqual(self.price(g),[1]);self.assertEqual(g.state.entities[e.id].zone,Zone.BOARD);self.portable(g)

    def test_own_copy_and_same_named_opponent_card_do_not_qualify(self):
        g=self.game((CARD,P+'copy_own'));self.play(g,P+'copy_own');e=self.copied(g)[0]
        self.assertEqual(e.copy_origin.controller,1);self.play(g,B,entity=e.id);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_generated_other_class_card_is_not_a_copied_opponent_card(self):
        g=self.game((CARD,P+'generate'));self.play(g,P+'generate');self.play(g,C)
        self.assertEqual(self.price(g),[5]);self.assertIsNone(g.state.play_history[-1].copy_origin);self.portable(g)

    def test_moved_original_is_not_a_copy(self):
        g=self.game((CARD,P+'move_source'));self.play(g,P+'move_source');e=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==B)
        self.assertEqual((e.owner,e.controller,e.copy_origin),(2,1,None));self.play(g,B,entity=e.id);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_original_source_moving_to_other_controller_cannot_rewrite_credit(self):
        g=self.game((CARD,P+'copy',P+'move_source'));self.play(g,P+'copy');e=self.copied(g)[0];original=e.copy_origin.entity_id
        self.play(g,P+'move_source');self.assertEqual(g.state.entities[original].controller,1)
        self.play(g,B,entity=e.id);self.assertEqual(self.price(g),[1]);self.assertEqual(g.state.play_history[-1].copy_origin.controller,2);self.portable(g)

    def test_copied_spell_keeps_credit_after_stored_face_change(self):
        g=self.game((CARD,P+'copy',P+'change_copy'));self.play(g,P+'copy');eid=self.copied(g)[0].id
        self.play(g,P+'change_copy');self.assertEqual(g.state.entities[eid].card_id,C)
        self.play(g,C,entity=eid);self.assertEqual(self.price(g),[1]);self.assertEqual(g.state.play_history[-1].copy_origin.card_id,B);self.portable(g)

    def test_copied_minion_keeps_credit_after_stored_face_change(self):
        g=self.game((CARD,P+'copy',P+'change_copy'),enemy_deck=(A,));self.play(g,P+'copy');eid=self.copied(g)[0].id
        self.play(g,P+'change_copy');self.play(g,D,entity=eid);self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_shatter_derivatives_keep_copy_credit_separate_from_generated_origin(self):
        g=self.game(enemy_deck=(SPLIT,),mode='shatter');self.play(g,P+'copy')
        parts=self.copied(g);self.assertEqual({e.card_id for e in parts},{SPLIT+'L',SPLIT+'R'})
        self.assertTrue(all(e.copy_origin.entity_id!=e.origin_entity_id for e in parts));self.assertEqual(self.price(g),[5])
        self.play(g,SPLIT+'L');self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_multiple_current_holders_mark_once_and_new_holder_does_not_retroactively_mark(self):
        g=self.game((CARD,CARD,P+'copy'),mode='acquire');self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id)
        self.assertEqual(self.price(g),[1,1,5]);self.portable(g)

    def test_current_and_base_copy_keep_distinct_earned_progress(self):
        g=self.game((CARD,P+'copy',P+'pair'));self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id);self.play(g,P+'pair')
        self.assertEqual(self.price(g),[1,1,5]);self.assertEqual(len({ability(e).id for e in self.held(g)}),3);self.portable(g)

    def test_copy_of_own_copy_uses_immediate_source_policy(self):
        g=self.game((CARD,P+'copy',P+'pair'),enemy_deck=(CARD,));self.play(g,P+'copy');opponent_copy=self.copied(g)[0]
        self.play(g,P+'pair');own_copy=next(e for e in self.copied(g)if e.copy_origin.controller==1)
        target=g.state.players[2].board[0];self.play(g,CARD,target,entity=own_copy.id)
        self.assertEqual(g.state.play_history[-1].copy_origin.controller,1)
        self.assertEqual(g.quote_cost(opponent_copy.id).amount,5);self.assertEqual(self.price(g),[5,5,5]);self.portable(g)

    def test_leave_and_reenter_hand_resets_earned_condition(self):
        g=self.game((CARD,P+'copy',P+'reenter'));self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id)
        e=self.held(g)[0];entry=e.hand_entry_id;self.play(g,P+'reenter')
        self.assertEqual(self.held(g)[0].id,e.id);self.assertNotEqual(self.held(g)[0].hand_entry_id,entry);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_condition_does_not_carry_to_a_replacement_face(self):
        g=self.game((CARD,P+'copy',P+'change_held'));self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id)
        eid=self.held(g)[0].id;self.play(g,P+'change_held');self.assertEqual(g.state.entities[eid].card_id,B)
        self.assertIsNone(ability(g.state.entities[eid]));self.assertEqual(g.quote_cost(eid).amount,1);self.portable(g)

    def test_local_edits_and_external_aura_follow_intrinsic_set_to_one(self):
        g=self.game((CARD,P+'price',P+'copy'),own_board=(AURA,));self.play(g,P+'price');self.assertEqual(self.price(g),[9])
        self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_generated_quote_cannot_borrow_existing_physical_condition(self):
        g=self.game();self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id)
        self.assertEqual(self.price(g),[1]);before=g.snapshot()
        self.assertEqual(quote_generated_cost(g.state,g.registry,1,CARD).amount,5)
        self.assertEqual(g.snapshot(),before);self.portable(g)

    def test_automatic_cast_of_physical_copy_does_not_count_as_hand_play(self):
        g=self.game((CARD,P+'copy',P+'automatic'));self.play(g,P+'copy');self.play(g,P+'automatic')
        self.assertEqual(self.price(g),[5]);self.assertEqual(len(g.state.play_history),2);self.portable(g)

    def test_board_copies_do_not_count_until_bounced_and_manually_played(self):
        for name in('copy_board','copy_board_quantity','copy_stored_board'):
            with self.subTest(route=name):
                g=self.game((CARD,P+name,P+'bounce'),enemy_deck=(A,));target=g.state.players[2].board[0]
                self.play(g,P+name,target if name!='copy_stored_board'else None)
                eid=next(i for i in g.state.players[1].board if g.state.entities[i].copy_origin is not None)
                self.assertEqual(self.price(g),[5]);self.play(g,P+'bounce',eid);self.play(g,A,entity=eid)
                self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_paid_countered_copy_still_counts_as_a_play(self):
        g=self.game((CARD,P+'copy',P+'arm'));self.play(g,P+'copy');eid=self.copied(g)[0].id;self.play(g,P+'arm')
        self.play(g,B,entity=eid);self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_other_players_copied_play_marks_only_that_players_holders(self):
        g=self.game(actor=2,enemy_hand=(CARD,));self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id)
        self.assertEqual(self.price(g),[1]);self.assertFalse(ability(self.held(g,1)[0]).consumed)
        self.assertEqual(quote_unselected_cost(g.state,g.registry,self.held(g,1)[0]).amount,5)
        self.assertEqual(g.state.play_history[-1].player_id,2);self.portable(g)

    def test_real_ashamane_copy_can_satisfy_the_new_native_card(self):
        g=self.game((CARD,ASHAMANE),enemy_deck=(A,));self.play(g,ASHAMANE);self.assertEqual(self.price(g),[5])
        e=self.copied(g)[0];self.assertEqual(g.quote_cost(e.id).amount,0)
        self.play(g,A,entity=e.id);self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_commitment_wait_keeps_atomic_progress_cost_and_original_paid_quote(self):
        g=self.game(mode='wait');self.play(g,P+'copy');eid=self.copied(g)[0].id;before=g.state.players[1].mana
        self.play(g,B,entity=eid);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.price(g),[1])
        self.assertEqual(g.state.players[1].mana,before-1);self.portable(g)
        self.choose(g,'ok');self.assertEqual(self.price(g),[1]);self.assertEqual(ability(self.held(g)[0]).progress_keys,('play:2',));self.portable(g)

    def test_failed_wait_choice_rolls_back_only_choice_and_preserves_earned_fact(self):
        g=self.game(mode='wait');self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id);before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K195 deliberate'):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),[1]);self.portable(g);self.choose(g,'ok');self.portable(g)

    def test_original_copied_payload_failure_rolls_back_payment_progress_rng_and_information(self):
        g=self.game(mode='failure');self.play(g,P+'copy');eid=self.copied(g)[0].id;before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'K195 deliberate'):self.play(g,B,entity=eid)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_rewind_reexecutes_original_copy_play_without_accumulating_attempts(self):
        for mode in('rewind','retain'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);self.play(g,P+'copy');eid=self.copied(g)[0].id;mana=g.state.players[1].mana
                self.play(g,B,entity=eid);self.assertEqual(self.price(g),[1]);self.portable(g)
                if mode=='rewind':self.choose(g,'retry')
                else:self.assertIsNone(g.state.pending_choice)
                self.assertEqual(g.state.players[1].mana,mana-1);self.assertEqual(len(g.state.play_history),2)
                self.assertEqual(ability(self.held(g)[0]).progress_keys,('play:2',));self.assertEqual(self.price(g),[1]);self.portable(g)

    def test_invalid_original_target_does_not_pay_or_set_progress(self):
        g=self.game();before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,CARD,g.state.players[2].hero_id)
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.price(g),[5]);self.portable(g)

    def test_rehashed_noncopy_and_nonplay_progress_witnesses_are_rejected(self):
        g=self.game();self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id);self.portable(g)
        eid=str(self.held(g)[0].id)
        for key in('play:1','event:1'):
            s=deepcopy(g.snapshot());a=next(a for a in s['state']['entities'][eid]['abilities']if a['kind']=='hand_progress')
            a['progress_keys']=[key];self.reject(s,g)

    def test_rehashed_origin_removal_or_relation_rewrite_is_rejected(self):
        g=self.game();self.play(g,P+'copy');eid=self.copied(g)[0].id;self.play(g,B,entity=eid);self.portable(g)
        s=deepcopy(g.snapshot());s['state']['entities'][str(eid)]['copy_origin']=None;self.reject(s,g)
        s=deepcopy(g.snapshot());s['state']['entities'][str(eid)]['copy_origin']['controller']=1
        s['state']['play_history'][-1]['copy_origin']['controller']=1;self.reject(s,g)

    def test_rehashed_paid_quote_cannot_borrow_another_physical_witness(self):
        g=self.game();self.play(g,P+'copy');self.play(g,B,entity=self.copied(g)[0].id);self.play(g,CARD,g.state.players[2].board[0]);self.portable(g)
        s=deepcopy(g.snapshot());fact=s['state']['play_history'][-1]['submitted_cost']['quote']['intrinsic']['condition_facts'][0]
        fact['play_ids']=[1];self.reject(s,g)

    def test_old_397_snapshot_is_explicitly_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=397
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,g.registry)
