"""Real Pocket Dimension stops on every original offered identity, not picks."""
from dataclasses import replace
from functools import lru_cache
import json
from random import Random
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import past_arcane_seen_offers as native
from hs_sim.engine import (CardClass, CardDefinition, CardType, CastSpell, Game, PlayerSetup,
    ResolutionError, Scenario, TriggerSpec)
from hs_sim.engine.discovery import (ContinuePoolDiscovery, DiscoveryPick, ResolvePoolDiscovery,
    seen_offer_finished, validate_batch, validate_selection)
from hs_sim.engine.effects import ChoiceOption, GainArmor, InvokeBehavior, RequestChoice
from hs_sim.engine.model import CardMetadata, ChoicePurpose, CostSpec, Rarity
from hs_sim.engine.pools import (DiscoverFromPool, GenerationContext, PoolCard, PoolDefinition,
    PoolMember, resolve_candidates, sample_candidates)
from hs_sim.engine.representative import build_registry as build_representative_registry
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import TargetValidationError
from tools import card_batch as batch

CARD = native.CARD
P = 'k598.'
SPELLS = tuple(P+str(i)for i in range(8))
AUTO, ORDINARY, WAIT, FAULT, FAIL = (P+n for n in ('auto','ordinary','wait','fault','fail'))
CTX = GenerationContext('k598-explicit-complete-diagnostic-domain','experimental')
META = CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,tribes=(),factions=(),subtypes=())


