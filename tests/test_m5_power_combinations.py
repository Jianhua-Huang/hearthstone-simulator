"""Multi-power Rewind/lifecycle transactions; internal R-102/R-107/R-108 contract."""
import json
import unittest

from hs_sim.engine import (AddHeroPower, CardDefinition, CardType, CostSpec, EndTurn,
    Game, HeroPowerReference, IllegalAction, Keyword, PaymentType, PlayCard,
    PlayerSetup, Registry, RemoveHeroPower, ResolutionError, Resource, RewindSpec, Scenario,
    SelectChoice, TriggerHeroPower, TriggerSpec, UseHeroPower, Zone, hero_power_references)
from hs_sim.engine.effects import (AddCostModifier, AddToHand, ChoiceOption, Damage,
    DamageBatch, GainArmor, InvokeBehavior, ModifyCost, RandomDamage, RefreshHeroPower,
    ReplaceHero, ReplaceHeroPower, RequestChoice, Summon)
from hs_sim.engine.replay import build_replay, replay


class PowerCombinationTests(unittest.TestCase):
    def setUp(self):
        self.r = Registry('power-combinations-tests-v1')
        for cid in ('hero', 'newhero'):
            self.r.register_card(CardDefinition(cid, cid, CardType.HERO, health=30))
        self.r.register_card(CardDefinition('body', 'body', CardType.MINION, attack=1, health=4))
        self.r.register_card(CardDefinition('retainer', 'retainer', CardType.MINION,
                                            health=4, retain_rewind_outcomes=True))
        self.power('plain', lambda c: [GainArmor(1, 1)], retries=None)
        self.power('rewind', lambda c: [GainArmor(1, 2+c.rewind_attempt)])

    def power(self, cid, fn, retries=1):
        self.r.register_behavior(cid, fn)
        kw = {} if retries is None else dict(keywords=(Keyword.REWIND,), rewind=RewindSpec(retries))
        self.r.register_card(CardDefinition(cid, cid, CardType.HERO_POWER, cost=2, on_use=cid, **kw))

    def script(self, cid, fn):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid))

    def watch(self, cid, event, fn):
        self.r.register_behavior(cid, fn)
        self.r.register_card(CardDefinition(cid, cid, CardType.MINION, health=4,
                                            triggers=(TriggerSpec(event, cid),)))

    def game(self, extras=('rewind',), primary='plain', hand=(), board=(), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hero_power_card_id=primary,
            additional_hero_power_card_ids=extras, hand=hand, board=board, deck=('body',)*4,
            mana=10, max_mana=10, corpses=6), PlayerSetup('hero', hero_power_card_id='plain',
            hand=('body',), board=enemy, deck=('body',)*4)), seed=69), self.r)

    def ids(self, g): return g.state.players[1].hero_power_ids
    def hero(self, g, p=1): return g.state.entities[g.state.players[p].hero_id]
    def use(self, g, index=1): g.apply(UseHeroPower(1, self.ids(g)[index]))
    def choose(self, g, option='retry'):
        c = g.state.pending_choice
        g.apply(SelectChoice(c.player_id, c.id, (option,)))
    def play(self, g, card):
        eid = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
        g.apply(PlayCard(1, eid))
    def ref(self, state, index=1): return hero_power_references(state, 1)[index]
    def own_ref(self, c): return HeroPowerReference.capture(c.state.entities[c.source_id])
    def check(self, g):
        snapshot = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(snapshot, self.r).snapshot(), snapshot)
        self.assertEqual(g.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), snapshot)
    def option(self, c, effects, player=1):
        return RequestChoice(player, (ChoiceOption('go', 'private option', tuple(effects)),), source_id=c.source_id)
    def trigger(self, choices='player'):
        self.script('trigger', lambda c: [TriggerHeroPower(1, c.source_id,
            power=self.ref(c.state), choices=choices)])

    def test_extra_retry_keeps_prior_primary_payment_uses_and_history(self):
        g = self.game(); self.use(g, 0); first = g.state.hero_power_history[0]
        self.use(g); self.check(g); self.choose(g)
        self.assertEqual((g.state.players[1].mana, self.hero(g).armor), (6, 4))
        self.assertEqual([g.state.entities[i].uses_this_turn for i in self.ids(g)], [1, 1])
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2)
        self.assertEqual(g.state.hero_power_history[0], first); self.check(g)

    def test_reversed_order_has_separate_checkpoints_for_same_definition(self):
        g = self.game(primary='rewind'); self.use(g); self.choose(g)
        first = g.state.hero_power_history[0]; self.use(g, 0); self.choose(g, 'keep')
        self.assertEqual(g.state.hero_power_history[0], first)
        self.assertEqual([h.source_id for h in g.state.hero_power_history], list(reversed(self.ids(g))))
        self.assertEqual((self.hero(g).armor, g.state.players[1].mana), (5, 6)); self.check(g)

    def test_single_use_shared_discount_is_not_reissued_by_extra_retry(self):
        self.script('discount', lambda c: [AddCostModifier(1,
            CostSpec(delta=-1, card_types=(CardType.HERO_POWER,)), uses_remaining=1)])
        g = self.game(hand=('discount',)); self.play(g, 'discount'); self.use(g, 0); self.use(g); self.choose(g)
        self.assertEqual([h.cost for h in g.state.hero_power_history], [1, 2])
        self.assertEqual(g.state.players[1].mana, 7)
        self.assertFalse(g.state.players[1].cost_modifiers); self.check(g)

    def test_extra_alternate_payment_and_primary_mana_remain_independent(self):
        for payment in (PaymentType.CORPSES, PaymentType.HEALTH):
            self.script('fee.'+payment.value, lambda c, p=payment: [ModifyCost(self.ref(c.state).entity_id,
                CostSpec(payment=p, card_types=(CardType.HERO_POWER,)))])
        for payment in (PaymentType.CORPSES, PaymentType.HEALTH):
            with self.subTest(payment=payment):
                name = 'fee.'+payment.value
                g = self.game(hand=(name,)); self.play(g, name); self.use(g, 0); self.use(g); self.choose(g)
                self.assertEqual(g.state.players[1].mana, 8)
                self.assertEqual(g.state.hero_power_history[1].payment, payment)
                self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 4 if payment == PaymentType.CORPSES else 6)
                # The prior primary gave one armor, which absorbs health-payment loss.
                self.assertEqual(self.hero(g).health, 29 if payment == PaymentType.HEALTH else 30); self.check(g)

    def test_retry_removes_new_branch_entities_and_never_reuses_their_refs(self):
        self.power('install', lambda c: [AddHeroPower(1, 'plain'), AddToHand(1, 'body')])
        g = self.game(extras=('install',)); original = self.ids(g); self.use(g)
        old = self.ids(g)[-1]; old_ref = g.observe(1)['players'][0]['additional_hero_powers'][-1]['ref']
        hand = g.state.players[1].hand[0]; self.check(g); self.choose(g)
        self.assertEqual(self.ids(g)[:2], original)
        self.assertNotIn(old, g.state.entities); self.assertNotIn(hand, g.state.entities)
        self.assertGreater(self.ids(g)[-1], old)
        self.assertNotEqual(g.observe(1)['players'][0]['additional_hero_powers'][-1]['ref'], old_ref)
        port = g.for_player(1); listing = port.legal_actions(); before = g.snapshot()
        result = port.submit({'revision': listing['revision'], 'action': {'type': 'use_hero_power', 'power': old_ref}})
        self.assertFalse(result['accepted']); self.assertEqual(g.snapshot(), before); self.check(g)

    def test_self_replacement_retries_captured_source_without_replacing_primary(self):
        self.power('replace', lambda c: [ReplaceHeroPower(1, 'plain', power=self.own_ref(c)),
            GainArmor(1, c.rewind_attempt+2)])
        g = self.game(extras=('replace', 'plain')); original = self.ids(g)
        self.use(g); abandoned = self.ids(g)[1]; self.check(g); self.choose(g)
        self.assertEqual((self.ids(g)[0], self.ids(g)[2]), (original[0], original[2]))
        self.assertNotIn(abandoned, g.state.entities)
        self.assertEqual(g.state.entities[original[1]].zone, Zone.GRAVEYARD)
        self.assertEqual((g.state.hero_power_history[0].source_id, self.hero(g).armor), (original[1], 3))
        self.assertEqual(g.state.entities[self.ids(g)[1]].uses_this_turn, 0); self.check(g)

    def test_start_reaction_removes_and_reinstalls_extra_on_each_retry(self):
        self.watch('swap', 'hero_power_started', lambda c: [
            RemoveHeroPower(1, HeroPowerReference.capture(c.state.entities[c.event.source_id])),
            AddHeroPower(1, 'plain')])
        g = self.game(board=('swap',)); source = self.ids(g)[1]; self.use(g)
        abandoned = self.ids(g)[1]; self.check(g); self.choose(g)
        self.assertNotIn(abandoned, g.state.entities)
        self.assertEqual(self.hero(g).armor, 3)
        self.assertEqual(g.state.hero_power_history[0].source_id, source); self.check(g)

    def test_source_removed_during_pending_choice_still_resumes_original_payload(self):
        self.power('removed', lambda c: [RemoveHeroPower(1, self.own_ref(c)),
            self.option(c, [GainArmor(1, c.rewind_attempt+2)])])
        g = self.game(extras=('removed',)); self.use(g); self.check(g)
        self.choose(g, 'go'); self.choose(g); self.check(g); self.choose(g, 'go')
        self.assertEqual(len(self.ids(g)), 1); self.assertEqual(self.hero(g).armor, 3); self.check(g)

    def test_hero_replacement_with_extra_removal_is_inside_retry_checkpoint(self):
        self.power('herochange', lambda c: [ReplaceHero(1, 'newhero', additional_power_policy='remove'),
            GainArmor(1, c.rewind_attempt+2)])
        g = self.game(extras=('herochange', 'plain')); oldhero = self.hero(g).id
        self.use(g); firsthero = self.hero(g).id; self.check(g); self.choose(g)
        self.assertNotIn(firsthero, g.state.entities); self.assertIn(oldhero, g.state.players[1].graveyard)
        self.assertEqual(len(self.ids(g)), 1); self.assertEqual(self.hero(g).armor, 3); self.check(g)

    def test_refresh_of_prior_primary_is_undone_when_retry_omits_it(self):
        self.power('conditional', lambda c: [RefreshHeroPower(1)] if c.rewind_attempt == 0 else [GainArmor(1, 3)])
        g = self.game(extras=('conditional',)); self.use(g, 0); self.use(g)
        self.assertEqual(g.state.entities[self.ids(g)[0]].uses_this_turn, 0); self.choose(g)
        self.assertEqual(g.state.entities[self.ids(g)[0]].uses_this_turn, 1)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 2); self.check(g)

    def test_retained_results_accumulate_new_powers_with_one_manual_charge(self):
        self.power('install', lambda c: [AddHeroPower(1, 'plain'), GainArmor(1, c.rewind_attempt+2)])
        g = self.game(extras=('install',), board=('retainer',)); self.use(g, 0); self.use(g)
        self.assertEqual(len(self.ids(g)), 4); self.assertEqual(self.hero(g).armor, 6)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (6, 2))
        out = g.state.rewind_outcomes[0]
        self.assertEqual((out.power_id, out.completed, out.total, out.finished), (2, 2, 2, True)); self.check(g)

    def test_retained_removed_source_keeps_captured_payload_for_later_results(self):
        self.power('removed', lambda c: ([RemoveHeroPower(1, self.own_ref(c)), AddHeroPower(1, 'plain')]
            if c.rewind_attempt == 0 else [])+[GainArmor(1, c.rewind_attempt+2)])
        g = self.game(extras=('removed',), board=('retainer',)); source = self.ids(g)[1]; self.use(g)
        self.assertEqual(self.hero(g).armor, 5); self.assertEqual(len(self.ids(g)), 2)
        self.assertEqual(g.state.rewind_outcomes[0].source_id, source)
        self.assertEqual(g.state.hero_power_history[0].card_id, 'removed'); self.check(g)

    def test_retained_nested_other_power_captures_each_current_installation(self):
        self.power('child', lambda c: [GainArmor(1, c.rewind_attempt+1)])
        self.power('parent', lambda c: [TriggerHeroPower(1, c.source_id, power=self.ref(c.state, 2)),
            ReplaceHeroPower(1, 'child', power=self.ref(c.state, 2))])
        g = self.game(extras=('parent', 'child'), board=('retainer',)); self.use(g)
        records = g.state.hero_power_history
        self.assertEqual([r.parent_id for r in records], [None, 1, 1])
        self.assertNotEqual(records[1].source_id, records[2].source_id)
        self.assertEqual([o.power_id for o in g.state.rewind_outcomes], [1, 2, 3])
        self.assertEqual(self.hero(g).armor, 6)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (8, 1)); self.check(g)

    def test_retained_nested_choices_restore_each_parent_and_child_boundary(self):
        self.power('child', lambda c: [self.option(c, [GainArmor(1, c.rewind_attempt+1)])])
        self.power('parent', lambda c: [TriggerHeroPower(1, c.source_id, power=self.ref(c.state, 2), choices='player')])
        g = self.game(extras=('parent', 'child'), board=('retainer',)); self.use(g)
        for _ in range(4):
            self.check(g); restored = Game.from_snapshot(g.snapshot(), self.r)
            self.choose(g, 'go'); self.choose(restored, 'go'); self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.hero(g).armor, 6); self.assertIsNone(g.state.pending_choice); self.check(g)

    def test_retained_completed_prior_power_is_not_a_new_child_parent(self):
        g = self.game(primary='rewind', board=('retainer',)); self.use(g, 0); first = g.state.rewind_outcomes[0]
        self.use(g); self.assertEqual(g.state.rewind_outcomes[0], first)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, None])
        self.assertEqual([p.power_id for p in g.state.rewind_outcomes], [1, 2]); self.check(g)

    def test_indirect_extra_choice_has_no_root_checkpoint_and_no_manual_fee(self):
        self.power('choice', lambda c: [self.option(c, [GainArmor(1, 2+c.rewind_attempt)])])
        self.trigger(); g = self.game(extras=('choice',), hand=('trigger',)); self.use(g, 0); self.play(g, 'trigger')
        self.assertIsNone(g.snapshot()['rewind_session']); self.check(g); self.choose(g, 'go')
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (8, 1))
        self.assertEqual(g.state.entities[self.ids(g)[1]].uses_this_turn, 0); self.check(g)

    def test_indirect_retained_random_choices_auto_finish_after_source_removal(self):
        self.power('random', lambda c: ([RemoveHeroPower(1, self.own_ref(c))] if c.rewind_attempt == 0 else [])+
            [RequestChoice(1, tuple(ChoiceOption(str(n), 'private '+str(n), (GainArmor(1, n),))
                for n in (2, 5)), source_id=c.source_id)])
        self.trigger('random'); g = self.game(extras=('random',), board=('retainer',), hand=('trigger',))
        self.play(g, 'trigger'); self.assertIsNone(g.state.pending_choice)
        self.assertEqual(sum(e.kind == 'hero_power_choice_automatic' for e in g.events), 2)
        self.assertEqual(g.state.rewind_outcomes[0].completed, 2)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0); self.check(g)

    def test_indirect_nested_primary_has_explicit_parent_and_zero_manual_uses(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id), GainArmor(1, 2)])
        self.trigger(); g = self.game(extras=('nested',), hand=('trigger',)); self.play(g, 'trigger')
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1])
        self.assertEqual([p.source_id for p in g.state.hero_power_history], [self.ids(g)[1], self.ids(g)[0]])
        self.assertEqual(self.hero(g).armor, 3); self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0); self.check(g)

    def lethal(self, c, seats):
        return DamageBatch(tuple(Damage(c.state.players[p].hero_id, 99, c.source_id) for p in seats))

    def terminal(self, g, seats, retained=False):
        self.assertEqual(g.state.status, 'draw' if len(seats) == 2 else 'finished')
        self.assertEqual(g.state.winner, None if len(seats) == 2 else 3-seats[0])
        self.assertIsNone(g.state.pending_choice); self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertIsNone(g.snapshot()['resolution_frame'])
        self.assertFalse(any(e.kind in ('hero_power_added', 'hero_power_refreshed') for e in g.events))
        self.assertTrue(g.state.hero_power_history[-1].interrupted)
        if retained: self.assertTrue(g.state.rewind_outcomes[-1].interrupted)
        self.check(g)

    def test_lethal_extra_payload_stops_install_refresh_and_indirect_tail(self):
        for seats in ((1,), (2,), (1, 2)):
            self.power('lethal'+str(seats), lambda c, ps=seats: [self.lethal(c, ps), AddHeroPower(1, 'plain'),
                RefreshHeroPower(1), TriggerHeroPower(1, c.source_id)])
        for seats in ((1,), (2,), (1, 2)):
            with self.subTest(seats=seats):
                cid = 'lethal'+str(seats)
                g = self.game(extras=(cid,)); self.use(g); self.terminal(g, seats)
                self.assertEqual(len(g.state.hero_power_history), 1)

    def test_lethal_choice_reaction_stops_selected_effect_and_retained_outcomes(self):
        self.power('choice', lambda c: [self.option(c, [AddHeroPower(1, 'plain'), RefreshHeroPower(1)])])
        for seats in ((1,), (2,), (1, 2)):
            self.watch('lethalchoice'+str(seats), 'choice_selected', lambda c, ps=seats: [self.lethal(c, ps)])
        for seats in ((1,), (2,), (1, 2)):
            with self.subTest(seats=seats):
                cid = 'lethalchoice'+str(seats)
                g = self.game(extras=('choice',), board=('retainer', cid)); self.use(g); self.check(g)
                self.choose(g, 'go'); self.terminal(g, seats, retained=True)
                self.assertEqual(g.state.rewind_outcomes[0].completed, 0)

    def test_lethal_start_reaction_interrupts_both_parent_and_child_history(self):
        self.power('parent', lambda c: [TriggerHeroPower(1, c.source_id, power=self.ref(c.state, 2))])
        self.watch('lethalstart', 'hero_power_trigger_started', lambda c: [self.lethal(c, (2,))])
        g = self.game(extras=('parent', 'rewind'), board=('retainer', 'lethalstart')); self.use(g)
        self.assertTrue(all(p.interrupted for p in g.state.hero_power_history))
        self.assertTrue(all(o.interrupted for o in g.state.rewind_outcomes)); self.terminal(g, (2,), retained=True)

    def test_terminal_second_retained_outcome_preserves_first_completion(self):
        self.power('latelethal', lambda c: [GainArmor(1, 4)] if c.rewind_attempt == 0 else
            [self.lethal(c, (2,)), AddHeroPower(1, 'plain')])
        g = self.game(extras=('latelethal',), board=('retainer',)); self.use(g)
        self.terminal(g, (2,), retained=True)
        self.assertEqual((g.state.rewind_outcomes[0].completed, self.hero(g).armor), (1, 4))

    def test_exception_after_random_install_and_remove_rolls_back_root_transaction(self):
        self.power('bad', lambda c: [RandomDamage(tuple(c.state.players[2].board), 1, c.source_id),
            RemoveHeroPower(1, self.own_ref(c)), AddHeroPower(1, 'plain'), Summon(1, 'unknown')])
        g = self.game(extras=('bad',), enemy=('body', 'body')); self.use(g, 0); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before); self.check(g)

    def test_payment_reaction_failure_restores_power_attachments_and_prior_usage(self):
        self.watch('paymentfail', 'corpses_spent', lambda c: [AddHeroPower(1, 'plain'), Summon(1, 'unknown')])
        self.script('fee', lambda c: [ModifyCost(self.ref(c.state).entity_id,
            CostSpec(payment=PaymentType.CORPSES, card_types=(CardType.HERO_POWER,)))])
        g = self.game(hand=('fee',), board=('paymentfail',)); self.play(g, 'fee'); self.use(g, 0); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.use(g)
        self.assertEqual(g.snapshot(), before); self.check(g)

    def test_choice_reaction_failure_restores_pending_choices_rng_and_power_set(self):
        self.power('choice', lambda c: [self.option(c, [GainArmor(1, 3)])])
        self.watch('badchoice', 'choice_selected', lambda c: [
            RandomDamage(tuple(c.state.players[2].board), 1, c.source_id),
            RemoveHeroPower(1, self.ref(c.state)), AddHeroPower(1, 'plain'), Summon(1, 'unknown')])
        g = self.game(extras=('choice',), board=('badchoice',), enemy=('body',)*2)
        self.use(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'go')
        self.assertEqual(g.snapshot(), before); self.check(g)

    def test_retry_exception_keeps_accepted_branch_and_allows_keep(self):
        self.power('retryfail', lambda c: [AddHeroPower(1, 'plain'),
            Summon(1, 'unknown')] if c.rewind_attempt else [AddHeroPower(1, 'plain')])
        g = self.game(extras=('retryfail',)); self.use(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g)
        self.assertEqual(g.snapshot(), before); self.choose(g, 'keep')
        self.assertEqual(len(self.ids(g)), 3); self.check(g)

    def test_later_retained_choice_failure_preserves_first_outcome_and_pending_boundary(self):
        self.r.register_behavior('fail', lambda c: [Summon(1, 'unknown')])
        self.power('badretained', lambda c: [self.option(c,
            [AddHeroPower(1, 'plain')] + ([InvokeBehavior('fail', c.source_id, 1)] if c.rewind_attempt else []))])
        g = self.game(extras=('badretained',), board=('retainer',)); self.use(g); self.choose(g, 'go')
        self.assertEqual(g.state.rewind_outcomes[0].completed, 1); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'go')
        self.assertEqual(g.snapshot(), before); self.assertEqual(len(self.ids(g)), 3); self.check(g)

    def test_private_choice_and_checkpoint_never_enter_opponent_view(self):
        self.power('private', lambda c: [self.option(c, [ReplaceHeroPower(1, 'plain', power=self.own_ref(c))])])
        g = self.game(extras=('private',)); self.use(g)
        own = g.observe(1); enemy = g.observe(2); text = json.dumps(enemy)
        self.assertIn('private option', json.dumps(own)); self.assertNotIn('private option', text)
        for hidden in ('rewind_session', 'zone_epoch', 'entered_order', 'HeroPowerReference', 'hero_power_history'):
            self.assertNotIn(hidden, text)
        self.assertEqual(g.for_player(2).legal_actions()['actions'],[{'type':'concede'}]); self.check(g)

    def test_opponent_owned_choice_keeps_seat_across_extra_retry(self):
        self.power('enemychoice', lambda c: [self.option(c, [GainArmor(2, c.rewind_attempt+2)], player=2)])
        g = self.game(extras=('enemychoice',)); self.use(g)
        self.assertEqual(g.for_player(1).legal_actions()['actions'],[{'type':'concede'}]); self.choose(g, 'go'); self.choose(g)
        self.assertEqual(g.state.pending_choice.player_id, 2); self.check(g)
        self.choose(g, 'go'); self.assertEqual(self.hero(g, 2).armor, 3); self.check(g)

    def test_removed_last_extra_retains_primary_absence_after_retry(self):
        self.power('last', lambda c: [RemoveHeroPower(1, self.own_ref(c)), GainArmor(1, c.rewind_attempt+2)])
        g = self.game(extras=('last',), primary=None); self.use(g, 0); self.choose(g)
        self.assertEqual(self.ids(g), ()); self.assertIsNone(g.state.players[1].hero_power_id)
        self.assertEqual(self.hero(g).armor, 3); self.check(g)

    def test_next_turn_resets_current_installed_powers_after_retained_installation(self):
        self.power('install', lambda c: [AddHeroPower(1, 'plain')])
        g = self.game(extras=('install',), board=('retainer',)); self.use(g)
        for i in (0, 2, 3): self.use(g, i)
        ids = self.ids(g); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.ids(g), ids)
        self.assertEqual([g.state.entities[i].uses_this_turn for i in ids], [0]*4)
        self.assertEqual(g.state.players[1].hero_power_uses_this_turn, 0); self.check(g)

    def test_rewind_primary_keeps_previously_used_extra_and_its_cost_attachment(self):
        self.script('fee', lambda c: [ModifyCost(self.ref(c.state).entity_id,
            CostSpec(payment=PaymentType.CORPSES, card_types=(CardType.HERO_POWER,)))])
        g = self.game(primary='rewind', extras=('plain',), hand=('fee',)); self.play(g, 'fee'); self.use(g)
        extra = g.state.entities[self.ids(g)[1]]; self.use(g, 0); self.choose(g)
        self.assertEqual(g.state.entities[extra.id], extra)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].resources[Resource.CORPSES]), (8, 4)); self.check(g)

    def test_rewound_primary_replacement_restores_prior_entity_and_consumed_use(self):
        self.power('conditionalreplace', lambda c: [ReplaceHeroPower(1, 'plain', cost=
            CostSpec(payment=PaymentType.CORPSES, card_types=(CardType.HERO_POWER,)))]
            if c.rewind_attempt == 0 else [GainArmor(1, 3)])
        g = self.game(extras=('conditionalreplace',)); self.use(g, 0); primary = g.state.entities[self.ids(g)[0]]
        self.use(g); abandoned = self.ids(g)[0]; self.choose(g)
        self.assertNotIn(abandoned, g.state.entities); self.assertEqual(self.ids(g)[0], primary.id)
        self.assertEqual(g.state.entities[primary.id], primary); self.check(g)

    def test_choice_replacement_leaves_captured_trigger_stale_in_both_retry_branches(self):
        self.power('replacechoice', lambda c: [self.option(c, [ReplaceHeroPower(1, 'plain', power=self.own_ref(c))]),
            TriggerHeroPower(1, c.source_id, power=self.own_ref(c))])
        g = self.game(extras=('replacechoice',)); self.use(g); self.choose(g, 'go'); self.check(g)
        self.choose(g); self.check(g); self.choose(g, 'go')
        self.assertEqual(len(g.state.hero_power_history), 1)
        self.assertEqual(sum(e.kind == 'effect_skipped' for e in g.events), 2); self.check(g)

    def test_root_retry_restores_nested_other_power_history_without_resetting_attempt_policy(self):
        self.power('parent', lambda c: [TriggerHeroPower(1, c.source_id), GainArmor(1, 10+c.rewind_attempt)])
        g = self.game(primary='rewind', extras=('parent',)); self.use(g); self.choose(g)
        self.assertEqual(self.hero(g).armor, 13)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1])
        self.assertEqual([g.state.entities[i].uses_this_turn for i in self.ids(g)], [0, 1]); self.check(g)

    def test_completion_reaction_lethal_keeps_completed_record_without_rewind_offer(self):
        self.watch('endlethal', 'hero_power_used', lambda c: [self.lethal(c, (2,)), AddHeroPower(1, 'plain')])
        g = self.game(board=('endlethal',)); self.use(g)
        record = g.state.hero_power_history[0]
        self.assertTrue(record.completed); self.assertFalse(record.interrupted)
        self.assertIsNone(g.state.pending_choice); self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertFalse(any(e.kind == 'hero_power_added' for e in g.events)); self.check(g)

    def test_representative_player_commands_retry_retain_restore_and_finish(self):
        from examples.power_combinations import run
        game, snapshot = run()
        # One accepted hand minion adds counter-check and accepted-entry facts.
        accepted = [e for e in game.events if e.kind == 'spell_cast_accepted']
        self.assertEqual(len(accepted), 5)
        self.assertEqual([(dict(e.data)['cast_id'], e.source_id, e.target_id, e.player_id) for e in accepted],
            [(r.id, r.source_id, r.target_id, r.player_id) for r in game.state.cast_history])
        self.assertEqual((len(game.history), len(game.events)-len(accepted), game.state.winner), (18, 96, 1))
        self.assertIsNotNone(snapshot['rewind_session'])
        self.assertEqual(game.state.rewind_outcomes[0].completed, 2)


if __name__ == '__main__': unittest.main()
