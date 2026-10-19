"""A private mixed hand guess, original-deck decoys and ordinary self health."""
from copy import deepcopy
from dataclasses import replace
import json
import random
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.futuristic_forefather_card import CARD, load_batch, register_futuristic_forefather_card
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game, GenerationContext,
    Keyword, PlayCard, PlayerSetup, Rarity, Registry, Ruleset, Scenario, SelectChoice, SnapshotError,
    TriggerSpec, Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import AddToHand, Damage, InvokeBehavior, ReturnToHand
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.hand_inspection import GuessOpponentHandCard, guess_decoys, selected_hand_guess
from hs_sim.engine.model import ChoiceResult
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import canonical_digest

P = 'forefather.test.'
DEFAULT_DECK = (P+'a',P+'b',P+'c',P+'d')


def registry(mode=None):
    r=Registry('forefather-native-tests-v1');meta=CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON)
    r.register_card(CardDefinition(P+'hero','Hero',CardType.HERO,health=100))
    register_futuristic_forefather_card(r)
    r.register_behavior(P+'noop',lambda c:())
    for cid in ('a','a_alias','b','b_alias','c','d','filler'):
        face=cid.split('_')[0]
        card=CardDefinition(P+cid,face.upper(),CardType.SPELL,on_play=P+'noop',metadata=meta)
        r.register_card(card);r.register_pool_card(PoolCard.from_definition(card,identity=P+face))
    def reenter(c):
        target=c.state.entities[c.target_id]
        return (SummonStoredCard(CardReference.capture(target),target.controller),)
    r.register_behavior(P+'reenter',reenter)
    r.register_behavior(P+'fail',lambda c:(AddToHand(c.player_id,'missing.forefather'),))
    if mode:
        def watch(c):
            e=c.event
            if mode=='bad_reward':
                return (InvokeBehavior(P+'fail',c.source_id,c.player_id),) if e.target_id is not None and c.state.entities[e.target_id].card_id==CARD else ()
            source=e.source_id
            if source is None or c.state.entities[source].card_id!=CARD:return ()
            if mode=='injure':return (Damage(source,3,c.source_id),)
            if mode=='hand_depart':
                eid=c.state.players[2].hand[0]
                return (DiscardCard(CardReference.capture(c.state.entities[eid]),c.source_id),)
            if mode in ('return','reenter'):
                work=(ReturnToHand(source),)
                return (*work,InvokeBehavior(P+'reenter',c.source_id,c.player_id,source)) if mode=='reenter' else work
            return ()
        event='stats_changed' if mode=='bad_reward' else 'choice_requested'
        r.register_behavior(P+'watch',watch)
        r.register_card(CardDefinition(P+'watch','Observer',CardType.MINION,health=20,triggers=(TriggerSpec(event,P+'watch'),)))
    return r


