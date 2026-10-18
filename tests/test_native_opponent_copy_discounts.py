"""Enthralled Shade consumes physical copy credit through ordinary hand costs."""
from copy import deepcopy
from functools import lru_cache
import json
import unittest

import test_native_held_opponent_copy_cards as f
from hs_sim.cards.native_held_opponent_copy_cards import SHADE as CARD, load_batch
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RandomDamage, RequestChoice, Silence, TriggerDeathrattles)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CostSpec, LimitedTriggerSpec
from hs_sim.engine.zones import CardReference, CopyCard, CopyMatching, ModifyStoredCost, MoveCard

P='k197.'; EXP=P+'spell'; MINION=P+'minion'; WATCH=P+'watch'


@lru_cache(maxsize=None)
def registry(mode=None):
    r=f.registry.__wrapped__(P+str(mode))
    r.register_behavior(P+'noop',lambda c:())
    r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('K197 deliberate failure')))
    r.register_card(f.CardDefinition(EXP,EXP,f.CardType.SPELL,cost=6,on_play=P+'noop'))
    r.register_card(f.CardDefinition(MINION,MINION,f.CardType.MINION,cost=4,attack=3,health=8))
    def copied(c):
        return next(c.state.entities[i]for i in c.state.players[c.player_id].hand
            if c.state.entities[i].copy_origin is not None)
    def reenter(c):
        e=copied(c)
        return(MoveCard(CardReference.capture(e),c.player_id,f.Zone.DECK,'top',source_id=c.source_id),
            f.Draw(c.player_id,source_id=c.source_id))
    bodies={
        'copy':lambda c:(CopyMatching(c.player_id,3-c.player_id,f.Zone.DECK,source_id=c.source_id),),
        'own':lambda c:(CopyMatching(c.player_id,c.player_id,f.Zone.DECK,source_id=c.source_id),),
        'enemy_copy':lambda c:(CopyMatching(3-c.player_id,c.player_id,f.Zone.DECK,source_id=c.source_id),),
        'kill':lambda c:(Destroy(c.target_id,c.source_id),),
        'trigger':lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
        'silence':lambda c:(Silence(c.target_id),),
        'control':lambda c:(ChangeControl(c.target_id,3-c.player_id),),
        'generate':lambda c:(AddToHand(c.player_id,EXP,c.source_id),),
        'move':lambda c:(MoveCard(CardReference.capture(c.state.entities[c.state.players[3-c.player_id].deck[0]]),c.player_id,f.Zone.HAND,source_id=c.source_id),),
        'change':lambda c:(f.TransformStoredCard(CardReference.capture(copied(c)),MINION,c.source_id),),
        'set':lambda c:(ModifyStoredCost(CardReference.capture(copied(c)),CostSpec(set_to=4),c.source_id),),
        'pair':lambda c:tuple(CopyCard(CardReference.capture(copied(c)),c.player_id,mode=m,source_id=c.source_id)for m in('current','base')),
        'reenter':reenter,
        'kill_fail':lambda c:(Destroy(c.target_id,c.source_id),InvokeBehavior(P+'fail',c.source_id,c.player_id)),
    }
    targets={'kill','trigger','silence','control','kill_fail'}
    for name,body in bodies.items():
        r.register_behavior(P+name,body)
        fields={'targeting':f.MINION_TARGET}if name in targets else{}
        r.register_card(f.CardDefinition(P+name,P+name,f.CardType.SPELL,on_play=P+name,**fields))
    if mode in('death_copy','death_wait','cost_wait'):
        event='cost_modified'if mode=='cost_wait'else'minion_died'
        def eligible(c):
            e=c.state.entities.get(c.event.source_id)
            return e is not None and e.card_id==CARD
        def react(c):
            if mode=='death_copy':
                return(CopyMatching(c.player_id,3-c.player_id,f.Zone.DECK,source_id=c.source_id),)
            acquire=(CopyMatching(c.player_id,3-c.player_id,f.Zone.DECK,source_id=c.source_id),)
            fail=(RandomDamage(tuple(c.state.players[p].hero_id for p in(1,2)),1,c.source_id),
                InvokeBehavior(P+'fail',c.source_id,c.player_id))
            if mode=='death_wait':
                options=(ChoiceOption('ok','Copy before Deathrattle',acquire),ChoiceOption('fail','Rollback',fail))
            else:
                later=next(c.state.entities[i]for i in c.state.players[c.player_id].hand
                    if i!=c.event.target_id and c.state.entities[i].copy_origin is not None)
                move=(MoveCard(CardReference.capture(later),c.player_id,f.Zone.DECK,'top',source_id=c.source_id),
                    f.Draw(c.player_id,source_id=c.source_id))
                options=(ChoiceOption('ok','Continue',()),ChoiceOption('new','New copy',acquire),
                    ChoiceOption('move','Reenter later target',move),ChoiceOption('fail','Rollback',fail))
            return(RequestChoice(c.player_id,options,c.source_id),)
        r.register_trigger_condition(P+'eligible',eligible)
        r.register_behavior(P+'react',react)
        r.register_card(f.CardDefinition(WATCH,WATCH,f.CardType.MINION,health=20,
            limited_triggers=(LimitedTriggerSpec(event,P+'react',condition_id=P+'eligible'),)))
    r.validate();return r


