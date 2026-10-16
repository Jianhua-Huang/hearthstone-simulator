"""Whole-game semantic shuffle pricing, actual producers and original proofs."""
from dataclasses import replace
import json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards.shuffle_native_cards import load_batch
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,
    PlayCard,PlayerSetup,Rarity,Scenario,SelectChoice,SnapshotError,TriggerSpec,Zone)
from hs_sim.engine.costs import quote_unselected_cost,quote_input,capture_cost_input
from hs_sim.engine.deck_shuffles import ShuffleDeckCards,shuffled,validate_cost_prefix
from hs_sim.engine.effects import AddToHand,ChoiceOption,GainArmor,InvokeBehavior,RequestChoice,ShuffleIntoDeck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.intrinsic_costs import validate_intrinsic_stage_fact
from hs_sim.engine.model import CostSpec,Keyword
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import AddToDeck,CardReference,CopyCard,MoveCard,ShuffleDeck
from hs_sim.targets import canonical_digest

TRACKER='TLC_520';RAPTORS='TLC_826';PLAIN='CORE_CS2_182'


def registry():
    r=build_registry();meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=())
    def own(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==TRACKER)
    def batch(c,count=3,owner=None):
        owner=c.player_id if owner is None else owner
        return shuffled(c,(AddToDeck(owner,PLAIN,source_id=c.source_id)for _ in range(count)),player_id=owner)
    def wait(c):
        if c.state.entities[c.event.source_id].card_id!=TRACKER:return ()
        return(RequestChoice(c.player_id,(ChoiceOption('ok','Shuffle after payment',batch(c,1)),
            ChoiceOption('bad','Fail',(InvokeBehavior('k49.fail',c.source_id,c.player_id),))),c.source_id),)
    scripts=dict(fail=lambda c:(AddToHand(c.player_id,'unknown.k49',c.source_id),),batch=batch,single=lambda c:batch(c,1),empty=lambda c:shuffled(c,()),
        foreign=lambda c:batch(c,3,3-c.player_id),acquire=lambda c:(AddToHand(c.player_id,TRACKER,c.source_id),),
        current=lambda c:(CopyCard(CardReference.capture(own(c)),c.player_id,mode='current',source_id=c.source_id),),
        base=lambda c:(CopyCard(CardReference.capture(own(c)),c.player_id,mode='base',source_id=c.source_id),),
        transfer=lambda c:(MoveCard(CardReference.capture(own(c)),3-c.player_id,Zone.HAND,source_id=c.source_id),),
        unknown=lambda c:(AddToDeck(c.player_id,PLAIN,source_id=c.source_id),),
        bottom=lambda c:(AddToDeck(c.player_id,PLAIN,position='bottom',source_id=c.source_id),),
        top=lambda c:(AddToDeck(c.player_id,PLAIN,position='top',source_id=c.source_id),),
        reorder=lambda c:(ShuffleDeck(c.player_id),),
        cost=lambda c:(__import__('hs_sim.engine.zones',fromlist=['ModifyStoredCost']).ModifyStoredCost(CardReference.capture(own(c)),CostSpec(delta=-1),c.source_id),),
        copydeck=lambda c:shuffled(c,(CopyCard(CardReference.capture(own(c)),c.player_id,Zone.DECK,source_id=c.source_id),)),
        movedeck=lambda c:shuffled(c,(MoveCard(CardReference.capture(own(c)),c.player_id,Zone.DECK,'random',source_id=c.source_id),)))
    def stale(c):
        ref=CardReference.capture(own(c))
        return(MoveCard(ref,c.player_id,Zone.DECK,'top',source_id=c.source_id),
            ShuffleDeckCards(c.player_id,c.player_id,(MoveCard(ref,c.player_id,Zone.DECK,'random',source_id=c.source_id),),c.source_id))
    scripts['stale']=stale
    for name,body in scripts.items():
        key='k49.'+name;r.register_behavior(key,body);r.register_card(CardDefinition(key,name,CardType.SPELL,on_play=key,metadata=meta))
    r.register_behavior('k49.wait',wait)
    r.register_card(CardDefinition('k49.wait','Post-payment wait',CardType.MINION,health=8,metadata=meta,
        triggers=(TriggerSpec('card_committed','k49.wait'),)))
    return r


class ShuffleNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.r=registry()
    def game(self,hand=(),*,board=(),enemy_hand=(),deck=(PLAIN,)*6):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=hand,board=board,deck=deck,
            mana=80,max_mana=80,mana_cap=80,hand_cap=30),PlayerSetup('HERO_08',hand=enemy_hand,deck=(PLAIN,)*6,
            mana=80,max_mana=80,mana_cap=80,hand_cap=30)),seed=949),self.r)
    def eid(self,g,cid,p=1,zone='hand'):
        s=g.state;return next(i for i in getattr(s.players[p],zone)if s.entities[i].card_id==cid)
    def play(self,g,cid,p=1):
        s=g.state;eid=self.eid(g,cid,p);g.apply(PlayCard(p,eid,position=len(s.players[p].board)if s.entities[eid].kind==CardType.MINION else None));return eid
    def quote(self,g,eid=None,p=1):
        s=g.state;return quote_unselected_cost(s,g.registry,s.entities[eid if eid is not None else self.eid(g,TRACKER,p)])
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));other=Game.from_snapshot(saved,registry())
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),registry()).snapshot(),saved);return other
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))

    def test_real_complete_tracker_face_and_intrinsic_declaration(self):
        row=load_batch()['cards'][0];raw=row['record'];c=self.r.card(TRACKER)
        self.assertEqual(canonical_digest(raw),row['record_sha256']);self.assertEqual((c.cost,c.attack,c.health),(6,5,5))
        self.assertEqual(c.keywords,(Keyword.RUSH,));self.assertEqual(c.intrinsic_costs[0].condition,'own_deck_shuffle_count')

    def test_unshuffled_tracker_costs_six(self):
        g=self.game((TRACKER,));self.assertEqual(self.quote(g).amount,6)

    def test_one_semantic_batch_of_three_is_one_discount(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch')
        self.assertEqual(self.quote(g).amount,5);self.assertEqual(len(g.state.deck_shuffle_history),1)
        self.assertEqual(g.state.deck_shuffle_history[0].declared_count,3);self.portable(g)

    def test_actual_ten_raptor_card_is_one_operation_not_ten(self):
        g=self.game((RAPTORS,TRACKER));source=self.play(g,RAPTORS);s=g.state
        self.assertEqual(self.quote(g).amount,5);self.assertEqual(len(s.deck_shuffle_history),1)
        self.assertEqual(s.deck_shuffle_history[0].source.entity_id,source)
        self.assertEqual(sum(s.entities[i].card_id=='UNG_920t2'for i in s.players[1].deck),10);self.portable(g)

    def test_separate_actual_shuffle_operations_stack_and_stop_at_zero(self):
        g=self.game(('k49.batch',)*7+(TRACKER,))
        for i in range(7):self.play(g,'k49.batch');self.assertEqual(self.quote(g).amount,max(0,5-i))
        self.assertEqual(len(g.state.deck_shuffle_history),7)

    def test_actual_payment_uses_the_intrinsic_discount_once(self):
        g=self.game((RAPTORS,TRACKER));self.play(g,RAPTORS);before=g.state.players[1].mana;source=self.play(g,TRACKER)
        self.assertEqual(g.state.players[1].mana,before-5);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(5,5));self.portable(g)

    def test_history_is_recorded_before_any_tracker_exists(self):
        g=self.game(('k49.batch','k49.acquire'));self.play(g,'k49.batch');self.play(g,'k49.acquire')
        self.assertEqual(self.quote(g).amount,5);self.portable(g)

    def test_queried_price_does_not_consume_rng_history_or_modifiers(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch');before=g.snapshot();rng=g._rng.getstate()
        self.assertEqual(self.quote(g).amount,5);self.assertEqual(self.quote(g).amount,5)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g._rng.getstate(),rng)

    def test_current_and_base_copies_use_complete_payer_history(self):
        for mode in('current','base'):
            g=self.game(('k49.batch','k49.'+mode,TRACKER));self.play(g,'k49.batch');self.play(g,'k49.'+mode);s=g.state
            ids=[i for i in s.players[1].hand if s.entities[i].card_id==TRACKER]
            self.assertEqual(len(ids),2);self.assertEqual([self.quote(g,i).amount for i in ids],[5,5])

    def test_foreign_recipient_is_not_the_original_shuffle_actor(self):
        g=self.game(('k49.foreign',TRACKER),enemy_hand=(TRACKER,));self.play(g,'k49.foreign')
        self.assertEqual((self.quote(g).amount,self.quote(g,p=2).amount),(6,6))
        row=g.state.deck_shuffle_history[0];self.assertEqual((row.actor_id,row.player_id),(1,2));self.portable(g)

    def test_opponent_shuffle_into_own_deck_does_not_discount_your_card(self):
        g=self.game((TRACKER,),enemy_hand=('k49.foreign',));g.apply(EndTurn(1));self.play(g,'k49.foreign',p=2)
        self.assertEqual(self.quote(g).amount,6)

    def test_transfer_reprices_using_new_controllers_history(self):
        g=self.game(('k49.batch','k49.transfer',TRACKER));self.play(g,'k49.batch');original=self.eid(g,TRACKER)
        self.assertEqual(self.quote(g).amount,5);self.play(g,'k49.transfer')
        self.assertEqual(g.state.entities[original].controller,2);self.assertEqual(self.quote(g,original).amount,6);self.portable(g)

    def test_top_bottom_and_reordering_existing_deck_do_not_count(self):
        g=self.game(('k49.top','k49.bottom','k49.reorder',TRACKER))
        for name in('top','bottom','reorder'):self.play(g,'k49.'+name)
        self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(self.quote(g).amount,6);self.portable(g)

    def test_empty_semantic_batch_has_no_credit_and_no_rng(self):
        g=self.game(('k49.empty',TRACKER));rng=g._rng.getstate();self.play(g,'k49.empty')
        self.assertEqual(g._rng.getstate(),rng);self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(self.quote(g).amount,6)

    def test_expired_original_physical_entry_does_not_create_credit(self):
        g=self.game(('k49.stale',TRACKER));original=self.eid(g,TRACKER);self.play(g,'k49.stale')
        self.assertFalse(g.state.deck_shuffle_history);self.assertEqual(g.state.entities[original].zone,Zone.DECK);self.portable(g)

    def test_unknown_direct_issuer_is_explicitly_unsupported_not_zero(self):
        g=self.game(('k49.unknown',TRACKER));self.play(g,'k49.unknown')
        self.assertIsNone(g.state.deck_shuffle_history[0].actor_id)
        with self.assertRaises(ValueError):self.quote(g)

    def test_ordinary_local_cost_modifier_keeps_its_layer_after_intrinsic(self):
        g=self.game(('k49.batch','k49.cost',TRACKER));self.play(g,'k49.batch');self.play(g,'k49.cost')
        self.assertEqual(self.quote(g).amount,4);self.portable(g)

    def test_real_current_hand_copy_to_deck_is_one_operation(self):
        g=self.game(('ICC_091',TRACKER,PLAIN));self.play(g,'ICC_091')
        self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(self.quote(g).amount,5)
        self.assertEqual(sum(g.state.entities[i].card_id==TRACKER for i in g.state.players[1].deck),1);self.portable(g)

    def test_copy_to_deck_records_one_original_operation(self):
        g=self.game(('k49.copydeck',TRACKER));self.play(g,'k49.copydeck');self.assertEqual(self.quote(g).amount,5);self.portable(g)

    def test_original_hand_card_move_is_one_operation_with_original_physical_id(self):
        g=self.game(('k49.movedeck',TRACKER));original=self.eid(g,TRACKER);self.play(g,'k49.movedeck')
        row=g.state.deck_shuffle_history[0];self.assertEqual(row.first_card.entity_id,original)
        self.assertEqual(self.quote(g,original).amount,5);self.portable(g)

    def test_pending_payment_receipt_keeps_original_price_after_a_later_shuffle(self):
        g=self.game(('k49.batch',TRACKER),board=('k49.wait',));self.play(g,'k49.batch');before=g.state.players[1].mana
        source=self.play(g,TRACKER);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.players[1].mana,before-5)
        g=self.portable(g);self.choose(g);self.assertEqual(g.state.players[1].mana,before-5)
        self.assertEqual(len(g.state.deck_shuffle_history),2);self.assertEqual(g.state.entities[source].zone,Zone.BOARD);self.portable(g)

    def test_failed_post_payment_choice_restores_original_boundary_and_rng(self):
        g=self.game(('k49.batch',TRACKER),board=('k49.wait',));self.play(g,'k49.batch');self.play(g,TRACKER);saved=g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),saved);self.choose(g);self.assertIsNone(g.state.pending_choice)

    def test_complete_operation_prefix_and_selected_ids_are_frozen_in_quote(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch');s=g.state;fact=quote_input(s,g.registry,capture_cost_input(s.entities[self.eid(g,TRACKER)])).intrinsic;condition=fact.condition_facts[0]
        self.assertEqual(condition.quantity,1);self.assertEqual(condition.selected_ids,(1,));self.assertEqual(len(condition.records),1)
        validate_intrinsic_stage_fact(g.registry,fact);validate_cost_prefix(condition,g.state,g.registry)
        with self.assertRaises(ValueError):replace(condition,selected_ids=(),quantity=0,matched=False).__post_init__()

    def test_saved_history_cannot_be_dropped_while_insertion_events_remain(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch');saved=g.snapshot();saved['state']['deck_shuffle_history']=[]
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_saved_operation_issuer_cannot_be_rewritten_without_original_event(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch');saved=g.snapshot();saved['state']['deck_shuffle_history'][0]['actor_id']=2
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry())

    def test_batch_rejects_an_unrelated_destination_or_nonrandom_operation(self):
        with self.assertRaises(ValueError):ShuffleDeckCards(1,1,(AddToDeck(2,PLAIN),))
        with self.assertRaises(ValueError):ShuffleDeckCards(1,1,(AddToDeck(1,PLAIN,position='bottom'),))
        with self.assertRaises(ValueError):ShuffleDeckCards(1,1,(AddToHand(1,PLAIN),))

    def test_player_projection_contains_price_without_private_shuffle_materials(self):
        g=self.game(('k49.batch',TRACKER));self.play(g,'k49.batch');own=g.for_player(1).observe()['observation']
        player=next(p for p in own['players']if p['id']==1);self.assertEqual(player['hand'][0]['cost']['amount'],5)
        enemy=g.for_player(2).observe()['observation'];other=next(p for p in enemy['players']if p['id']==1)
        self.assertEqual(other['hand'][0]['card_id'],None)
        for key in('deck_shuffle_history','first_card','declared_count','selected_ids'):self.assertNotIn(key,json.dumps(enemy))

    def test_actual_previous_snapshot_is_rejected(self):
        from pathlib import Path
        old=json.loads(Path('outputs/card-integration-20261014/k49-before/constructed-v57-core349-schema276.json').read_text(encoding='utf-8'))
        with self.assertRaises(SnapshotError):Game.from_snapshot(old,self.r)