class FuturisticForefatherTests(unittest.TestCase):
    def game(self, hand=(P+'a',), original=DEFAULT_DECK, *, mode=None, known=True, budget=None):
        self.mode=mode
        context=GenerationContext('forefather-test','experimental',starting_decks=((CARD,P+'filler'),tuple(original))) if known else None
        board=(P+'watch',) if mode else ()
        rules=Ruleset(max_choice_options=budget) if budget is not None else None
        return Game.from_scenario(Scenario((PlayerSetup(P+'hero',hand=(CARD,),board=board,deck=(P+'filler',)*5,
            mana=20,max_mana=20,mana_cap=20),PlayerSetup(P+'hero',hand=hand,deck=(P+'filler',)*5,
            mana=20,max_mana=20,mana_cap=20)),seed=268,generation_context=context),registry(mode),ruleset=rules)
    def play(self,g):
        eid=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==CARD)
        g.apply(PlayCard(1,eid));return eid
    def material(self,g):return json.loads(g.state.pending_choice.options[0].id)['material']
    def right(self,g):
        m=self.material(g);ref=next(x['card'] for x in m['hand'] if x['card']['entity_id']==m['chosen_id'])
        return next(o.id for o in g.state.pending_choice.options if o.card_id==ref['card_id'])
    def select(self,g,right=True):
        q=g.state.pending_choice;correct=self.right(g)
        option=correct if right else next(o.id for o in q.options if o.id!=correct)
        g.apply(SelectChoice(q.player_id,q.id,(option,)))
    def portable(self,g):
        saved=json.loads(json.dumps(g.snapshot()));reader=registry(self.mode)
        other=Game.from_snapshot(saved,reader)
        self.assertEqual(other.snapshot(),saved);self.assertEqual(g.clone().snapshot(),saved)
        self.assertEqual(replay(build_replay(g),reader).snapshot(),saved)
        for p in (1,2):
            public=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
            for key in ('chosen_id','entry_id','material','original_deck','decoys','rng_state','resolution_frame'):
                self.assertNotIn('"'+key+'"',public)
        return other

    def test_a00_complete_original_body_metadata_and_taunt_are_registered(self):
        d=load_batch();row,=d['cards'];r=build_registry();card=r.card(CARD)
        self.assertEqual(canonical_digest(row['record']),row['record_sha256'])
        self.assertEqual((card.cost,card.attack,card.health,card.keywords),(4,4,4,(Keyword.TAUNT,)))
        self.assertEqual(card.metadata,metadata_from_record(row['record']))
        self.assertEqual(len(d['official_observations']),2);self.assertFalse(d['cn_calibrated'])

    def test_a01_paid_original_hand_guess_gets_one_health_buff_after_correct_choice(self):
        g=self.game();source=self.play(g)
        self.assertEqual(g.state.players[1].mana,16);self.assertEqual(g.state.entities[source].health,4)
        self.assertEqual(len(g.state.pending_choice.options),3);self.select(g)
        self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health,g.state.entities[source].health),(4,8,8))
        self.assertFalse(any(e.kind=='healed' for e in g.events));self.portable(g)

    def test_a02_wrong_guess_has_no_health_reward(self):
        g=self.game();source=self.play(g);self.select(g,False)
        self.assertEqual(g.state.entities[source].health,4);self.assertIsNone(g.state.pending_choice)

    def test_a03_decoys_use_original_deck_not_current_deck_or_global_pool(self):
        g=self.game(original=(P+'a',P+'b',P+'c'));self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{P+'a',P+'b',P+'c'})
        self.assertNotIn(P+'filler',[o.card_id for o in g.state.pending_choice.options])

    def test_a04_all_current_hand_faces_and_generation_aliases_are_excluded_from_decoys(self):
        g=self.game((P+'a',P+'b'),(P+'a_alias',P+'b_alias',P+'c',P+'d'));self.play(g)
        m=self.material(g);self.assertEqual(set(m['decoys']),{P+'c',P+'d'})
        self.assertEqual(len(m['hand']),2)

    def test_a05_true_weight_is_physical_hand_and_decoys_are_distinct_generation_identities(self):
        original=(P+'a',P+'b',P+'c',P+'c',P+'d',P+'d')
        g=self.game((P+'a',P+'a',P+'b'),original);hand=tuple(g.state.players[2].hand)
        rng=random.Random();rng.setstate(g._rng.getstate());chosen=rng.choice(hand)
        decoys=rng.sample((P+'c',P+'d'),2);faces=[g.state.entities[chosen].card_id,*decoys];rng.shuffle(faces)
        self.play(g);m=self.material(g)
        self.assertEqual(m['chosen_id'],chosen);self.assertEqual(m['faces'],faces)
        self.assertEqual(g._rng.getstate(),rng.getstate())

    def test_a06_generated_hand_face_need_not_belong_to_original_deck(self):
        g=self.game((P+'filler',),(P+'a',P+'b'));self.play(g)
        self.assertEqual({o.card_id for o in g.state.pending_choice.options},{P+'filler',P+'a',P+'b'})
        self.select(g);self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,8)

    def test_b00_empty_hand_does_nothing_without_rng_even_when_origin_is_unavailable(self):
        g=self.game((),known=False);rng=g._rng.getstate();source=self.play(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g._rng.getstate(),rng)
        self.assertEqual(g.state.entities[source].health,4)

    def test_b01_unavailable_original_inventory_is_an_explicit_error_and_full_rollback(self):
        g=self.game(known=False);saved=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'original opponent deck'):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_b02_known_small_original_inventory_uses_the_complete_smaller_offer(self):
        for original,size in (((),1),((P+'a',P+'b'),2)):
            with self.subTest(original=original):
                g=self.game(original=original);self.play(g)
                self.assertEqual(len(g.state.pending_choice.options),size);self.select(g)
                self.assertEqual(g.state.entities[g.state.players[1].board[0]].health,8)

    def test_b03_choice_budget_cannot_silently_shrink_a_real_three_face_offer(self):
        g=self.game(budget=2);saved=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),saved)

    def test_b04_unknown_original_decoy_is_not_trimmed_or_hidden_after_known_candidates(self):
        g=self.game();ref=CardReference.capture(g.state.entities[g.state.players[2].hand[0]])
        with self.assertRaises(UnsupportedDefinitionError):guess_decoys(g.registry,(ref,),(P+'b',P+'c','missing.forefather'))

    def test_c00_private_offer_never_marks_the_actual_hand_slot_or_exposes_truth(self):
        g=self.game((P+'a',P+'b'));self.play(g)
        self.assertTrue(all(o.entity_id is None for o in g.state.pending_choice.options))
        own=g.for_player(1).observe()['observation'];enemy=g.for_player(2).observe()['observation']
        self.assertTrue(all(x.get('card_id') is None for x in own['players'][1]['hand']))
        self.assertFalse((enemy.get('pending_choice') or {}).get('options'))
        self.portable(g);self.select(g)
        own=g.for_player(1).observe()['observation']
        self.assertTrue(all(x.get('card_id') is None for x in own['players'][1]['hand']))

    def test_c01_waiting_restore_clone_and_replay_keep_original_offer_and_rng(self):
        g=self.game();self.play(g);saved=g.snapshot();other=self.portable(g)
        self.assertEqual(other._rng.getstate(),g._rng.getstate())
        self.select(g);self.select(other);self.assertEqual(g.snapshot(),other.snapshot())

    def test_c02_departed_hand_card_does_not_recompute_the_accepted_answer(self):
        g=self.game(mode='hand_depart');source=self.play(g)
        self.select(g);self.assertFalse(g.state.players[2].hand)
        self.assertEqual(g.state.entities[source].health,8);self.portable(g)

    def test_c03_health_gain_preserves_damage_and_is_not_healing(self):
        g=self.game(mode='injure');source=self.play(g)
        self.assertEqual(g.state.entities[source].health,4);self.select(g)
        self.assertEqual((g.state.entities[source].max_health,g.state.entities[source].health),(8,5))
        self.assertFalse(any(e.kind=='healed' for e in g.events))

    def test_c04_original_recipient_departure_or_reentry_cannot_buff_a_new_body(self):
        for mode in ('return','reenter'):
            with self.subTest(mode=mode):
                g=self.game(mode=mode);source=self.play(g);self.select(g)
                self.assertEqual(g.state.entities[source].max_health,4)
                self.assertEqual(g.state.entities[source].zone,Zone.HAND if mode=='return' else Zone.BOARD)

    def test_c05_failed_reward_reaction_rolls_back_only_to_the_original_choice_boundary(self):
        g=self.game(mode='bad_reward');self.play(g);saved=g.snapshot()
        with self.assertRaises(ResolutionError):self.select(g)
        self.assertEqual(g.snapshot(),saved)

    def test_d00_selected_material_rejects_foreign_owner_source_and_changed_original_deck(self):
        g=self.game();source=self.play(g);q=g.state.pending_choice
        for field,value in (('owner_id',1),('source_id',g.state.players[2].hero_id),('original_deck',[P+'a'])):
            with self.subTest(field=field):
                options=[]
                for old in q.options:
                    raw=json.loads(old.id);raw['material'][field]=value
                    options.append(replace(old,id=json.dumps(raw,sort_keys=True)))
                changed=replace(q,options=tuple(options))
                c=RuleContext(g.state,source,1,choice=ChoiceResult(changed,(changed.options[0].id,)))
                with self.assertRaises(ResolutionError):selected_hand_guess(c,g.registry)

    def test_d01_request_codec_and_previous_schema_require_the_current_finite_type(self):
        g=self.game();source=g.state.players[1].hand[0]
        request=GuessOpponentHandCard(1,2,source,'cards.futuristic_forefather.selected')
        codec=FrameCodec(g.mechanics,g.registry,origin_state=g.state)
        self.assertEqual(codec.decode(codec.encode(request)),request)
        with self.assertRaises(ValueError):GuessOpponentHandCard(True,2,source,'body')
        with self.assertRaises(ValueError):GuessOpponentHandCard(1,1,source,'body')
        with self.assertRaises(ValueError):GuessOpponentHandCard(1,2,source,'body','[]')
        self.play(g);saved=deepcopy(g.snapshot());saved['schema_version']=440
        with self.assertRaises(SnapshotError):Game.from_snapshot(saved,registry(self.mode))


if __name__=='__main__':unittest.main()