class NativeOpponentCopyDiscountTests(unittest.TestCase):
    def game(self,hand=(CARD,P+'copy',P+'kill'),enemy_deck=(EXP,),mode=None,actor=1,own_board=(),enemy_hand=()):
        self.mode=mode
        if mode in('death_copy','death_wait','cost_wait'):own_board=(*own_board,WATCH)
        own=f.PlayerSetup(f.HERO,hand=hand,deck=(EXP,)*6,board=own_board,mana=100,max_mana=100,mana_cap=100)
        other=f.PlayerSetup(f.HERO,hand=enemy_hand,deck=enemy_deck,mana=100,max_mana=100,mana_cap=100)
        return f.Game.from_scenario(f.Scenario((own,other)if actor==1 else(other,own),active_player=actor,seed=197),registry(mode))

    def play(self,g,cid,target=None,entity=None):
        p=g.state.active_player
        eid=entity if entity is not None else next(i for i in g.state.players[p].hand if g.state.entities[i].card_id==cid)
        g.apply(f.PlayCard(p,eid,target));return eid

    def copies(self,g,p=None):
        p=g.state.active_player if p is None else p
        return[g.state.entities[i]for i in g.state.players[p].hand if g.state.entities[i].copy_origin is not None]

    def cost(self,g,eid):return f.quote_unselected_cost(g.state,g.registry,g.state.entities[eid]).amount

    def kill(self,g):
        eid=next(i for i in g.state.players[g.state.active_player].board if g.state.entities[i].card_id==CARD)
        self.play(g,P+'kill',eid);return eid

    def choose(self,g,key):
        c=g.state.pending_choice;g.apply(f.SelectChoice(c.player_id,c.id,(key,)))

    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));reader=registry.__wrapped__(self.mode)
        self.assertEqual(f.Game.from_snapshot(deepcopy(s),reader).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s)
        self.assertEqual(f.replay(f.build_replay(g),reader).snapshot(),s)
        for p in(1,2):
            visible=json.dumps(g.observe(p))+json.dumps(g.player_events(p))+json.dumps(g.for_player(p).legal_actions())
            for private in('copy_origin','resolution_frame','rng_state','zone_epoch'):
                self.assertNotIn(private,visible)

    def test_complete_native_face_metadata_and_two_primary_observations(self):
        d=load_batch();row=next(x for x in d['cards']if x['record']['id']==CARD);raw=row['record'];card=registry().card(CARD)
        self.assertEqual((raw['id'],raw['dbf_id'],raw['name_en']),(CARD,126127,'Enthralled Shade'))
        self.assertEqual((card.kind,card.cost,card.attack,card.health),(f.CardType.MINION,2,3,2))
        self.assertIsNotNone(card.deathrattle);self.assertIsNone(card.battlecry)
        self.assertEqual(card.metadata,metadata_from_record(raw))
        self.assertEqual(len(d['official_observations']),6)

    def test_real_paid_death_discounts_each_physical_copy_and_preserves_source_deck(self):
        g=self.game((CARD,P+'copy',P+'copy',P+'kill'))
        original=deepcopy(g.state.players[2].deck)
        self.play(g,P+'copy');self.play(g,P+'copy');ids=[e.id for e in self.copies(g)]
        shade=self.play(g,CARD);self.assertEqual([self.cost(g,i)for i in ids],[6,6])
        self.kill(g);self.assertEqual([self.cost(g,i)for i in ids],[5,5])
        self.assertEqual(g.state.players[2].deck,original)
        self.assertEqual(g.state.entities[shade].zone,f.Zone.GRAVEYARD)
        self.assertEqual(len(g.state.death_history),1);self.assertTrue(g.state.deathrattle_history[-1].completed)
        self.assertEqual([e.id for e in self.copies(g)],ids);self.portable(g)

    def test_spell_and_minion_copies_use_the_same_discount(self):
        for source,cost in((EXP,6),(MINION,4)):
            with self.subTest(source=source):
                g=self.game(enemy_deck=(source,));self.play(g,P+'copy');eid=self.copies(g)[0].id
                self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,eid),cost-1)

    def test_own_copy_generated_card_and_moved_original_are_not_eligible(self):
        for action in('own','generate','move'):
            with self.subTest(action=action):
                g=self.game((CARD,P+action,P+'kill'));self.play(g,P+action)
                e=next(g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==EXP)
                self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,e.id),6)

    def test_source_transferred_after_copy_does_not_rewrite_original_credit(self):
        g=self.game((CARD,P+'copy',P+'move',P+'kill'))
        self.play(g,P+'copy');e=self.copies(g)[0];original=e.copy_origin.entity_id
        self.play(g,P+'move');self.assertEqual(g.state.entities[original].controller,1)
        self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,e.id),5)

    def test_transformed_copy_keeps_eligibility_from_original_physical_source(self):
        g=self.game((CARD,P+'copy',P+'change',P+'kill'))
        self.play(g,P+'copy');eid=self.copies(g)[0].id;self.play(g,P+'change')
        self.assertEqual(g.state.entities[eid].card_id,MINION)
        self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,eid),3);self.portable(g)

    def test_copying_own_copy_does_not_give_new_copies_opponent_credit(self):
        g=self.game((CARD,P+'copy',P+'pair',P+'kill'))
        self.play(g,P+'copy');self.play(g,P+'pair');copies=self.copies(g)
        self.assertEqual([e.copy_origin.controller for e in copies],[2,1,1])
        self.play(g,CARD);self.kill(g)
        self.assertEqual([self.cost(g,e.id)for e in copies],[5,6,6]);self.portable(g)

    def test_active_deathrattle_repeats_stack_without_killing_the_source(self):
        g=self.game((CARD,P+'copy',P+'trigger',P+'trigger'))
        self.play(g,P+'copy');eid=self.copies(g)[0].id;shade=self.play(g,CARD)
        self.play(g,P+'trigger',shade);self.play(g,P+'trigger',shade)
        self.assertEqual(self.cost(g,eid),4);self.assertEqual(g.state.entities[shade].zone,f.Zone.BOARD)
        self.assertEqual([d.capture.origin for d in g.state.deathrattle_history],['effect','effect'])
        self.assertFalse(g.state.death_history);self.portable(g)

    def test_zero_cost_floor_is_preserved(self):
        g=self.game(enemy_deck=(f.B,));self.play(g,P+'copy');eid=self.copies(g)[0].id
        self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,eid),0)

    def test_existing_local_set_and_external_aura_remain_in_ordinary_order(self):
        g=self.game((CARD,P+'copy',P+'set',P+'kill'),own_board=(f.AURA,))
        self.play(g,P+'copy');eid=self.copies(g)[0].id;self.play(g,P+'set')
        self.assertEqual(self.cost(g,eid),6)
        self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,eid),5);self.portable(g)

    def test_silence_removes_native_deathrattle(self):
        g=self.game((CARD,P+'copy',P+'silence',P+'kill'))
        self.play(g,P+'copy');eid=self.copies(g)[0].id;shade=self.play(g,CARD)
        self.play(g,P+'silence',shade);self.kill(g)
        self.assertEqual(self.cost(g,eid),6);self.assertFalse(g.state.deathrattle_history)

    def test_death_uses_controller_hand_and_opponent_relative_to_that_player(self):
        g=self.game((CARD,P+'enemy_copy',P+'control',P+'kill'))
        self.play(g,P+'enemy_copy');eid=self.copies(g,2)[0].id;shade=self.play(g,CARD)
        self.play(g,P+'control',shade);self.play(g,P+'kill',shade)
        self.assertEqual(g.state.deathrattle_history[-1].capture.player_id,2)
        self.assertEqual(self.cost(g,eid),5);self.portable(g)

    def test_second_player_receives_its_own_discount(self):
        g=self.game(actor=2);self.play(g,P+'copy');eid=self.copies(g)[0].id
        self.play(g,CARD);self.kill(g);self.assertEqual(self.cost(g,eid),5)
        self.assertEqual(g.state.deathrattle_history[-1].capture.player_id,2);self.portable(g)

    def test_death_reaction_new_copy_is_included_at_actual_execution(self):
        g=self.game((CARD,P+'kill'),mode='death_copy')
        self.play(g,CARD);self.kill(g);copies=self.copies(g)
        self.assertEqual(len(copies),1);self.assertEqual(self.cost(g,copies[0].id),5);self.portable(g)

    def test_death_wait_restores_then_uses_new_hand_copy_once(self):
        g=self.game((CARD,P+'kill'),mode='death_wait');self.play(g,CARD);self.kill(g)
        self.assertIsNotNone(g.state.pending_choice);self.assertFalse(self.copies(g));self.portable(g)
        self.choose(g,'ok');eid=self.copies(g)[0].id
        self.assertEqual(self.cost(g,eid),5);self.assertEqual(len(g.state.deathrattle_history),1);self.portable(g)

    def test_failed_death_choice_rolls_back_information_rng_and_pending_body(self):
        g=self.game((CARD,P+'kill'),mode='death_wait');self.play(g,CARD);self.kill(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok');self.assertEqual(self.cost(g,self.copies(g)[0].id),5)

    def test_cost_wait_preserves_paid_action_and_unexecuted_hand_tail(self):
        g=self.game((CARD,P+'copy',P+'copy',P+'kill'),mode='cost_wait')
        self.play(g,P+'copy');self.play(g,P+'copy');ids=[e.id for e in self.copies(g)]
        self.play(g,CARD);self.kill(g)
        self.assertEqual([self.cost(g,i)for i in ids],[5,6]);self.portable(g)
        self.choose(g,'ok');self.assertEqual([self.cost(g,i)for i in ids],[5,5]);self.portable(g)

    def test_later_target_reentry_invalidates_its_frozen_reference(self):
        g=self.game((CARD,P+'copy',P+'copy',P+'kill'),mode='cost_wait')
        self.play(g,P+'copy');self.play(g,P+'copy');ids=[e.id for e in self.copies(g)]
        self.play(g,CARD);self.kill(g);self.choose(g,'move')
        self.assertEqual([self.cost(g,i)for i in ids],[5,6]);self.portable(g)

    def test_copy_acquired_after_body_acceptance_does_not_join_original_tail(self):
        g=self.game((CARD,P+'copy',P+'copy',P+'kill'),mode='cost_wait')
        self.play(g,P+'copy');self.play(g,P+'copy');self.play(g,CARD);self.kill(g);self.choose(g,'new')
        self.assertEqual([self.cost(g,e.id)for e in self.copies(g)],[5,5,6]);self.portable(g)

    def test_failed_cost_choice_restores_first_discount_and_tail(self):
        g=self.game((CARD,P+'copy',P+'copy',P+'kill'),mode='cost_wait')
        self.play(g,P+'copy');self.play(g,P+'copy');self.play(g,CARD);self.kill(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertEqual(g.snapshot(),s);self.choose(g,'ok')
        self.assertEqual([self.cost(g,e.id)for e in self.copies(g)],[5,5])

    def test_outer_failure_restores_payment_death_and_cost_attachments(self):
        g=self.game((CARD,P+'copy',P+'kill_fail'));self.play(g,P+'copy');shade=self.play(g,CARD);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,P+'kill_fail',shade)
        self.assertEqual(g.snapshot(),s);self.assertEqual(self.cost(g,self.copies(g)[0].id),6)

    def test_permanent_discount_is_used_by_later_actual_payment(self):
        g=self.game();self.play(g,P+'copy');eid=self.copies(g)[0].id;self.play(g,CARD);self.kill(g)
        g.apply(f.EndTurn(1));g.apply(f.EndTurn(2));self.assertEqual(self.cost(g,eid),5)
        mana=g.state.players[1].mana;self.play(g,EXP,entity=eid)
        self.assertEqual(mana-g.state.players[1].mana,5);self.portable(g)

    def test_real_ashamane_copy_discount_stacks_on_its_original_local_cost(self):
        g=self.game((f.ASHAMANE,CARD,P+'kill'));self.play(g,f.ASHAMANE)
        copies=self.copies(g);self.assertTrue(copies);self.assertTrue(all(self.cost(g,e.id)==3 for e in copies))
        self.play(g,CARD);self.kill(g)
        self.assertTrue(all(self.cost(g,e.id)==2 for e in copies));self.portable(g)
