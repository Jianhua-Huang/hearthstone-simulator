"""Actual Instant Multiverse budgets, native Rewind and original summon outputs."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import random
import unittest

from hs_sim.cards.native_mana_worth_cards import CARD, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, TriggerSpec,
    PlayCard, PlayerSetup, Ruleset, Scenario, SelectChoice, SnapshotError, SummonQuantitySpec, Zone)
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import ChoiceOption, Destroy, InvokeBehavior, RequestChoice
from hs_sim.engine.errors import ResolutionError, ResolutionLimitExceeded
from hs_sim.engine.hero_health_history import effective_events
from hs_sim.engine.mana_worth_summons import (SummonManaWorth, ManaWorthEntryLink,
    ContinueManaWorth, query, validate_queue as validate_budget_queue)
from hs_sim.engine.model import ChoicePurpose
from hs_sim.engine.pools import resolve_candidates, sample_candidates
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial, reject_choice_control
from test_simple_followup_p70_cards import (registry as old_registry, CONTEXT,
    M0, M1, M2, M3, M6, M20, UNKNOWN, YETI, COLOSSAL)

P = 'k162.native.'
WATCH, DOUBLER, AUTO = (P + n for n in ('watch', 'doubler', 'auto'))
MEMBERS = ((M6, 1),)


@lru_cache(maxsize=32)
def registry(role, mode=None, members=MEMBERS):
    assert role in ('writer', 'reader')
    r = old_registry(members=members)
    r.register_card(CardDefinition(DOUBLER, DOUBLER, CardType.MINION, health=30,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_behavior(AUTO, lambda c: (CastSpell(c.player_id, CARD, c.source_id), CastSpell(c.player_id, CARD, c.source_id)))
    r.register_card(CardDefinition(AUTO, AUTO, CardType.SPELL, on_play=AUTO))
    def fail(c): raise ResolutionError('K162 native deliberate failure')
    r.register_behavior(P + 'fail', fail)
    if mode:
        event = 'overload_added' if mode == 'overload' else 'minion_summoned'
        def eligible(c):
            return c.event.player_id == 1 if mode == 'overload' else c.state.entities[c.event.target_id].card_id in (M0, M2, M3, M6, COLOSSAL)
        def watch(c):
            if not eligible(c): return ()
            if mode == 'kill_zero': return (Destroy(c.event.target_id, c.source_id),)
            options = [ChoiceOption('ok', 'Continue'), ChoiceOption('fail', 'Rollback',
                (InvokeBehavior(P + 'fail', c.source_id, c.player_id),))]
            if mode != 'overload':
                options.extend((ChoiceOption('kill', 'Destroy original summoned minion', (Destroy(c.event.target_id, c.source_id),)),
                    ChoiceOption('nested', 'Independent attributed summon', (SummonByCard(1,
                        (SummonEntryMaterial(M1),), SummonCause.capture(c)),))))
            return (RequestChoice(1, tuple(options), c.source_id),)
        r.register_behavior(P + 'watch', watch)
        r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=30,
            triggers=(TriggerSpec(event, P + 'watch'),)))
    r.validate(); r.freeze(); return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class NativeManaWorthTests(unittest.TestCase):
    def game(self, hand=(CARD,), board=(), mode=None, members=MEMBERS, limit=7, steps=10000):
        self.config = mode, members
        return Game.from_scenario(Scenario((PlayerSetup('HERO_10', hand=hand,
            board=((WATCH,) if mode else ()) + board, deck=(YETI,) * 12, mana=40, max_mana=40, mana_cap=40),
            PlayerSetup('HERO_10', deck=(YETI,) * 12)), generation_context=CONTEXT, seed=162),
            registry('writer', mode, members), ruleset=Ruleset(max_board=limit, max_resolution_steps=steps))

    def play(self, g, cid=CARD):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == cid)
        g.apply(PlayCard(1, source)); return source

    def choose(self, g, key='ok'):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def keep(self, g):
        self.assertEqual(g.state.pending_choice.purpose, ChoicePurpose.REWIND); self.choose(g, 'keep')

    def roots(self, g):
        return [r for r in g.state.card_summon_history if type(r.request.producer_link) is ManaWorthEntryLink]

    def count(self, g, cid):
        return sum(g.state.entities[i].card_id == cid for i in g.state.players[1].board)

    def portable(self, g):
        saved = json.loads(json.dumps(g.snapshot())); r = registry('reader', *self.config)
        self.assertIsNot(r, g.registry); self.assertEqual(r.fingerprint(), g.registry.fingerprint())
        other = Game.from_snapshot(saved, r)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), r).snapshot(), saved)
        for pid in (1, 2):
            public = json.dumps(g.for_player(pid).observe()) + json.dumps(g.for_player(pid).legal_actions()) + json.dumps(g.player_events(pid))
            for key in ('remaining', 'previous_root_id', 'pool_basis', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a0_one_complete_raw_and_two_strict_primary_faces(self):
        from tools.card_batch import check_face
        d = load_batch(); raw = d['cards'][0]['record']
        for o in d['official_observations']: check_face(raw, o['face'], o['locale'])
        self.assertEqual(len(d['official_observations']), 2)
        c = registry('writer').card(CARD)
        self.assertEqual((c.cost, c.rewind.retries), (6, 1)); self.assertEqual(raw['tags']['OVERLOAD'], 3)

    def test_a1_actual_native_payment_and_two_six_cost_original_picks(self):
        g = self.game(); source = self.play(g); roots = self.roots(g)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (34, 3))
        self.assertEqual(self.count(g, M6), 2); self.assertEqual(len(roots), 2)
        self.assertEqual([r.request.producer_link.remaining for r in roots], [12, 6])
        self.assertEqual([r.request.producer_link.previous_root_id for r in roots], [None, roots[0].id])
        self.assertTrue(all(r.request.cause.source.entity_id == source and r.request.cause.cast_card_id == CARD for r in roots))
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history)), (1, 1))
        self.keep(g); self.portable(g)

    def test_a2_weighted_each_pick_uses_remaining_printed_budget_and_exact_rng(self):
        members = ((M3, 1), (M6, 2)); g = self.game(members=members); rng = random.Random(); rng.setstate(g._rng.getstate())
        remaining, expected = 12, []
        while remaining:
            candidates = resolve_candidates(g.registry, CONTEXT, 'constructed.cards', query(remaining), player_id=1, source_card_id=CARD)
            cid = sample_candidates(rng, candidates, 1, replacement=True)[0]
            expected.append(cid); remaining -= g.registry.pool_card(cid).cost
        self.play(g)
        actual = [r.request.materials[r.selected].card_id for r in self.roots(g)]
        self.assertEqual(actual, expected); self.assertEqual(g._rng.getstate(), rng.getstate())
        self.assertEqual(sum(g.registry.pool_card(cid).cost for cid in actual), 12)
        self.keep(g); self.portable(g)

    def test_b0_full_or_empty_eligible_pool_keeps_empty_root_without_rng_and_still_overloads(self):
        for board, members in (((M1,) * 7, MEMBERS), ((), ((M20, 1),))):
            with self.subTest(full=bool(board)):
                g = self.game(board=board, members=members); rng = g._rng.getstate(); self.play(g)
                root, = self.roots(g); self.assertIsNone(root.selected); self.assertEqual(root.status, 'skipped')
                self.assertEqual(g._rng.getstate(), rng); self.assertEqual(g.state.players[1].overload_owed, 3)
                self.keep(g); self.portable(g)

    def test_b1_unknown_eligible_pool_is_not_removed_even_when_board_is_full(self):
        for board in ((), (M1,) * 7):
            g = self.game(board=board, members=((UNKNOWN, 1),)); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g)
            self.assertEqual(g.snapshot(), saved)

    def test_b2_zero_cost_picks_stop_at_actual_custom_capacity_without_spending_budget(self):
        g = self.game(members=((M0, 1),), limit=3); self.play(g); roots = self.roots(g)
        self.assertEqual(self.count(g, M0), 3); self.assertEqual(len(roots), 4)
        self.assertTrue(all(r.request.producer_link.remaining == 12 for r in roots))
        self.assertIsNone(roots[-1].selected); self.assertEqual(roots[-1].rng_before, roots[-1].rng_after)
        self.keep(g); self.portable(g)

    def test_b3_zero_cost_minions_dying_on_entry_use_shared_resolution_limit_and_rollback(self):
        g = self.game(mode='kill_zero', members=((M0, 1),), steps=120); saved = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.play(g)
        self.assertEqual(g.snapshot(), saved)

    def test_c0_actual_colossal_entries_charge_only_each_original_six_cost_body(self):
        g = self.game(members=((COLOSSAL, 1),)); self.play(g); roots = self.roots(g)
        self.assertEqual(self.count(g, COLOSSAL), 2); self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(len(g.state.colossal_history), 2); self.assertEqual(len(roots), 2)
        self.assertEqual([r.request.producer_link.remaining for r in roots], [12, 6])
        self.keep(g); self.portable(g)

    def test_c1_quantity_extra_bodies_do_not_spend_additional_printed_budget(self):
        g = self.game(board=(DOUBLER,)); self.play(g); roots = self.roots(g)
        self.assertEqual(len(roots), 2); self.assertEqual([r.plan.total for r in roots], [2, 2])
        self.assertEqual(self.count(g, M6), 4); self.assertEqual(len(g.state.players[1].board), 5)
        self.keep(g); self.portable(g)

    def test_d0_waiting_original_delivery_death_does_not_refund_budget_and_failed_resume_rolls_back(self):
        g = self.game(mode='summon'); self.play(g); saved = g.snapshot(); other = self.portable(g)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g, 'kill'); self.choose(other, 'kill'); self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual([r.request.producer_link.remaining for r in self.roots(g)], [12, 6])
        self.choose(g); self.choose(other); self.assertEqual(self.count(g, M6), 1)
        self.keep(g); self.keep(other); self.assertEqual(other.snapshot(), g.snapshot()); self.portable(g)

    def test_d1_unrelated_nested_summon_cannot_become_a_budget_pick(self):
        g = self.game(mode='summon'); self.play(g); self.choose(g, 'nested'); self.choose(g)
        self.assertEqual(len(g.state.card_summon_history), 3); self.assertEqual(len(self.roots(g)), 2)
        self.assertEqual((self.count(g, M6), self.count(g, M1)), (2, 1))
        self.keep(g); self.portable(g)

    def test_e0_two_actual_automatic_casts_have_independent_budgets_and_no_manual_rewind(self):
        g = self.game(hand=(AUTO,)); self.play(g, AUTO); roots = self.roots(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.count(g, M6), 4)
        self.assertEqual([r.request.producer_link.remaining for r in roots], [12, 6, 12, 6])
        self.assertEqual(len({r.request.cause.cast_id for r in roots}), 2)
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history), g.state.players[1].overload_owed), (1, 3, 6))
        self.portable(g)

    def test_e1_real_rewind_retires_original_roots_and_overload_but_keeps_one_payment(self):
        g = self.game(); self.play(g); first_ids = {r.id for r in self.roots(g)}; self.portable(g)
        self.choose(g, 'retry'); roots = self.roots(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.count(g, M6), 2)
        self.assertTrue(first_ids.isdisjoint(r.id for r in roots))
        self.assertEqual([r.request.producer_link.remaining for r in roots], [12, 6])
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (34, 3))
        self.assertEqual((len(g.state.play_history), len(g.state.cast_history), len(g.state.overload_history)), (1, 1, 1))
        self.assertEqual(len([e for e in g.events if e.kind == 'overload_added']), 2)
        self.assertEqual(len([e for e in effective_events(g.events) if e.kind == 'overload_added']), 1)
        self.portable(g)

    def test_f0_strict_budget_link_and_control_codec_reject_unknown_original_work(self):
        g = self.game(); self.play(g); root = self.roots(g)[0]
        values = (root.request.producer_link, ContinueManaWorth(root.id), SummonManaWorth(1, 'constructed.cards', 12, root.request.cause))
        codec = FrameCodec(g.mechanics, g.registry)
        for value in values: self.assertEqual(codec.decode(json.loads(json.dumps(codec.encode(value)))), value)
        for args in ((True, 12), (12, 13), (12, 0), (12, 6), (12, 6, 0)):
            with self.assertRaises(ValueError): ManaWorthEntryLink(*args)
        with self.assertRaises(ValueError): reject_choice_control((ChoiceOption('bad', 'Injected', (ContinueManaWorth(root.id),)),))
        self.keep(g); self.portable(g)

    def test_f1_waiting_budget_cannot_drop_duplicate_or_rewrite_its_original_continuation(self):
        g = self.game(mode='summon'); self.play(g); frame = g._frame
        from hs_sim.engine.summon_quantities import walk_work
        work = tuple(walk_work((*frame.prefix, *frame.continuation)))
        controls = [w for w in work if type(w) is ContinueManaWorth]
        self.assertEqual(len(controls), 1)
        with self.assertRaises(ValueError): validate_budget_queue(g.state, g.registry, [w for w in work if type(w) is not ContinueManaWorth])
        with self.assertRaises(ValueError): validate_budget_queue(g.state, g.registry, (*work, controls[0]))
        saved = g.snapshot()
        for change in ('remainder', 'remove_link', 'future_previous'):
            bad = deepcopy(saved); request = bad['state']['card_summon_history'][0]['request']
            if change == 'remainder': request['producer_link']['remaining'] = 11
            elif change == 'remove_link': request['producer_link'] = None
            else: request['producer_link']['previous_root_id'] = 100000
            with self.subTest(change=change), self.assertRaises(SnapshotError): Game.from_snapshot(rehash(bad), registry('reader', *self.config))
        self.portable(g)

    def test_g0_native_overload_wait_restores_completed_budget_and_failed_choice_boundary(self):
        g = self.game(mode='overload'); self.play(g); saved = g.snapshot(); other = self.portable(g)
        self.assertEqual(len(self.roots(g)), 2); self.assertEqual(g.state.players[1].overload_owed, 3)
        with self.assertRaises(ResolutionError): self.choose(g, 'fail')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g); self.choose(other); self.keep(g); self.keep(other)
        self.assertEqual(other.snapshot(), g.snapshot()); self.portable(g)
