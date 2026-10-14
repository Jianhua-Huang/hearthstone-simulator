"""Paid Spell cost origins, complete saved windows and actual closing guards."""
from copy import deepcopy
from dataclasses import replace
import unittest

import test_m5_spell_repeats as foundation
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, CostSpec,
    Game, Keyword, PaymentType, PlayCard, RepeatCostFilter, RepeatMatchSpec,
    RewindSpec, SnapshotError, SpellRepeatSpec, TriggerSpec)
from hs_sim.engine.effects import (AddCostModifier, ChoiceOption, Damage, Destroy,
    GainArmor, ModifyCost, RandomDamage, RequestChoice, Silence)
from hs_sim.engine.model import Zone
from hs_sim.engine.registry import RuleContext
from hs_sim.engine.resolver import FinishPlay, PlayFromHand
from hs_sim.engine.spell_acceptance import (FinishSpellAcceptance, _bind_live,
    capture_submission, validate_acceptance, validate_history, validate_queue)
from hs_sim.engine.spell_cost_proof import (validate_hand_cost_proof,
    validate_hand_cost_proof_live)
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.replay import build_replay, replay


class SpellCostAcceptanceTests(unittest.TestCase):
    minion = foundation.SpellRepeatTests.minion
    spell = foundation.SpellRepeatTests.spell
    game = foundation.SpellRepeatTests.game
    play = foundation.SpellRepeatTests.play
    hero = foundation.SpellRepeatTests.hero
    choose = foundation.SpellRepeatTests.choose
    events = foundation.SpellRepeatTests.events

    @staticmethod
    def fee(basis='submitted_quote', maximum=2, casts=2, **kwargs):
        profile = 'repeat.cost.accepted_hand' if basis == 'window_quote' else None
        return SpellRepeatSpec(casts, 'any', RepeatMatchSpec(
            recipient_cost=RepeatCostFilter(basis, maximum=maximum,
                                            quote_profile_id=profile, **kwargs)))

    def setUp(self):
        foundation.SpellRepeatTests.setUp(self)
        self.spell('fee.ask', self.ask, cost=3)
        self.spell('fee.hit', lambda c: [GainArmor(c.player_id, 1)], cost=3)
        self.r.register_card(CardDefinition('fee.empty', 'Empty', CardType.SPELL, cost=3,
            metadata=CardMetadata(False, (CardClass.MAGE,), None)))
        self.spell('fee.fatal', lambda c: [Damage(c.state.players[2].hero_id, 50, c.source_id)], cost=3)
        self.granter('fee.prepare', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.SPELL,)), uses_remaining=1),
            AddSpellRepeatModifier(1, self.fee(), uses=2),
            AddSpellRepeatModifier(1, self.fee('window_quote', casts=4), uses=2)))
        self.granter('fee.twice', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.SPELL,)), uses_remaining=2),))
        self.granter('fee.health', (AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH,
            card_types=(CardType.SPELL,))), GainArmor(1, 2)))
        self.granter('fee.false', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.MINION,)), uses_remaining=2),))
        self.minion('fee.board', health=5, spell_repeats=(self.fee(casts=3),))
        self.minion('fee.false.board', health=5, spell_repeats=(self.fee(maximum=0, casts=4),))
        self.minion('fee.retainer', health=5, retain_rewind_outcomes=True)

    def granter(self, name, effects):
        self.r.register_behavior(name, lambda c: list(effects))
        self.minion(name, health=4, battlecry=name)

    @staticmethod
    def ask(c):
        return [RequestChoice(c.player_id, (ChoiceOption('ok', 'OK',
            (GainArmor(c.player_id, 1),)),), source_id=c.source_id)]

    def ready(self, grant=None, hand=('fee.ask',), board=()):
        g = self.game(hand=((*((grant,) if grant else ()), *hand)), board=board)
        if grant: self.play(g, grant)
        return g

    @staticmethod
    def proof(g):
        return next(w for w in (*g._frame.prefix, *g._frame.continuation)
                    if type(w) is FinishSpellAcceptance)

    def portable(self, g, registry=None):
        registry = self.r if registry is None else registry
        snap = g.snapshot()
        self.assertEqual(Game.from_snapshot(snap, registry).snapshot(), snap)
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry).snapshot(), snap)

    def complete(self, g):
        while g.state.pending_choice:
            self.choose(g, 'ok')

    def waiting(self, grant=None, board=()):
        g = self.ready(grant, board=board); self.play(g, 'fee.ask')
        self.assertIsNotNone(g.state.pending_choice)
        validate_acceptance(self.proof(g), self.r)
        return g

    def test_submitted_quote_keeps_last_discount_after_both_window_prices_rise(self):
        g = self.waiting('fee.prepare')
        p = g.state.play_history[-1]
        self.assertEqual((p.submitted_cost.printed_cost, p.submitted_cost.quote.local_amount,
                          p.cost, p.spell_submission.cost_facts.window_quotes[0].amount), (3, 3, 1, 3))
        self.assertEqual(p.spell_payload.casts, 2)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].spell_modifiers], [1, 2])
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.portable(g); self.complete(g)
        self.assertEqual(self.hero(g).armor, 2)
        self.assertEqual(len([x for x in g.state.cost_use_history if x.source_card_id == 'fee.ask']), 1)

    def test_two_global_finite_cost_uses_are_exact_and_third_root_unmodified(self):
        g = self.ready('fee.twice', hand=('fee.hit',)*3)
        for _ in range(3): self.play(g, 'fee.hit')
        roots = [p for p in g.state.play_history if p.kind == CardType.SPELL]
        self.assertEqual([p.cost for p in roots], [1, 1, 3])
        rows = [r for r in g.state.cost_use_history if r.source_card_id == 'fee.hit']
        self.assertEqual([r.player_modifiers[0].uses_remaining for r in rows[:2]], [2, 1])
        self.assertFalse(rows[2].player_modifiers); self.portable(g)

    def test_nonmatching_cost_policy_and_repeat_policy_have_separate_clocks(self):
        g = self.waiting('fee.false', board=('fee.false.board',))
        self.assertEqual(g.state.play_history[-1].cost, 3)
        self.assertEqual(g.state.play_history[-1].spell_payload.casts, 1)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 2)
        self.portable(g)

    def test_zero_price_consumes_all_cost_and_nonmax_repeat_sources_once(self):
        self.spell('fee.zero.ask', self.ask, cost=1)
        self.minion('fee.lower.board', health=5, spell_repeats=(self.fee(casts=2),))
        self.granter('fee.zero.prepare', (
            AddCostModifier(1, CostSpec(delta=-1, card_types=(CardType.SPELL,)), uses_remaining=2),
            AddCostModifier(1, CostSpec(delta=-2, card_types=(CardType.SPELL,)), uses_remaining=1),
            AddSpellRepeatModifier(1, self.fee(casts=2), uses=1),
            AddSpellRepeatModifier(1, self.fee('printed', maximum=0, casts=4), uses=2)))
        g = self.ready('fee.zero.prepare', hand=('fee.zero.ask',), board=('fee.lower.board', 'fee.board'))
        self.play(g, 'fee.zero.ask'); p = g.state.play_history[-1]
        self.assertEqual((p.cost, p.spell_payload.casts), (0, 3))
        self.assertEqual([s.ability.spell_repeat.casts for s in p.spell_payload.contributors], [2, 3])
        self.assertEqual([m.spec.casts for m in p.spell_submission.modifiers], [2])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].cost_modifiers], [1])
        self.assertEqual([m.uses_remaining for m in g.state.players[1].spell_modifiers], [2])
        row = g.state.cost_use_history[-1]
        self.assertEqual([m.uses_remaining for m in row.player_modifiers], [2, 1])
        self.assertEqual(len(row.modifier_ids), 2); self.assertEqual(len(row.consumable_ids), 2)
        waiting = 0
        while g.state.pending_choice:
            self.portable(g); waiting += 1; self.choose(g, 'ok')
        self.assertEqual(waiting, 3)
        self.assertEqual(len([r for r in g.state.cost_use_history if r.source_id == p.source_id]), 1)
        self.assertEqual(len([e for e in self.events(g, 'mana_spent') if e.source_id == p.source_id]), 1)
        self.portable(g)

    def test_real_payment_reaction_changes_late_price_without_reconsuming_saved_policy(self):
        self.spell('fee.payment.ask', self.ask, cost=1)
        self.granter('fee.payment.prepare', (
            AddSpellRepeatModifier(1, self.fee('window_quote', casts=2), uses=2),))
        self.minion('fee.window.board', health=5, spell_repeats=(self.fee('window_quote', casts=3),))
        def paid(c):
            if not c.event.source_id or c.state.entities[c.event.source_id].card_id != 'fee.payment.ask': return []
            self.assertFalse(any(p.source_id == c.event.source_id for p in c.state.play_history))
            self.assertEqual(c.state.entities[c.event.source_id].zone, Zone.HAND)
            return [AddCostModifier(1, CostSpec(delta=2, card_types=(CardType.SPELL,))),
                RequestChoice(1, (ChoiceOption('ok', 'Continue after payment reaction', ()),), source_id=c.source_id)]
        self.r.register_behavior('fee.payment.watch', paid)
        self.minion('fee.payment.watch', health=5, triggers=(TriggerSpec('mana_spent', 'fee.payment.watch'),))
        g = self.ready('fee.payment.prepare', hand=('fee.payment.ask',), board=('fee.payment.watch', 'fee.window.board'))
        self.play(g, 'fee.payment.ask'); p = g.state.play_history[-1]
        self.assertIsNone(self.proof(g).resolution)
        self.assertEqual(p.spell_submission.cost_facts.window_quotes[0].amount, 1)
        self.portable(g); self.choose(g, 'ok'); p = g.state.play_history[-1]
        self.assertEqual((p.cost, p.spell_payload.cost_facts.window_quotes[0].amount, p.spell_payload.casts), (1, 3, 2))
        self.assertFalse(p.spell_payload.contributors)
        self.assertEqual(g.state.players[1].spell_modifiers[0].uses_remaining, 1)
        self.portable(g); self.complete(g)
        self.assertEqual(self.hero(g).armor, 2); self.portable(g)

    def test_prepared_quote_proof_binds_original_full_input(self):
        g = self.waiting(); proof = self.proof(g)
        bad = deepcopy(proof.cost_proof); bad.payment_state.entities[bad.prepared_play.source_id].base_cost = 2
        with self.assertRaises(ValueError): validate_hand_cost_proof(bad, self.r)
        self.assertEqual(g.snapshot(), g.clone().snapshot())

    def test_same_numeric_quote_cannot_hide_mutated_false_cost_source(self):
        g = self.waiting('fee.false'); proof = self.proof(g)
        bad = deepcopy(proof)
        m = bad.cost_proof.payment_state.players[1].cost_modifiers[0]
        bad.cost_proof.payment_state.players[1].cost_modifiers[0] = replace(m, uses_remaining=1)
        with self.assertRaises(ValueError): validate_acceptance(bad, self.r)
        validate_acceptance(proof, self.r)

    def test_payment_projection_rejects_postpay_resource_rewrite(self):
        g = self.waiting(); proof = self.proof(g)
        bad = deepcopy(proof.submission.state); bad.players[1].mana_spent += 1
        with self.assertRaises(ValueError):
            validate_hand_cost_proof(proof.cost_proof, self.r, submission_state=bad)
        validate_hand_cost_proof(proof.cost_proof, self.r, submission_state=proof.submission.state)

    def test_payment_projection_rejects_missing_global_use_receipt(self):
        g = self.waiting('fee.prepare'); proof = self.proof(g)
        bad = deepcopy(proof.submission.state); bad.cost_use_history.pop()
        with self.assertRaises(ValueError):
            validate_hand_cost_proof(proof.cost_proof, self.r, submission_state=bad)

    def test_postpay_window_cannot_resurrect_consumed_discount(self):
        g = self.waiting('fee.prepare'); proof = self.proof(g)
        bad = deepcopy(proof.submission.state)
        bad.players[1].cost_modifiers = deepcopy(proof.cost_proof.payment_state.players[1].cost_modifiers)
        with self.assertRaises(ValueError):
            validate_hand_cost_proof(proof.cost_proof, self.r, submission_state=bad)

    def test_cost_source_id_cannot_cross_player_after_original_false_window(self):
        g = self.waiting('fee.false'); proof = self.proof(g)
        bad = deepcopy(g.state); bad.players[2].cost_modifiers.append(bad.players[1].cost_modifiers.pop())
        with self.assertRaises(ValueError): _bind_live(bad, proof, self.r)
        _bind_live(g.state, proof, self.r)

    def test_frozen_false_repeat_source_cannot_change_after_physical_removal(self):
        self.spell('fee.remove', lambda c: [Destroy(c.state.players[1].board[0]), *self.ask(c)], cost=3)
        g = self.ready(hand=('fee.remove',), board=('fee.false.board',)); self.play(g, 'fee.remove')
        proof = self.proof(g); self.assertFalse(g.state.players[1].board)
        bad = deepcopy(proof); source = next(e for e in bad.resolution.state.entities.values()
            if e.card_id == 'fee.false.board')
        a = next(a for a in source.abilities if a.kind == 'spell_repeat')
        source.abilities[source.abilities.index(a)] = replace(a, spell_repeat=self.fee(maximum=1, casts=4))
        with self.assertRaises(ValueError): _bind_live(g.state, bad, self.r)
        self.portable(g)

    def test_compact_cost_fact_local_amount_cannot_drift(self):
        g = self.waiting(board=('fee.board',)); bad = deepcopy(g.state); p = bad.play_history[-1]
        fact = p.spell_payload.cost_facts
        bad.play_history[-1] = replace(p, spell_payload=replace(p.spell_payload,
            cost_facts=replace(fact, local_amount=2)))
        with self.assertRaises(ValueError): validate_history(bad, self.r)

    def test_live_queue_rejects_removed_entire_acceptance_tail(self):
        g = self.waiting(); q = (*g._frame.prefix, *g._frame.continuation)
        with self.assertRaises(ValueError): validate_queue(g.state, self.r,
            tuple(w for w in q if type(w) is not FinishSpellAcceptance), g.ruleset.max_resolution_steps)
        validate_queue(g.state, self.r, q, g.ruleset.max_resolution_steps)

    def test_live_queue_rejects_duplicate_tail_instead_of_deduplicating(self):
        g = self.waiting(); q = (*g._frame.prefix, *g._frame.continuation)
        with self.assertRaises(ValueError): validate_queue(g.state, self.r,
            (*q, self.proof(g)), g.ruleset.max_resolution_steps)

    def test_popped_control_rejects_missing_root_before_any_handler_runs(self):
        from collections import deque
        from hs_sim.engine.resolver import Resolution
        from hs_sim.engine.spell_acceptance import validate_control_work
        g = self.waiting(); q = (*g._frame.prefix, *g._frame.continuation)
        r = Resolution(g); work = q[0]
        r._work_queue = deque(q[1:]); validate_control_work(r, work)
        r._work_queue = deque(w for w in q[1:] if type(w) is not FinishSpellAcceptance)
        with self.assertRaises(ValueError): validate_control_work(r, work)
        self.assertEqual(g.snapshot(), g.clone().snapshot())

    def test_actual_popped_closing_tail_still_binds_pre_payment_state(self):
        g = self.waiting(); p = self.proof(g)
        self.complete(g)
        state = deepcopy(g.state); root = state.play_history[-1]
        state.play_history[-1] = replace(root, spell_acceptance_closed=False)
        # All gameplay work really completed; only the transparent closed bit
        # is reopened for this pure popped-tail diagnostic comparison.
        validate_queue(state, self.r, (), g.ruleset.max_resolution_steps, closing=p)
        bad = deepcopy(p); bad.cost_proof.payment_state.players[1].mana_spent += 1
        with self.assertRaises(ValueError): validate_queue(state, self.r, (),
            g.ruleset.max_resolution_steps, closing=bad)

    def test_empty_body_is_a_paid_complete_root_with_two_windows(self):
        g = self.ready('fee.prepare', hand=('fee.empty',)); self.play(g, 'fee.empty')
        p = g.state.play_history[-1]
        self.assertTrue(p.completed and p.spell_acceptance_closed)
        self.assertEqual(p.spell_payload.behavior_ids, ())
        self.assertEqual(p.spell_payload.casts, 2)
        self.assertEqual(p.cost, 1); self.portable(g)

    def test_countered_paid_root_has_no_successful_payload(self):
        from hs_sim.engine.secrets import SetSecret
        self.granter('fee.counter.prepare', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.SPELL,)), uses_remaining=1), SetSecret(2, 'EX1_287')))
        g = self.ready('fee.counter.prepare', hand=('fee.hit',)); self.play(g, 'fee.hit')
        p = g.state.play_history[-1]
        self.assertTrue(p.countered and p.completed and p.spell_acceptance_closed)
        self.assertIsNone(p.spell_payload); self.assertEqual(p.cost, 1); self.portable(g)

    def test_lethal_pre_entry_preserves_only_reached_cost_window(self):
        self.r.register_behavior('fee.kill.commit', lambda c: [Damage(c.state.players[2].hero_id, 50)]
            if c.event.source_id and c.state.entities[c.event.source_id].card_id == 'fee.ask' else [])
        self.minion('fee.kill.commit', health=5, triggers=(TriggerSpec('card_committed', 'fee.kill.commit'),))
        g = self.ready('fee.prepare', board=('fee.kill.commit',)); self.play(g, 'fee.ask')
        p = g.state.play_history[-1]
        self.assertEqual(g.state.status, 'finished'); self.assertTrue(p.interrupted)
        self.assertIsNone(p.spell_payload); self.assertIsNotNone(p.submitted_cost); self.portable(g)

    def test_lethal_last_choice_checks_original_proof_before_drop(self):
        self.spell('fee.ask.fatal', lambda c: [RequestChoice(1, (ChoiceOption('ok', 'Kill',
            (Damage(c.state.players[2].hero_id, 50),)),), source_id=c.source_id)], cost=3)
        g = self.ready(hand=('fee.ask.fatal',)); self.play(g, 'fee.ask.fatal')
        self.portable(g); self.choose(g, 'ok')
        self.assertEqual(g.state.status, 'finished')
        self.assertIsNotNone(g.state.play_history[-1].spell_payload); self.portable(g)

    def test_terminal_diagnostic_rejects_trimmed_root_proof(self):
        g = self.waiting(); state = deepcopy(g.state); state.status = 'finished'
        q = (*g._frame.prefix, *g._frame.continuation)
        validate_queue(state, self.r, q, g.ruleset.max_resolution_steps, terminal=True)
        with self.assertRaises(ValueError): validate_queue(state, self.r,
            tuple(w for w in q if type(w) is not FinishSpellAcceptance),
            g.ruleset.max_resolution_steps, terminal=True)

    def test_multi_active_roots_terminal_checks_all_bare_parent_and_child_proofs(self):
        self.spell('fee.terminal.child', lambda c: [RequestChoice(1, (
            ChoiceOption('ok', 'Safe child', (GainArmor(1, 1),)),
            ChoiceOption('kill', 'Terminal child', (Damage(c.state.players[2].hero_id, 50),))),
            source_id=c.source_id)], cost=3)
        def parent(c):
            if c.cast.iteration > 1: return [GainArmor(1, 1)]
            child = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'fee.terminal.child')
            return [RequestChoice(1, (ChoiceOption('ok', 'Paid child', (
                PlayFromHand(PlayCard(1, child)),
                RequestChoice(1, (ChoiceOption('ok', 'Complete parent tail', ()),), source_id=c.source_id))),),
                source_id=c.source_id)]
        self.spell('fee.terminal.parent', parent, cost=3)
        self.granter('fee.terminal.prepare', (AddSpellRepeatModifier(1,
            self.fee(maximum=3, casts=2), uses=3),))
        g = self.ready('fee.terminal.prepare', hand=('fee.terminal.parent', 'fee.terminal.child'))
        self.play(g, 'fee.terminal.parent'); self.choose(g, 'ok'); self.portable(g)
        q = (*g._frame.prefix, *g._frame.continuation)
        proofs = [w for w in q if type(w) is FinishSpellAcceptance]
        self.assertEqual(len(proofs), 2)
        state = deepcopy(g.state); state.status = 'finished'; state.pending_choice = None
        validate_queue(state, self.r, q, g.ruleset.max_resolution_steps, terminal=True)
        for proof in proofs:
            with self.subTest(play_id=proof.play_id):
                with self.assertRaises(ValueError): validate_queue(state, self.r,
                    tuple(w for w in q if w is not proof), g.ruleset.max_resolution_steps, terminal=True)
                damaged = deepcopy(proof); damaged.cost_proof.payment_state.players[1].mana_spent += 1
                with self.assertRaises(ValueError): validate_queue(state, self.r,
                    tuple(damaged if w is proof else w for w in q), g.ruleset.max_resolution_steps, terminal=True)
        safe = g.clone(); self.complete(safe); self.portable(safe)
        self.choose(g, 'kill'); self.assertEqual(g.state.status, 'finished')
        roots = [p for p in g.state.play_history if p.kind == CardType.SPELL]
        self.assertEqual(len(roots), 2); self.assertTrue(all(p.interrupted for p in roots))
        self.assertTrue(all(p.submitted_cost is not None and p.spell_payload is not None for p in roots))
        self.portable(g)

    def rewind_cards(self, retries=1, body=None):
        self.r.register_behavior('fee.retry.body', self.ask if body is None else body)
        def card(cid, rewind=None):
            self.r.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=3,
                on_play='fee.retry.body', metadata=CardMetadata(False, (CardClass.MAGE,), None),
                keywords=(Keyword.REWIND,) if rewind is not None else (), rewind=rewind))
        card('fee.retry.last')
        if retries == 2:
            card('fee.retry.middle', RewindSpec(1, 'fee.retry.last'))
        card('fee.retry', RewindSpec(retries, 'fee.retry.middle' if retries == 2 else 'fee.retry.last'))
        self.granter('fee.retry.prepare', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.SPELL,), card_ids=('fee.retry',)), uses_remaining=2),
            AddSpellRepeatModifier(1, self.fee(casts=2), uses=2)))

    def retry_waiting(self, retries=1):
        self.rewind_cards(retries)
        g = self.ready('fee.retry.prepare', hand=('fee.retry',)); self.play(g, 'fee.retry')
        while g.state.pending_choice.purpose.value != 'rewind': self.choose(g, 'ok')
        self.portable(g); self.choose(g, 'retry')
        self.assertIsNotNone(g.state.pending_choice)
        return g

    def test_true_retry_original_quote_and_new_face_window_are_separate(self):
        self.rewind_cards()
        self.granter('fee.retry.window.prepare', (AddCostModifier(1, CostSpec(delta=-2,
            card_types=(CardType.SPELL,), card_ids=('fee.retry',)), uses_remaining=1),
            AddSpellRepeatModifier(1, self.fee(casts=2), uses=2),
            AddSpellRepeatModifier(1, self.fee('window_quote', casts=4), uses=2)))
        g = self.ready('fee.retry.window.prepare', hand=('fee.retry',)); self.play(g, 'fee.retry')
        while g.state.pending_choice.purpose.value != 'rewind': self.choose(g, 'ok')
        self.portable(g); self.choose(g, 'retry'); p = g.state.play_history[-1]
        self.assertEqual((p.card_id, p.cost, p.submitted_cost.quote_origin,
            p.submitted_cost.quote.quote_input.card_id), ('fee.retry.last', 1, 'rewind_root', 'fee.retry'))
        self.assertEqual(p.spell_submission.cost_facts.window_quotes[0].amount, 3)
        self.assertEqual(p.spell_payload.casts, 2)
        self.assertEqual([m.uses_remaining for m in g.state.players[1].spell_modifiers], [1, 2])
        validate_acceptance(self.proof(g), self.r); self.portable(g); self.complete(g)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(len(self.events(g, 'timeline_rewound')), 1)

    def test_true_retry_anchor_rejects_wrong_attempt_cursor_and_root_action(self):
        g = self.retry_waiting(); p = self.proof(g).cost_proof
        validate_hand_cost_proof_live(p, g)
        for anchor in (replace(p.rewind_anchor, attempt=2),
                       replace(p.rewind_anchor, event_start=p.rewind_anchor.event_start+1),
                       replace(p.rewind_anchor, action=replace(p.rewind_anchor.action, target_id=self.hero(g, 2).id))):
            with self.subTest(anchor=anchor.attempt):
                with self.assertRaises(ValueError):
                    validate_hand_cost_proof_live(replace(p, rewind_anchor=anchor), g)

    def test_retry_normalization_rejects_hand_state_and_counter_regression(self):
        g = self.retry_waiting(); p = self.proof(g).cost_proof
        for name in ('next_attachment_id', 'next_window_id'):
            bad = deepcopy(p); setattr(bad.payment_state, name, getattr(bad.rewind_anchor.before, name)-1)
            with self.assertRaises(ValueError): validate_hand_cost_proof(bad, self.r)
        bad = deepcopy(p); bad.payment_state.entities[bad.prepared_play.source_id].zone_epoch += 1
        with self.assertRaises(ValueError): validate_hand_cost_proof(bad, self.r)

    def test_two_retries_restore_cost_uses_and_keep_each_attempt_log(self):
        g = self.retry_waiting(2)
        while g.state.pending_choice.purpose.value != 'rewind': self.choose(g, 'ok')
        self.portable(g); self.choose(g, 'retry'); self.portable(g); self.complete(g)
        self.assertEqual(g.state.play_history[-1].card_id, 'fee.retry.last')
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.assertEqual(len(self.events(g, 'timeline_rewound')), 2)
        self.assertEqual(len([e for e in self.events(g, 'mana_spent') if e.source_id == g.state.play_history[-1].source_id]), 3)

    def test_true_retry_waiting_restores_with_independently_constructed_registry(self):
        g = self.retry_waiting()
        other = SpellCostAcceptanceTests(); other.setUp(); other.rewind_cards()
        self.portable(g, other.r)
        restored = Game.from_snapshot(g.snapshot(), other.r)
        self.complete(g); self.complete(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_retained_results_keep_original_fee_quota_and_one_payment(self):
        self.rewind_cards()
        g = self.ready('fee.retry.prepare', hand=('fee.retry', 'fee.hit'), board=('fee.retainer',))
        self.play(g, 'fee.retry'); waiting = 0
        while g.state.pending_choice:
            waiting += 1; self.portable(g); self.choose(g, 'ok')
        p = next(p for p in g.state.play_history if p.card_id == 'fee.retry')
        self.assertEqual(waiting, 4)
        self.assertEqual(p.spell_payload.casts, 2)
        self.assertEqual(len([r for r in g.state.cost_use_history if r.source_id == p.source_id]), 1)
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.play(g, 'fee.hit'); self.assertEqual(g.state.play_history[-1].cost, 3)
        self.portable(g)

    def test_fee_retained_plan_cannot_downgrade_or_delete_entire_outcome_span(self):
        from hs_sim.engine.rewind_outcomes import StartRewindOutcome
        self.rewind_cards(2)
        g = self.ready('fee.retry.prepare', hand=('fee.retry',), board=('fee.retainer',))
        self.play(g, 'fee.retry'); self.portable(g)
        q = (*g._frame.prefix, *g._frame.continuation)
        validate_queue(g.state, self.r, q, g.ruleset.max_resolution_steps)
        for mode in ('downgrade', 'delete'):
            bad = deepcopy(g.state); damaged_queue = q
            if mode == 'downgrade':
                bad.rewind_outcomes[0] = replace(bad.rewind_outcomes[0], total=2)
            else:
                bad.rewind_outcomes.clear()
                damaged_queue = tuple(w for w in q if not isinstance(w, StartRewindOutcome))
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError): validate_queue(bad, self.r, damaged_queue,
                    g.ruleset.max_resolution_steps)
        self.complete(g); self.portable(g)

    def two_paid_children(self, *, child_wait=False):
        child_name = 'fee.ask' if child_wait else 'fee.hit'
        def body(c):
            cards = [i for i in c.state.players[1].hand if c.state.entities[i].card_id == child_name]
            return [RequestChoice(1, (ChoiceOption('ok', 'First paid child', (
                PlayFromHand(PlayCard(1, cards[0])),
                RequestChoice(1, (ChoiceOption('ok', 'Second paid child', (
                    PlayFromHand(PlayCard(1, cards[1])),
                    RequestChoice(1, (ChoiceOption('ok', 'Close parent', ()),), source_id=c.source_id))),),
                    source_id=c.source_id))),), source_id=c.source_id)]
        self.spell('fee.parent', body, cost=3)
        self.granter('fee.parent.prepare', (AddCostModifier(1, CostSpec(delta=-2,
            card_ids=(child_name,), card_types=(CardType.SPELL,)), uses_remaining=2),))
        g = self.ready('fee.parent.prepare', hand=('fee.parent', child_name, child_name))
        self.play(g, 'fee.parent')
        return g

    def test_parent_false_cost_source_authenticates_two_closed_child_uses_after_disappearance(self):
        g = self.two_paid_children()
        self.portable(g); self.choose(g, 'ok'); self.portable(g); self.choose(g, 'ok')
        self.assertFalse(g.state.players[1].cost_modifiers)
        p = self.proof(g)
        children = [r for r in g.state.cost_use_history if r.source_card_id == 'fee.hit']
        self.assertEqual([r.player_modifiers[0].uses_remaining for r in children], [2, 1])
        _bind_live(g.state, p, self.r)
        bad = deepcopy(g.state)
        i = next(i for i, r in enumerate(bad.cost_use_history) if r.id == children[1].id)
        row = bad.cost_use_history[i]
        bad.cost_use_history[i] = replace(row, player_modifiers=(replace(row.player_modifiers[0], uses_remaining=2),))
        with self.assertRaises(ValueError): _bind_live(bad, p, self.r)
        self.portable(g); self.choose(g, 'ok'); self.portable(g)

    def test_later_spell_typed_window_cannot_rewrite_accepted_parent_cost_fact(self):
        from hs_sim.engine.spell_acceptance import _bind_foreign_windows
        g = self.two_paid_children(child_wait=True); parent = self.proof(g)
        self.choose(g, 'ok')
        child = next(w for w in (*g._frame.prefix, *g._frame.continuation)
                     if type(w) is FinishSpellAcceptance and w.play_id != parent.play_id)
        validate_acceptance(child, self.r)
        _bind_foreign_windows(self.r, [parent], child)
        bad = deepcopy(child)
        for state in (bad.cost_proof.payment_state, bad.submission.state, bad.resolution.state):
            old = state.play_history[parent.play_id-1]
            q = old.submitted_cost.quote
            changed = replace(q, quote_input=replace(q.quote_input, base_cost=4), local_amount=4, amount=4,
                intrinsic=replace(q.intrinsic, base_cost=4, amount=4))
            state.play_history[parent.play_id-1] = replace(old, cost=4, mana_after=old.mana_after-1,
                submitted_cost=replace(old.submitted_cost, quote=changed))
        # Its own new paid child's quote/payment projection remains valid.
        validate_acceptance(bad, self.r)
        with self.assertRaises(ValueError): _bind_foreign_windows(self.r, [parent], bad)
        self.portable(g)

    def test_ordinary_child_during_retry_does_not_borrow_parent_quote(self):
        def body(c):
            child = next(i for i in c.state.players[1].hand if c.state.entities[i].card_id == 'fee.hit')
            return [RequestChoice(1, (ChoiceOption('ok', 'Child', (PlayFromHand(PlayCard(1, child)),)),), source_id=c.source_id)]
        self.rewind_cards(body=body)
        g = self.ready('fee.retry.prepare', hand=('fee.retry', 'fee.hit', 'fee.hit'))
        self.play(g, 'fee.retry')
        while g.state.pending_choice.purpose.value != 'rewind': self.choose(g, 'ok')
        self.choose(g, 'retry'); self.portable(g)
        self.choose(g, 'ok')
        child = g.state.play_history[-1]
        self.assertEqual(child.card_id, 'fee.hit'); self.assertEqual(child.submitted_cost.quote_origin, 'current_hand')
        self.assertEqual(child.cost, 3); self.portable(g)

    def test_health_account_quote_is_not_actual_life_loss(self):
        g = self.ready('fee.health')
        self.play(g, 'fee.ask'); p = g.state.play_history[-1]
        self.assertEqual((p.cost, p.payment), (3, PaymentType.HEALTH))
        self.assertEqual((self.hero(g).armor, self.hero(g).health), (0, 29))
        validate_acceptance(self.proof(g), self.r); self.portable(g)

    def test_after_payment_body_error_restores_full_action_and_cost_uses(self):
        from hs_sim.engine.errors import ResolutionError
        def fail(c): raise ResolutionError('fee fixture actual body failure')
        self.spell('fee.error', fail, cost=3)
        g = self.ready('fee.twice', hand=('fee.error',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fee.error')
        self.assertEqual(g.snapshot(), before)

    def test_choice_failure_restores_waiting_origin_and_policy_clock(self):
        from hs_sim.engine.effects import InvokeBehavior
        from hs_sim.engine.errors import ResolutionError
        def fail(c): raise ResolutionError('fee fixture choice failure')
        self.r.register_behavior('fee.fail.branch', fail)
        self.spell('fee.branch', lambda c: [RequestChoice(1, (ChoiceOption('ok', 'Fail',
            (InvokeBehavior('fee.fail.branch', c.source_id, c.player_id),)),), source_id=c.source_id)], cost=3)
        g = self.ready('fee.twice', hand=('fee.branch',)); self.play(g, 'fee.branch'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'ok')
        self.assertEqual(g.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