@lru_cache(None)
def registry(mode='single',role='writer'):
    r = build_representative_registry(); native.register_past_arcane_seen_offers(r)
    def fail(c):raise ResolutionError('K598 deliberate discovery delivery failure')
    def watch(c):
        e = c.event; source = c.state.entities.get(e.source_id)
        if source is None or source.card_id != CARD or e.player_id != c.player_id:return ()
        if c.source.card_id == FAIL:return (InvokeBehavior(FAULT,c.source_id,c.player_id),)
        return (RequestChoice(c.player_id,(ChoiceOption('continue','Continue'),
            ChoiceOption('fault','Fail',(InvokeBehavior(FAULT,c.source_id,c.player_id),))),c.source_id),)
    r.register_behavior(FAULT,fail);r.register_behavior(P+'watch',watch)
    for cid in (WAIT,FAIL):r.register_card(CardDefinition(cid,cid,CardType.MINION,health=10,
        triggers=(TriggerSpec('card_added_to_hand',P+'watch'),)))
    for cid in SPELLS:
        r.register_behavior(cid,lambda c:(GainArmor(c.player_id,1),))
        card = CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=META)
        r.register_card(card)
        r.register_pool_card(replace(PoolCard.from_definition(card),identity=P+'alias')
            if mode == 'alias' and cid in SPELLS[:2] else PoolCard.from_definition(card))
    for cid,body in ((AUTO,lambda c:(CastSpell(c.player_id,CARD,c.source_id),)),
            (ORDINARY,lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',native.QUERY,source_id=c.source_id),))):
        r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    members = () if mode == 'empty' else SPELLS if mode in ('eight','alias') else SPELLS[:1]
    if mode == 'missing':
        r.register_pool_card(PoolCard(P+'unknown',CardType.SPELL,1,META));members = (*members,P+'unknown')
    r.register_pool(PoolDefinition('constructed.cards',P+'complete-domain-v1',CTX.target_id,CTX.mode,
        tuple(PoolMember(cid)for cid in (*members,CARD)),complete=True))
    r.validate();return r


class PastArcaneSeenOfferTests(CardBatchTestMixin,unittest.TestCase):
    mode = 'single'
    registry_factory = staticmethod(registry)

    def game(self,hand=(CARD,),*,mode='single',player=1,seed=598,board=()):
        self.mode = mode
        players = tuple(PlayerSetup('HERO_03',hand=hand if p == player else (),
            board=board if p == player else (),mana=20,max_mana=20,mana_cap=20)for p in (1,2))
        return Game.from_scenario(Scenario(players,active_player=player,seed=seed,generation_context=CTX),registry(mode))

    def pick(self,g,index=0):
        q = g.state.pending_choice;self.assertEqual(q.purpose,ChoicePurpose.POOL_DISCOVERY)
        cid = q.options[index].card_id;self.choose(g,q.options[index].id);return cid

    def rows(self,g):return tuple(x for x in g.state.card_discovery_history if x.result.choice.source_id is not None
        and g.state.entities[x.result.choice.source_id].card_id == CARD)

    def plan(self,mode,seed,rounds=3):
        r = registry(mode);rng = Random(seed)
        pool = resolve_candidates(r,CTX,'constructed.cards',native.QUERY,current_class=CardClass.ROGUE,
            source_card_id=CARD,player_id=1,exclude_source_by_rule=True)
        return tuple(sample_candidates(rng,pool,3,replacement=False)for _ in range(rounds))

    def seed(self,condition):
        for seed in range(1000):
            plan = self.plan('eight',seed)
            if condition(plan):return seed,plan
        self.fail('The complete finite diagnostic pool had no requested deterministic menu pattern')

    def test_complete_real_source_and_two_primary_faces_no_new_root(self):
        data = native.load_batch();self.assertEqual((len(data['dependencies']),len(data['official_observations'])),(1,2))
        raw = data['dependencies'][0]['record']
        for obs in data['official_observations']:batch.check_face(raw,obs['face'],obs['locale'])
        self.assertEqual((registry().card(CARD).cost,native.COLLECTIBLE_ROOTS),(4,()))

    def test_paid_real_entry_both_actors_second_seen_menu_is_still_delivered(self):
        for player in (1,2):
            g = self.game(player=player);source = self.play(g,CARD,player=player)
            self.assertEqual((g.state.players[player].mana,g.state.play_history[-1].cost),(16,4))
            self.assertEqual([o.card_id for o in g.state.pending_choice.options],[SPELLS[0]])
            self.pick(g);self.assertIsNotNone(g.state.pending_choice);self.pick(g)
            self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.rows(g)),2)
            entities = [g.state.entities[i]for i in g.state.players[player].hand]
            self.assertEqual([e.card_id for e in entities],[SPELLS[0]]*2)
            self.assertEqual(len({e.id for e in entities}),2)
            self.assertTrue(all(x.result.choice.source_id == source for x in self.rows(g)))
            self.portable(g)

    def test_unselected_original_offer_ends_repeat_even_when_neither_pick_repeats(self):
        seed,plan = self.seed(lambda p:bool(set(p[0])&set(p[1]))and bool(set(p[0])-set(p[1]))and bool(set(p[1])-set(p[0])))
        g = self.game(mode='eight',seed=seed);self.play(g,CARD)
        self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),plan[0])
        first = next(c for c in plan[0]if c not in plan[1]);self.choose(g,next(o.id for o in g.state.pending_choice.options if o.card_id == first))
        other = self.portable(g);self.assertEqual(tuple(o.card_id for o in other.state.pending_choice.options),plan[1])
        last = next(c for c in plan[1]if c not in plan[0]);self.choose(other,next(o.id for o in other.state.pending_choice.options if o.card_id == last))
        self.assertIsNone(other.state.pending_choice)
        self.assertEqual([x.result.selected[0].card_id for x in self.rows(other)],[first,last]);self.portable(other)

    def test_three_genuine_menus_keep_every_prior_offer_and_stop_without_extra_rng(self):
        seed,plan = self.seed(lambda p:not(set(p[0])&set(p[1])))
        g = self.game(mode='eight',seed=seed);self.play(g,CARD)
        for n in range(3):
            self.assertEqual(tuple(o.card_id for o in g.state.pending_choice.options),plan[n])
            saved_rng = g._rng.getstate();self.pick(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.rows(g)),3)
        self.assertEqual(g._rng.getstate(),saved_rng)
        self.assertEqual([tuple(o.card_id for o in row.result.choice.options)for row in self.rows(g)],list(plan));self.portable(g)

    def test_alias_faces_share_one_seen_generation_identity(self):
        seed = next(s for s in range(1000)if set(self.plan('alias',s)[0])&set(self.plan('alias',s)[1]))
        g = self.game(mode='alias',seed=seed);self.play(g,CARD)
        for _ in range(10):
            if g.state.pending_choice is None:break
            offered = g.state.pending_choice.options
            identities = [g.registry.pool_card(o.card_id).generation_identity for o in offered]
            self.assertEqual(len(set(identities)),len(offered));self.pick(g)
        rows = self.rows(g);self.assertIsNone(g.state.pending_choice)
        picks = tuple(DiscoveryPick(x.result.selected[0].card_id,CardClass.ROGUE,CARD,result=x.result)for x in rows)
        spec = DiscoverFromPool(1,'constructed.cards',native.QUERY,source_id=rows[0].result.choice.source_id,repeat_until_seen=True)
        self.assertTrue(seen_offer_finished(g.registry,ContinuePoolDiscovery(spec,picks)));self.portable(g)

    def test_seen_history_is_local_to_each_original_execution_and_ignores_other_discoveries(self):
        g = self.game((ORDINARY,CARD,CARD,SPELLS[0]));self.play(g,ORDINARY);self.pick(g)
        counts = []
        for _ in range(2):
            self.play(g,CARD);self.pick(g);self.assertIsNotNone(g.state.pending_choice);self.pick(g)
            counts.append(len(self.rows(g)))
        self.assertEqual(counts,[2,4]);self.assertEqual(len(g.state.card_discovery_history),5);self.portable(g)

    def test_full_hand_burn_does_not_end_repeat_or_lose_discovery_receipt(self):
        g = self.game((CARD,)+(SPELLS[0],)*9);self.play(g,CARD);self.pick(g)
        self.assertEqual(len(g.state.players[1].hand),10);self.assertIsNotNone(g.state.pending_choice)
        self.pick(g);self.assertIsNone(g.state.pending_choice)
        self.assertEqual((len(g.state.players[1].hand),len(self.rows(g))),(10,2));self.portable(g)

    def test_empty_actual_candidate_pool_ends_without_choice_fatigue_or_rng(self):
        g = self.game(mode='empty');state = g._rng.getstate();self.play(g,CARD)
        self.assertEqual(g._rng.getstate(),state);self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(g.state.card_discovery_history),0);self.assertEqual(len(g.state.draw_history),0);self.portable(g)

    def test_automatic_cast_has_the_same_original_offers_and_no_extra_paid_play(self):
        g = self.game((AUTO,));self.play(g,AUTO)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(len(self.rows(g)),2)
        self.assertTrue(all(g.events[row.selection_event-1].kind == 'spell_choice_automatic'for row in self.rows(g)))
        self.assertEqual([r.card_id for r in g.state.play_history],[AUTO]);self.assertEqual(g.state.players[1].mana,20);self.portable(g)

    def test_each_delivery_wait_restores_original_receipts_and_failed_reaction_rolls_back(self):
        g = self.game(board=(WAIT,));self.play(g,CARD)
        for n in (1,2):
            self.pick(g);self.assertEqual(g.state.pending_choice.purpose,ChoicePurpose.EFFECT)
            self.assertEqual(len(self.rows(g)),n);other = self.portable(g);before = other.snapshot()
            with self.assertRaises(ResolutionError):self.choose(other,'fault')
            self.assertEqual(other.snapshot(),before);self.choose(other);g = other
        self.assertIsNone(g.state.pending_choice);self.portable(g)

    def test_failed_selection_keeps_original_paid_menu_candidates_and_rng(self):
        g = self.game(board=(FAIL,));self.play(g,CARD);before = g.snapshot()
        with self.assertRaises(ResolutionError):self.pick(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.state.players[1].mana,16);self.portable(g)

    def test_completed_seen_batch_cannot_borrow_a_third_menu_or_extra_progress(self):
        g = self.game();source = self.play(g,CARD);self.pick(g);self.pick(g);rows = self.rows(g)
        spec = DiscoverFromPool(1,'constructed.cards',native.QUERY,source_id=source,repeat_until_seen=True)
        picks = tuple(DiscoveryPick(SPELLS[0],CardClass.ROGUE,CARD,result=row.result)for row in rows)
        batch = ContinuePoolDiscovery(spec,picks);validate_batch(g.registry,CTX,batch)
        with self.assertRaises(ValueError):validate_selection(g.registry,CTX,ResolvePoolDiscovery(batch,(SPELLS[0],),
            DiscoveryPick(SPELLS[0],CardClass.ROGUE,CARD)))
        with self.assertRaises(ValueError):validate_batch(g.registry,CTX,ContinuePoolDiscovery(spec,(*picks,picks[-1])))

    def test_finite_seen_profile_rejects_unrelated_delivery_rewards_and_untyped_flag(self):
        spec = DiscoverFromPool(1,'constructed.cards',native.QUERY,source_id=4,repeat_until_seen=True)
        for changes in ({'repeat_until_seen':1},{'discoveries':2},{'delivery':'after_all'},{'count':2},
                {'replacement':False},{'cost':CostSpec(delta=-1)},{'shuffle_unselected_into_deck':True},
                {'query':replace(native.QUERY,class_mode='any')},{'source_id':None},{'destination':'deck'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(spec,**changes)

    def test_missing_executable_candidate_is_rejected_before_rng_without_partial_payment(self):
        g = self.game(mode='missing');before = g.snapshot()
        with self.assertRaises((ResolutionError,ValueError)):self.play(g,CARD)
        self.assertEqual(g.snapshot(),before)

    def test_private_continuation_and_old_schema_are_not_player_contracts(self):
        g = self.game();self.play(g,CARD);self.pick(g);self.portable(g)
        for player in (1,2):
            view = json.dumps(g.for_player(player).observe())
            for field in ('repeat_until_seen','selections','resolution_frame','rng_state','offered_card_ids'):
                self.assertNotIn('"'+field+'"',view)
        old = g.snapshot();old['schema_version'] = SNAPSHOT_SCHEMA_VERSION-1
        with self.assertRaises(ValueError):Game.from_snapshot(old,registry())

    def test_bad_final_metadata_is_rejected_before_any_partial_registration(self):
        r = build_representative_registry();data = native.load_batch();raw = dict(data['dependencies'][0]['record']);raw['cost'] = 5
        changed = dict(data,dependencies=[dict(data['dependencies'][0],record=raw)])
        before = (dict(r.cards),dict(r.pool_cards),dict(r._behaviors))
        with patch.object(native,'load_batch',return_value=changed),self.assertRaises(TargetValidationError):
            native.register_past_arcane_seen_offers(r)
        self.assertEqual((r.cards,r.pool_cards,r._behaviors),before)
