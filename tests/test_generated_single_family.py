"""Actual single/BC-only generated identities without borrowed repeat policies."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import CardType, SelectChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.game import Game
from hs_sim.engine.model import ComboRepeatPlan
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.body_conditions import BodyPlayReference, body_play_conditions
from tests import test_generated_body_targets as fixture
from tests import test_generated_combo_repetition as combos


class GeneratedSingleFamilyTests(unittest.TestCase):
    play = fixture.GeneratedBodyTargetTests.play
    generated = fixture.GeneratedBodyTargetTests.generated

    def game(self, mode='normal', variant='legacy', policy='random', kind=CardType.MINION, **kw):
        return fixture.GeneratedBodyTargetTests.game(self, mode, policy, kind, variant, **kw)

    def settled(self, mode='normal', variant='legacy', **kw):
        g = self.game(mode, variant, **kw)
        self.play(g, 'repeat')
        return g

    def portable(self, g, mode='normal', variant='legacy', policy='random', kind=CardType.MINION):
        saved = json.loads(json.dumps(g.snapshot()))
        branches = (Game.from_snapshot(saved, fixture.registry(mode, policy, kind, variant)),
            g.clone(), replay(build_replay(g), fixture.registry(mode, policy, kind, variant)))
        for branch in branches:
            self.assertEqual(branch.snapshot(), saved)
            for seat in (1, 2): self.assertEqual(branch.observe(seat), g.observe(seat))
        return branches

    def reject(self, g, mutate, mode='normal', variant='legacy'):
        saved = deepcopy(g.snapshot())
        mutate(saved)
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(saved, fixture.registry(mode, 'random', CardType.MINION, variant))
        self.assertNotIn('digest mismatch', str(error.exception))

    def test_single_body_has_complete_actual_battlecry_and_combo_identities(self):
        g = self.settled(); p = self.generated(g)
        self.assertEqual(len(p.battlecry_ids), 2)
        self.assertEqual(len(p.combo_ids), 2)
        self.assertEqual(p.combo_repeat_acceptance.plan, ComboRepeatPlan())
        self.assertEqual([g.state.combo_history[i - 1].payload.card_id for i in p.combo_ids], ['unit', 'donor'])
        self.assertTrue(all(g.state.combo_history[i - 1].play_id is None for i in p.combo_ids))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)
        self.assertEqual(len(g.state.play_history), 2)
        self.portable(g)

    def test_single_source_does_not_query_or_consume_any_repeat_policy(self):
        g = self.game(policies=True)
        originals = (tuple(g.state.players[1].battlecry_modifiers), tuple(g.state.players[1].combo_modifiers))
        with patch('hs_sim.engine.combo_acceptance_matching.capture_player_modifiers',
                side_effect=AssertionError('Single Combo queried repetition policies')), patch(
                'hs_sim.engine.combo_acceptance_matching.capture_repeat_plan',
                side_effect=AssertionError('Single Combo queried board witnesses')):
            self.play(g, 'repeat')
        p = self.generated(g)
        self.assertEqual((tuple(g.state.players[1].battlecry_modifiers),
            tuple(g.state.players[1].combo_modifiers)), originals)
        receipt = g.state.combo_policy_receipts[p.combo_repeat_acceptance.policy_receipt_id - 1]
        self.assertEqual(receipt.modifiers, ())
        self.assertTrue(receipt.consumption_applied)
        self.assertEqual(p.combo_repeat_acceptance.plan, ComboRepeatPlan())
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (2, 2))

    def test_battlecry_only_source_repeats_battlecry_and_keeps_combo_single(self):
        g = self.settled(variant='legacy_bc', policies=True); p = self.generated(g)
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (4, 2))
        self.assertEqual(p.battlecry_repeat_acceptance.plan.repetitions, 2)
        self.assertEqual(p.combo_repeat_acceptance.plan, ComboRepeatPlan())
        self.assertEqual(g.state.players[1].battlecry_modifiers, [])
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 1)
        self.assertEqual(len(g.state.play_history), 3)
        self.portable(g, variant='legacy_bc')

    def test_independent_body_targets_and_frozen_declaring_thresholds(self):
        g = self.settled('conditions', variant='legacy_bc'); p = self.generated(g)
        self.assertEqual(g.state.players[1].max_mana, 2)
        for identity in p.combo_ids:
            row = g.state.combo_history[identity - 1]
            values = body_play_conditions(g.state, g.registry, BodyPlayReference.from_record(row, 'combo'))
            self.assertTrue(values.manathirst)
            self.assertEqual(values.manathirst_threshold, 9 if row.payload.card_id == 'unit' else 4)
        self.assertEqual([s.conditions.manathirst_threshold for s in p.body_targets.slots], [9, 4, 9, 4])
        self.portable(g, 'conditions', 'legacy_bc')

    def test_explicit_request_has_per_body_failure_and_no_body_draw(self):
        g = self.settled(policy='explicit'); p = self.generated(g)
        self.assertEqual([s.selected.failure for s in p.body_targets.slots], [None, 'invalid_target', None, 'invalid_target'])
        self.assertEqual([g.state.combo_history[i - 1].failure for i in p.combo_ids], [None, 'invalid_target'])
        self.assertTrue(all(s.selected.rng_before == s.selected.rng_after for s in p.body_targets.slots))
        self.portable(g, policy='explicit')

    def test_root_empty_target_does_not_erase_actual_combo(self):
        g = self.settled('root_empty'); p = self.generated(g)
        self.assertEqual(p.selection.failure, 'no_target')
        self.assertEqual(len(p.combo_ids), 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)
        self.portable(g, 'root_empty')

    def test_entry_wait_has_no_acceptance_until_installation_finishes(self):
        g = self.settled('entry_wait'); p = self.generated(g)
        self.assertEqual(p.phase, 'installing')
        self.assertIsNone(p.activation)
        self.assertIsNone(p.combo_repeat_acceptance)
        self.assertEqual(p.combo_ids, ())
        branches = (g, *self.portable(g, 'entry_wait'))
        action = SelectChoice(1, g.state.pending_choice.id, ('go',))
        for branch in branches: branch.apply(action)
        self.assertTrue(all(branch.snapshot() == g.snapshot() for branch in branches))
        self.assertEqual(len(self.generated(g).combo_ids), 2)

    def test_actual_combo_wait_has_finish_identity_and_restores_before_resume(self):
        g = self.settled('wait', variant='legacy_bc')
        while not self.generated(g).combo_ids:
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('go',)))
        p = self.generated(g); actual = g.state.combo_history[p.combo_ids[-1] - 1]
        self.assertEqual(p.active_combo_id, actual.id)
        self.assertFalse(actual.completed)
        branches = (g, *self.portable(g, 'wait', 'legacy_bc'))
        while g.state.pending_choice is not None:
            action = SelectChoice(1, g.state.pending_choice.id, ('go',))
            for branch in branches: branch.apply(action)
            self.assertTrue(all(branch.snapshot() == g.snapshot() for branch in branches))
        self.assertEqual(len(self.generated(g).combo_ids), 2)
        self.assertIsNone(self.generated(g).active_combo_id)

    def test_acceptance_survives_silence_without_extending_remaining_vector(self):
        g = self.settled('silence'); self.assertEqual(len(self.generated(g).combo_ids), 2)
        self.portable(g, 'silence')

    def test_accepted_carrier_death_does_not_erase_combo(self):
        g = self.settled('death'); p = self.generated(g)
        self.assertEqual(g.state.entities[p.source.entity_id].zone.value, 'graveyard')
        self.assertEqual(len(p.combo_ids), 2)
        self.portable(g, 'death')

    def test_control_change_keeps_original_executor_and_targets(self):
        g = self.settled('control'); p = self.generated(g)
        self.assertEqual(g.state.entities[p.source.entity_id].controller, 2)
        self.assertTrue(all(g.state.combo_history[i - 1].player_id == 1 for i in p.combo_ids))
        self.portable(g, 'control')

    def test_late_grant_does_not_extend_actual_single_execution(self):
        g = self.settled('late'); p = self.generated(g)
        self.assertEqual((len(p.battlecry_ids), len(p.combo_ids)), (2, 2))
        self.assertEqual(len(p.body_targets.slots), 4)
        self.portable(g, 'late')

    def test_no_payload_has_acceptance_without_fabricated_actual_record(self):
        g = self.settled('empty_body'); p = self.generated(g)
        self.assertEqual(p.combo_repeat_acceptance.status, 'no_payload')
        self.assertIsNone(p.combo_repeat_acceptance.plan)
        self.assertEqual((p.combo_ids, p.battlecry_ids, p.body_targets.slots), ((), (), ()))
        self.portable(g, 'empty_body')

    def test_other_executor_disabled_combo_keeps_complete_inactive_declarations(self):
        g = self.settled('player_other'); p = self.generated(g)
        self.assertEqual(p.player_id, 2)
        self.assertEqual(p.combo_repeat_acceptance.status, 'disabled')
        self.assertEqual(len(p.combo_repeat_acceptance.payloads), 2)
        self.assertEqual(p.combo_ids, ())
        self.assertTrue(all(not s.active for s in p.body_targets.slots if s.reference.family == 'combo'))
        self.portable(g, 'player_other')

    def test_later_unknown_body_rolls_back_installation_payment_and_rng(self):
        g = self.game('fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'repeat')
        self.assertEqual(g.snapshot(), before)

    def test_empty_target_combo_still_has_completed_actual_identity(self):
        g = self.settled('empty_target'); p = self.generated(g)
        row = next(g.state.combo_history[i - 1] for i in p.combo_ids
            if g.state.combo_history[i - 1].payload.card_id == 'unit')
        self.assertEqual(row.failure, 'no_target')
        self.assertTrue(row.completed)
        self.portable(g, 'empty_target')

    def test_generated_weapon_uses_single_combo_identity(self):
        g = self.settled(kind=CardType.WEAPON); self.assertEqual(len(self.generated(g).combo_ids), 2)
        self.portable(g, kind=CardType.WEAPON)

    def test_generated_hero_uses_single_combo_identity(self):
        g = self.settled(kind=CardType.HERO); self.assertEqual(len(self.generated(g).combo_ids), 2)
        self.portable(g, kind=CardType.HERO)

    def test_closed_actual_combo_ids_cannot_be_trimmed_after_rehash(self):
        g = self.settled()
        self.reject(g, lambda s: s['state']['whole_card_replay_ledger']['children'][0]['physical'].__setitem__('combo_ids', []))

    def test_closed_actual_combo_cannot_borrow_paid_root(self):
        g = self.settled()
        self.reject(g, lambda s: s['state']['combo_history'][-1].__setitem__('play_id', 1))

    def test_single_plan_cannot_borrow_real_live_repeat_policy(self):
        g = self.settled(policies=True)
        modifier = g.state.players[1].combo_modifiers[0]
        def mutate(s):
            p = s['state']['whole_card_replay_ledger']['children'][0]['physical']
            p['combo_repeat_acceptance']['plan'] = dict(repetitions=3, contributors=[modifier.id], consumable_ids=[modifier.id])
        self.reject(g, mutate)

    def test_single_receipt_cannot_capture_unused_policy_after_rehash(self):
        g = self.settled(policies=True)
        def mutate(s):
            modifier = deepcopy(s['state']['players']['1']['combo_modifiers'][0])
            s['state']['combo_policy_receipts'][-1]['modifiers'] = [modifier]
        self.reject(g, mutate)

    def test_current_format_rejects_previous_single_unrecorded_semantics(self):
        g = self.settled(); saved = g.snapshot()
        self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        saved['schema_version'] = 136
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, fixture.registry(variant='legacy'))

    def test_bare_single_combo_keeps_actual_identity_without_target_binding(self):
        helper = combos.GeneratedComboRepetitionTests()
        g = helper.populated(repeater='gen.legacy'); p = helper.progress(g)
        self.assertIsNone(p.body_targets)
        self.assertEqual(p.combo_repeat_acceptance.plan, ComboRepeatPlan())
        self.assertEqual(len(p.combo_ids), 1)
        helper.portable(g)

    def test_single_combo_lethal_interrupt_has_only_the_actual_started_record(self):
        helper = combos.GeneratedComboRepetitionTests()
        g = helper.populated('gen.lethal', repeater='gen.legacy'); p = helper.progress(g)
        self.assertNotEqual(g.state.status, 'playing')
        self.assertEqual(len(p.combo_ids), 1)
        self.assertTrue(g.state.combo_history[p.combo_ids[0] - 1].interrupted)
        helper.portable(g)

    def test_single_combo_start_listener_wait_captures_already_bound_identity(self):
        helper = combos.GeneratedComboRepetitionTests()
        g = helper.populated(repeater='gen.legacy', board=('gen.watch_start',)); p = helper.progress(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(p.active_combo_id, p.combo_ids[-1])
        self.assertFalse(g.state.combo_history[p.active_combo_id - 1].completed)
        branches = (g, *helper.portable(g))
        action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
        for branch in branches: branch.apply(action)
        self.assertTrue(all(branch.snapshot() == g.snapshot() for branch in branches))
        self.assertTrue(g.state.combo_history[p.active_combo_id - 1].completed)
        self.assertEqual(g.state.players[1].combo_modifiers[0].uses_remaining, 3)

    def test_single_combo_finish_listener_wait_preserves_completed_identity(self):
        helper = combos.GeneratedComboRepetitionTests()
        g = helper.populated(repeater='gen.legacy', board=('gen.watch_finish',)); p = helper.progress(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(p.active_combo_id, p.combo_ids[-1])
        self.assertTrue(g.state.combo_history[p.active_combo_id - 1].completed)
        branches = (g, *helper.portable(g))
        action = SelectChoice(1, g.state.pending_choice.id, ('ok',))
        for branch in branches: branch.apply(action)
        self.assertTrue(all(branch.snapshot() == g.snapshot() for branch in branches))
        self.assertIsNone(helper.progress(g).active_combo_id)

    def test_accepted_target_loss_skips_only_corresponding_combo_identity(self):
        g = self.settled('stale'); p = self.generated(g)
        rows = [g.state.combo_history[i - 1] for i in p.combo_ids]
        self.assertEqual([row.failure for row in rows], ['invalid_target', None])
        self.assertTrue(all(row.completed for row in rows))
        self.portable(g, 'stale')
