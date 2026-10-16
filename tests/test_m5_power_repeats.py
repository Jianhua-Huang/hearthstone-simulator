"""M5-13d-02l-03: frozen board power counts and independent result axes."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest

import test_m5_power_payloads as foundation
import test_m5_power_activations as activations
from hs_sim.engine import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    DamageKind, EndTurn, Game, HeroPowerReference, IllegalAction, Keyword,
    ResolutionError, ResolutionLimitExceeded, Ruleset, SnapshotError,
    TargetSpec, TriggerHeroPower, UseHeroPower)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    Damage, Destroy, GainArmor, ReplaceHeroPower, RequestChoice, ReturnToHand,
    Silence, Summon, Transform)
from hs_sim.engine.hero_power_repeats import GrantHeroPowerRepeatAura
from hs_sim.engine.hero_powers import RemoveHeroPower
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (AbilityInstance, HeroPowerRepeatPlan,
    HeroPowerRepeatSpec, SpellRepeatSpec)
from hs_sim.engine.power_payloads import activated_power_payloads
from hs_sim.engine.serialization import canonical_hash


class PowerRepeatTests(unittest.TestCase):
    power = foundation.PowerPayloadTests.power
    script = foundation.PowerPayloadTests.script
    watch = foundation.PowerPayloadTests.watch
    play = foundation.PowerPayloadTests.play
    use = foundation.PowerPayloadTests.use
    source = foundation.PowerPayloadTests.source
    armor = foundation.PowerPayloadTests.armor
    choose = foundation.PowerPayloadTests.choose
    restore = foundation.PowerPayloadTests.restore
    check = foundation.PowerPayloadTests.check
    reject = foundation.PowerPayloadTests.reject
    pause = foundation.PowerPayloadTests.pause
    installer = foundation.PowerPayloadTests.installer
    rewind_power = foundation.PowerPayloadTests.rewind_power
    retainer = foundation.PowerPayloadTests.retainer
    named = foundation.PowerPayloadTests.named
    rows = foundation.PowerPayloadTests.rows
    batches = foundation.PowerPayloadTests.batches

    def setUp(self):
        foundation.PowerPayloadTests.setUp(self)
        self.aura('double', 2)
        self.aura('triple', 3)

    def aura(self, cid, count=2, **kw):
        self.r.register_card(CardDefinition(cid, cid, CardType.MINION, attack=1,
            health=5, hero_power_repeats=(HeroPowerRepeatSpec(count),), **kw))

    def game(self, **kw):
        kw.setdefault('board', ('double',))
        kw.setdefault('hand', ())
        return foundation.PowerPayloadTests.game(self, **kw)

    def plan(self, g, root=1): return g.state.hero_power_history[root-1].repeat_plan
    def body(self, g, player=1, index=0): return g.state.players[player].board[index]

    def waiting(self, *, retained=False, multiple=False):
        behavior = lambda c: [self.pause(c, GainArmor(1, c.power_payload.repeat_index))]
        board = ['double']
        if retained:
            self.rewind_power('waiting', behavior)
            self.retainer(); board.append('retainer')
        else:
            self.power('waiting', behavior)
        if multiple:
            self.installer(('waiting',)); g = self.game(power='waiting', board=tuple(board), hand=('install',))
            self.play(g, 'install')
        else:
            g = self.game(power='waiting', board=tuple(board))
        self.use(g)
        return g

    def queue(self, snapshot): return snapshot['resolution_frame']['fields']['continuation']['tuple']
    def assert_single_root_events(self, g, origin='manual'):
        kinds = ('hero_power_started', 'hero_power_used') if origin == 'manual' else (
            'hero_power_trigger_started', 'hero_power_triggered')
        self.assertEqual([e.kind for e in g.events if e.kind.startswith('hero_power')], list(kinds))

    def test_manual_twice_keeps_one_payment_use_and_root_completion(self):
        g = self.game(); self.use(g)
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn,
            g.state.players[1].hero_power_uses_this_turn), (2, 8, 1, 1))
        self.assertEqual(len(g.state.hero_power_history), 1)
        self.assertEqual([r.capture.repeat_index for r in self.rows(g)], [1, 2])
        self.assertTrue(all(r.completed for r in self.rows(g)))
        self.assert_single_root_events(g); self.check(g)

    def test_indirect_twice_with_zero_mana_consumes_no_manual_opportunity(self):
        g = self.game(hand=('trigger',), mana=0); origin = self.play(g)
        root = g.state.hero_power_history[0]
        self.assertEqual((root.origin, root.activator_id, root.cost, root.payment), ('effect', origin, None, None))
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn,
            g.state.players[1].hero_power_uses_this_turn), (2, 0, 0, 0))
        self.assert_single_root_events(g, 'effect'); self.check(g)

    def test_twice_payload_still_requires_new_manual_opportunity(self):
        g = self.game(); self.use(g)
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(len(self.rows(g)), 2); self.check(g)

    def test_two_double_sources_set_count_instead_of_multiplying(self):
        g = self.game(board=('double', 'double')); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (2, 2))
        self.assertEqual(len(self.plan(g).contributors), 2); self.check(g)

    def test_highest_set_count_wins_with_all_sources_captured(self):
        g = self.game(board=('triple', 'double')); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (3, 3))
        contributors = self.plan(g).contributors
        self.assertEqual(len(contributors), 2)
        self.assertEqual([c.ability.id for c in contributors], sorted(c.ability.id for c in contributors)); self.check(g)

    def test_enemy_source_does_not_repeat_friendly_power(self):
        g = self.game(board=(), enemy=('double',)); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g)), (1, HeroPowerRepeatPlan())); self.check(g)

    def test_source_complete_ability_and_card_provenance_is_frozen(self):
        g = self.game(); carrier = self.body(g); ability = active_abilities(g.state.entities[carrier], 'hero_power_repeat')[0]
        self.use(g); contributor = self.plan(g).contributors[0]
        self.assertEqual((contributor.carrier_id, contributor.card_id, contributor.player_id,
            contributor.ability), (carrier, 'double', 1, ability))
        self.assertEqual(self.batches(g)[0].plan, self.plan(g)); self.check(g)

    def test_source_disabled_before_acceptance_does_not_contribute(self):
        for operation in (Silence, Destroy, ReturnToHand, lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp(); self.script('disable', lambda c: [operation(c.state.players[1].board[0])])
                g = self.game(hand=('disable',)); self.play(g, 'disable'); self.use(g)
                self.assertEqual((self.armor(g), self.plan(g).repetitions), (1, 1)); self.check(g)

    def test_dormant_source_has_no_contribution(self):
        self.aura('sleeping', dormant_turns=1)
        g = self.game(board=('sleeping',)); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (1, 1)); self.check(g)

    def test_new_turn_recaptures_awakened_source(self):
        self.aura('sleeping', dormant_turns=1)
        g = self.game(board=('sleeping',)); self.use(g); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.use(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [1, 2])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_start_reaction_source_death_does_not_reduce_accepted_plan(self):
        self.watch('kill', lambda c: [Destroy(c.state.players[1].board[0])], 'hero_power_started')
        g = self.game(board=('double', 'kill')); source = self.body(g); self.use(g)
        self.assertNotIn(source, g.state.players[1].board)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (2, 2)); self.check(g)

    def test_start_reaction_new_source_only_affects_next_root(self):
        self.watch('add', lambda c: [Summon(1, 'double')], 'hero_power_started')
        g = self.game(board=('add',), hand=('trigger',)); self.use(g); self.play(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [1, 2])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_payment_reaction_runs_after_acceptance_and_does_not_reprice_count(self):
        def payment(c):
            self.assertEqual(c.state.hero_power_history[-1].repeat_plan, HeroPowerRepeatPlan())
            return [Destroy(c.state.players[1].board[0])]
        self.watch('killpaid', payment, 'mana_spent')
        g = self.game(board=('double', 'killpaid')); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (2, 2)); self.check(g)

    def test_source_removed_by_first_payload_keeps_current_count_and_changes_next_root(self):
        self.power('remove', lambda c: [Destroy(c.state.players[1].board[0]), GainArmor(1, 1)]
            if c.state.players[1].board else [GainArmor(1, 1)])
        g = self.game(power='remove', hand=('trigger',)); self.use(g); self.play(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [2, 1])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_source_silence_transform_and_control_change_do_not_shrink_current_root(self):
        for operation in (Silence, lambda i: Transform(i, 'plain'), lambda i: ChangeControl(i, 2)):
            with self.subTest(operation=operation):
                self.setUp()
                self.power('disable', lambda c: [operation(c.state.players[1].board[0]), GainArmor(1, 1)]
                    if c.power_payload.repeat_index == 1 and c.state.players[1].board else [GainArmor(1, 1)])
                g = self.game(power='disable', hand=('trigger',)); self.use(g); self.play(g)
                self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [2, 1])
                self.assertEqual(self.armor(g), 3); self.check(g)

    def test_source_created_by_payload_does_not_expand_already_accepted_root(self):
        self.power('create', lambda c: [Summon(1, 'double'), GainArmor(1, 1)])
        g = self.game(power='create', board=(), hand=('trigger',)); self.use(g); self.play(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [1, 2])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_extra_execution_reads_updated_state(self):
        self.power('grow', lambda c: [GainArmor(1, c.state.entities[c.state.players[1].hero_id].armor+1)])
        g = self.game(power='grow'); self.use(g)
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_each_ability_first_keeps_original_window_extra_reads_latest(self):
        self.power('make', lambda c: [Summon(1, 'plain')])
        self.r.register_behavior('count', lambda c: [GainArmor(1, len(c.state.players[1].board))])
        self.installer(('count',)); g = self.game(power='make', hand=('install',)); self.play(g, 'install'); self.use(g)
        self.assertEqual((len(g.state.players[1].board), self.armor(g)), (3, 4))
        self.assertEqual([(r.capture.ability.behavior_id, r.capture.repeat_index) for r in self.rows(g)],
                         [('make', 1), ('make', 2), ('count', 1), ('count', 2)]); self.check(g)

    def test_same_behavior_instances_each_have_independent_repeated_positions(self):
        self.installer(('power',)); g = self.game(hand=('install',)); self.play(g, 'install'); self.use(g)
        rows = self.rows(g); ids = [r.capture.ability.id for r in rows]
        self.assertEqual(ids[0], ids[1]); self.assertEqual(ids[2], ids[3]); self.assertNotEqual(ids[0], ids[2])
        self.assertEqual([r.capture.repeat_index for r in rows], [1, 2, 1, 2])
        self.assertEqual(self.armor(g), 4); self.check(g)

    def test_complete_batch_positions_and_total_are_durable(self):
        self.installer(('power',)); g = self.game(hand=('install',)); self.play(g, 'install'); self.use(g)
        batch = self.batches(g)[0]; self.assertEqual(batch.total, 4)
        self.assertEqual([batch.position(i) for i in range(batch.total)],
                         [(r.capture.ability, r.capture.repeat_index) for r in self.rows(g)])
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 2, 3, 4]); self.check(g)

    def test_repeated_damage_keeps_original_target_after_its_death(self):
        self.power('target', lambda c: [Damage(c.target_id, 4, c.source_id, DamageKind.HERO_POWER)],
                   targeting=TargetSpec(kinds=(CardType.MINION,), relation='enemy'))
        g = self.game(power='target', enemy=('plain', 'plain')); target = self.body(g, 2); other = self.body(g, 2, 1)
        self.use(g, target)
        self.assertEqual(g.state.players[2].board, [other]); self.assertEqual(g.state.entities[other].health, 4)
        self.assertEqual(g.state.hero_power_history[0].target_id, target)
        self.assertEqual(len(self.rows(g)), 2); self.assertTrue(all(r.completed for r in self.rows(g))); self.check(g)

    def test_random_indirect_target_is_selected_once_and_not_reselected(self):
        self.power('target', lambda c: [Damage(c.target_id, 4, c.source_id, DamageKind.HERO_POWER)],
                   targeting=TargetSpec(kinds=(CardType.MINION,), relation='enemy'))
        g = self.game(power='target', hand=('trigger',), enemy=('plain', 'plain')); self.play(g)
        target = g.state.hero_power_history[0].target_id
        self.assertNotIn(target, g.state.players[2].board); self.assertEqual(len(g.state.players[2].board), 1)
        self.assertEqual(g.state.entities[self.body(g, 2)].health, 4); self.check(g)

    def test_power_replaced_during_first_execution_keeps_original_source_ability(self):
        self.power('replace', lambda c: [ReplaceHeroPower(1, 'power'), GainArmor(1, 3)]
            if c.power_payload.repeat_index == 1 else [GainArmor(1, 3)])
        g = self.game(power='replace'); source = self.source(g).id; self.use(g)
        self.assertEqual(self.armor(g), 6); self.assertEqual(self.source(g).card_id, 'power')
        self.assertEqual(g.state.hero_power_history[0].source_id, source)
        self.assertEqual({r.capture.ability.behavior_id for r in self.rows(g)}, {'replace'}); self.check(g)

    def test_power_removed_during_first_execution_does_not_cancel_extra(self):
        self.power('remove', lambda c: [RemoveHeroPower(1), GainArmor(1, 2)]
            if c.power_payload.repeat_index == 1 else [GainArmor(1, 2)])
        g = self.game(power='remove'); self.use(g)
        self.assertIsNone(g.state.players[1].hero_power_id); self.assertEqual(self.armor(g), 4); self.check(g)

    def test_choose_one_branch_remains_original_for_every_execution(self):
        self.r.register_behavior('a', lambda c: [GainArmor(1, 2)] if c.power.branch_id == 'a' else [])
        self.r.register_behavior('b', lambda c: [GainArmor(1, 9)])
        spec = ChooseOneSpec((ChooseBranch('a', 'a', 'a'), ChooseBranch('b', 'b', 'b')),
                            ChooseBranch('both', 'both', 'a'))
        self.r.register_card(CardDefinition('branch', 'branch', CardType.HERO_POWER, cost=2, choose_one=spec))
        g = self.game(power='branch'); g.apply(UseHeroPower(1, self.source(g).id, branch_id='a'))
        self.assertEqual(self.armor(g), 4)
        self.assertEqual({r.capture.ability.behavior_id for r in self.rows(g)}, {'engine.choose_one'}); self.check(g)

    def test_plain_and_extra_slots_each_capture_own_root_and_one_use(self):
        g = self.game(extras=('power',)); ids = g.state.players[1].hero_power_ids
        for source in ids: g.apply(UseHeroPower(1, source))
        self.assertEqual((self.armor(g), g.state.players[1].mana, g.state.players[1].hero_power_uses_this_turn), (4, 6, 2))
        self.assertEqual([r.capture.power_id for r in self.rows(g)], [1, 1, 2, 2]); self.check(g)

    def test_independent_choices_pause_and_restore_for_every_repeat(self):
        g = self.waiting(); self.assertEqual([r.execution_order for r in self.rows(g)], [1, None])
        self.assertEqual(len(activated_power_payloads(g.state, 1)), 1); self.check(g)
        for _ in range(2):
            restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)
        self.assertEqual(self.armor(g), 3); self.assertIsNone(g.state.pending_choice)

    def test_random_indirect_choices_are_independent_and_finish_without_pause(self):
        self.power('choice', lambda c: [RequestChoice(1, (ChoiceOption('go', 'go',
            (GainArmor(1, c.power_payload.repeat_index),)),), source_id=c.source_id)])
        g = self.game(power='choice', hand=('trigger',)); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.armor(g), 3)
        self.assertEqual(sum(e.kind == 'hero_power_choice_automatic' for e in g.events), 2); self.check(g)

    def test_failure_in_second_repeat_rolls_back_entire_manual_action(self):
        def fail(c):
            if c.power_payload.repeat_index == 2: raise ValueError('second power repetition failed')
            return [GainArmor(1, 2)]
        self.power('bad', fail); g = self.game(power='bad'); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'second power repetition failed'): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_failed_selection_in_second_repeat_preserves_pending_fact(self):
        self.power('badchoice', lambda c: [RequestChoice(1, (ChoiceOption('bad', 'bad',
            (TriggerHeroPower(1, 99999),)), ChoiceOption('ok', 'ok', (GainArmor(1, 1),))), source_id=c.source_id)])
        g = self.game(power='badchoice'); self.use(g); self.choose(g, 'ok'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g, 'ok'); self.check(g)

    def test_terminal_in_first_repeat_interrupts_started_and_unstarted_facts(self):
        self.power('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30)])
        g = self.game(power='fatal'); self.use(g)
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, None])
        self.assertTrue(all(r.interrupted and not r.completed for r in self.rows(g)))
        self.assertTrue(g.state.hero_power_history[0].interrupted); self.check(g)

    def test_terminal_in_second_repeat_preserves_first_completed_fact(self):
        self.power('fatal', lambda c: [GainArmor(1, 1)] if c.power_payload.repeat_index == 1
            else [Damage(c.state.players[2].hero_id, 30)])
        g = self.game(power='fatal'); self.use(g)
        self.assertEqual([(r.completed, r.interrupted) for r in self.rows(g)], [(True, False), (False, True)])
        self.assertEqual(self.armor(g), 1); self.check(g)

    def test_terminal_start_reaction_keeps_full_unstarted_repeat_positions(self):
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30)], 'hero_power_started')
        g = self.game(board=('double', 'fatal')); self.use(g)
        self.assertEqual([r.execution_order for r in self.rows(g)], [None, None])
        self.assertTrue(all(r.interrupted for r in self.rows(g))); self.check(g)

    def test_excessive_expansion_uses_engine_budget_and_transaction(self):
        self.aura('huge', 100000); g = self.game(board=('huge',)); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_recursive_same_entity_roots_capture_latest_policy_separately(self):
        self.power('nested', lambda c: [Destroy(c.state.players[1].board[0]),
            TriggerHeroPower(1, c.source_id), GainArmor(1, 2)]
            if c.power.origin == 'manual' and c.power_payload.repeat_index == 1 else [GainArmor(1, 1)])
        g = self.game(power='nested'); self.use(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [2, 1])
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1])
        self.assertEqual([r.capture.power_id for r in self.rows(g)], [1, 1, 2])
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 3, 2])
        self.assertEqual(self.armor(g), 4); self.check(g)

    def test_recursive_same_entity_choices_restore_before_parent_extra_repeat(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')]
            if c.power.origin == 'manual' else [self.pause(c, GainArmor(1, 1))])
        g = self.game(power='nested'); self.use(g)
        for _ in range(4): self.check(g); self.choose(g)
        self.assertEqual(self.armor(g), 4)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1, 1]); self.check(g)

    def test_recursive_repeated_work_obeys_shared_resolution_budget(self):
        self.power('loop', lambda c: [TriggerHeroPower(1, c.source_id)])
        g = self.game(power='loop', rules=Ruleset(max_resolution_steps=40)); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_ordinary_rewind_retry_replaces_all_abandoned_repeat_facts(self):
        self.rewind_power(); g = self.game(power='rewinding'); self.use(g); self.choose(g, 'retry')
        self.assertEqual((len(self.rows(g)), len(self.batches(g)), len(g.state.hero_power_history)), (2, 1, 1))
        self.assertEqual([r.capture.id for r in self.rows(g)], [1, 2])
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn), (4, 8, 1)); self.check(g)

    def test_retained_result_and_repeat_are_independent_axes(self):
        self.rewind_power(); self.retainer(); g = self.game(power='rewinding', board=('double', 'retainer')); self.use(g)
        self.assertEqual([(r.capture.iteration, r.capture.repeat_index) for r in self.rows(g)],
                         [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual([r.capture.batch_id for r in self.rows(g)], [1, 1, 3, 3])
        self.assertEqual([b.plan for b in self.batches(g)], [self.plan(g), self.plan(g)])
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn), (6, 8, 1))
        self.assertEqual(len(g.state.hero_power_history), 1); self.assert_single_root_events(g); self.check(g)

    def test_retained_results_keep_original_plan_after_source_disappears(self):
        self.rewind_power('remove', lambda c: [Destroy(c.state.players[1].board[0]), GainArmor(1, 1)]
            if any(c.state.entities[i].card_id == 'double' for i in c.state.players[1].board) else [GainArmor(1, 1)])
        self.retainer(); g = self.game(power='remove', board=('double', 'retainer')); self.use(g)
        self.assertEqual((self.armor(g), len(self.rows(g))), (4, 4))
        self.assertTrue(all(b.plan.repetitions == 2 for b in self.batches(g))); self.check(g)

    def test_retained_second_result_does_not_recapture_added_repeat_source(self):
        self.rewind_power('add', lambda c: [Summon(1, 'triple'), GainArmor(1, 1)])
        self.retainer(); g = self.game(power='add', board=('double', 'retainer')); self.use(g)
        self.assertEqual((self.armor(g), len(self.rows(g))), (4, 4))
        self.assertTrue(all(b.plan.repetitions == 2 for b in self.batches(g))); self.check(g)

    def test_retained_multiskill_choices_restore_both_axes_independently(self):
        g = self.waiting(retained=True, multiple=True)
        for _ in range(8):
            restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)
        self.assertEqual(self.armor(g), 12); self.assertEqual(len(self.rows(g)), 8)
        self.assertEqual([b.iteration for b in self.batches(g)], [1, 2])

    def test_retained_same_entity_nested_result_scopes_do_not_alias(self):
        self.rewind_power('nested', lambda c: [TriggerHeroPower(1, c.source_id), GainArmor(1, 1)]
            if c.power.origin == 'manual' else [GainArmor(1, 1)])
        self.retainer(); g = self.game(power='nested', board=('double', 'retainer')); self.use(g)
        self.assertEqual(len(g.state.hero_power_history), 5)
        self.assertEqual(len(self.rows(g)), 20)
        self.assertEqual(self.armor(g), 20)
        for row in self.rows(g):
            out = g.state.rewind_outcomes[row.capture.outcome_id-1]
            self.assertEqual(out.power_id, row.capture.power_id)
        self.check(g)

    def test_retained_terminal_start_has_no_batch_if_no_result_started(self):
        self.rewind_power(); self.retainer()
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30)], 'hero_power_started')
        g = self.game(power='rewinding', board=('double', 'retainer', 'fatal')); self.use(g)
        self.assertFalse(self.batches(g)); self.assertFalse(self.rows(g))
        self.assertEqual(self.plan(g).repetitions, 2); self.check(g)

    def test_independent_root_completion_reaction_and_inspire_fire_once(self):
        self.watch('end', lambda c: [GainArmor(1, 10)] if c.power.completed else [], 'hero_power_used')
        g = self.game(board=('double', 'end')); self.use(g)
        self.assertEqual(self.armor(g), 12); self.assert_single_root_events(g); self.check(g)

    def test_actual_inspire_condition_counts_manual_root_once_and_ignores_indirect(self):
        def manual(c):
            self.assertTrue(is_inspire(c.state, c.event, c.player_id))
            self.assertFalse(is_inspire(c.state, c.event, 2))
            return [GainArmor(1, 10)]
        def indirect(c):
            self.assertFalse(is_inspire(c.state, c.event, c.player_id))
            return []
        self.watch('inspire', manual, 'hero_power_used')
        self.watch('effectend', indirect, 'hero_power_triggered')
        g = self.game(board=('double', 'inspire', 'effectend'), hand=('trigger',)); self.use(g)
        self.assertEqual(self.armor(g), 12); self.play(g)
        self.assertEqual((self.armor(g), g.state.players[1].hero_power_uses_this_turn), (14, 1))
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [2, 2]); self.check(g)

    def test_death_deferred_lethal_or_doomed_board_source_does_not_contribute(self):
        for operation in (lambda i: Damage(i, 5), Destroy):
            with self.subTest(operation=operation):
                self.setUp()
                self.r.register_card(CardDefinition('spellrepeat', 'spellrepeat', CardType.MINION,
                    attack=1, health=5, spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
                def inspect(c):
                    source = c.state.entities[c.state.players[1].board[0]]
                    self.assertEqual(source.card_id, 'double')
                    self.assertTrue(source.health <= 0 or source.doomed)
                    self.assertEqual(c.power.repeat_plan, HeroPowerRepeatPlan())
                    return [GainArmor(1, 1)]
                self.power('inspect', inspect)
                self.script('defer', lambda c: [operation(c.state.players[1].board[0]),
                    TriggerHeroPower(1, c.source_id)])
                g = self.game(power='inspect', board=('double', 'spellrepeat'), hand=('defer',))
                self.play(g, 'defer')
                self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [1, 1])
                self.assertEqual((self.armor(g), len(g.state.death_history)), (2, 1)); self.check(g)

    def test_shared_death_checkpoint_occurs_between_extra_executions(self):
        self.power('remove', lambda c: [Damage(c.state.players[1].board[0], 5)]
            if c.power_payload.repeat_index == 1 else [GainArmor(1, len(c.state.players[1].board))])
        g = self.game(power='remove'); self.use(g)
        self.assertEqual(len(g.state.death_history), 1); self.assertEqual(self.armor(g), 0)
        self.assertEqual(len(self.rows(g)), 2); self.check(g)

    def test_granted_repeat_attachment_uses_normal_expiry(self):
        self.script('grant', lambda c: [GrantHeroPowerRepeatAura(c.state.players[1].board[0], source_id=c.source_id, expires_turn=1)])
        g = self.game(board=('plain',), hand=('grant', 'trigger', 'trigger')); origin = self.play(g, 'grant'); self.play(g)
        self.assertEqual(self.plan(g).contributors[0].ability.source_id, origin)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g)
        self.assertEqual([p.repeat_plan.repetitions for p in g.state.hero_power_history], [2, 1])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_copy_repeat_source_has_new_attachment_identity_without_extra_count(self):
        self.script('copy', lambda c: [CopyMinion(c.state.players[1].board[0], 1)])
        g = self.game(hand=('copy',)); self.play(g, 'copy'); self.use(g)
        contributors = self.plan(g).contributors
        self.assertEqual(len(contributors), 2)
        self.assertEqual(len({c.ability.id for c in contributors}), 2)
        self.assertEqual(self.armor(g), 2); self.check(g)

    def test_granted_policy_removed_by_bounce_and_reinstall(self):
        self.script('grant', lambda c: [GrantHeroPowerRepeatAura(c.state.players[1].board[0])])
        self.script('bounce', lambda c: [ReturnToHand(c.state.players[1].board[0])])
        g = self.game(board=('plain',), hand=('grant', 'bounce')); self.play(g, 'grant'); self.play(g, 'bounce')
        self.play(g, 'plain'); self.use(g)
        self.assertEqual((self.armor(g), self.plan(g).repetitions), (1, 1)); self.check(g)

    def test_empty_success_captures_policy_but_has_no_payload_batch(self):
        self.installer((), clear_existing=True); g = self.game(hand=('install',)); self.play(g, 'install'); self.use(g)
        self.assertEqual(self.plan(g).repetitions, 2)
        self.assertFalse(g.state.hero_power_history[0].payloads)
        self.assertFalse(self.rows(g)); self.assertFalse(self.batches(g)); self.check(g)

    def test_failed_indirect_root_has_default_plan_without_repeat_positions(self):
        self.power('target', lambda c: [GainArmor(1, 9)],
                   targeting=TargetSpec(kinds=(CardType.MINION,), relation='enemy'))
        g = self.game(power='target', hand=('trigger',)); self.play(g)
        self.assertEqual(g.state.hero_power_history[0].failure, 'no_target')
        self.assertEqual(self.plan(g), HeroPowerRepeatPlan()); self.assertFalse(self.rows(g)); self.check(g)

    def test_repeat_fact_query_orders_nested_execution_and_excludes_queue(self):
        g = self.waiting(); self.assertEqual([r.capture.repeat_index for r in activated_power_payloads(g.state, 1)], [1])
        self.choose(g)
        self.assertEqual([r.capture.repeat_index for r in activated_power_payloads(g.state, 1, completed=False)], [2])
        self.choose(g); self.assertEqual(len(activated_power_payloads(g.state, 1, completed=True, origin='manual')), 2); self.check(g)

    def test_player_views_hide_repeat_plan_sources_and_internal_positions(self):
        g = self.waiting()
        for viewer in (1, 2):
            text = json.dumps((g.observe(viewer), g.player_events(viewer), g.for_player(viewer).legal_actions()))
            for field in ('repeat_plan', 'contributors', 'repeat_index', 'hero_power_payload_history', 'hero_power_payload_batches'):
                self.assertNotIn('"'+field+'"', text)
        self.check(g)

    def test_invalid_specs_and_attachment_declarations_fail_strictly(self):
        for value in (True, False, 0, 1, -1, '2'):
            with self.subTest(value=value), self.assertRaises(ValueError): HeroPowerRepeatSpec(value)
        with self.assertRaises(ValueError): AbilityInstance(99, 'hero_power_repeat')
        with self.assertRaises(ValueError): AbilityInstance(99, 'on_use', behavior_id='power', hero_power_repeat=HeroPowerRepeatSpec())

    def test_nonminion_repeat_declaration_rejected(self):
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('bad', 'bad', CardType.SPELL, hero_power_repeats=(HeroPowerRepeatSpec(),)))

    def test_capture_repeat_index_corruption_and_missing_position_rejected(self):
        g = self.waiting()
        for value in (0, True, 1, 3):
            s = g.snapshot(); s['state']['hero_power_payload_history'][1]['capture']['repeat_index'] = value
            with self.subTest(value=value): self.reject(s)
        s = g.snapshot(); s['state']['hero_power_payload_history'].pop(); self.reject(s)

    def test_root_and_batch_plan_mismatch_rejected(self):
        g = self.waiting()
        for field in ('hero_power_history', 'hero_power_payload_batches'):
            s = g.snapshot(); key = 'repeat_plan' if field == 'hero_power_history' else 'plan'
            s['state'][field][0][key] = {'repetitions': 1, 'contributors': []}
            with self.subTest(field=field): self.reject(s)

    def test_contributor_carrier_card_player_and_ability_corruption_rejected(self):
        g = self.waiting()
        for field, value in (('carrier_id', 99999), ('card_id', 'plain'), ('player_id', 2)):
            s = g.snapshot(); s['state']['hero_power_history'][0]['repeat_plan']['contributors'][0][field] = value
            with self.subTest(field=field): self.reject(s)
        s = g.snapshot(); s['state']['hero_power_history'][0]['repeat_plan']['contributors'][0]['ability']['id'] = 99999; self.reject(s)

    def test_plan_count_and_source_order_are_validated(self):
        self.power('waiting', lambda c: [self.pause(c, GainArmor(1, 1))])
        g = self.game(power='waiting', board=('double', 'triple')); self.use(g)
        for change in ('count', 'order', 'duplicate'):
            s = g.snapshot(); plan = s['state']['hero_power_history'][0]['repeat_plan']
            if change == 'count': plan['repetitions'] = 2
            elif change == 'order': plan['contributors'].reverse()
            else: plan['contributors'].append(plan['contributors'][0])
            with self.subTest(change=change): self.reject(s)

    def test_swapped_repeat_queue_rejected_even_with_same_behavior(self):
        g = self.waiting(multiple=True); s = g.snapshot(); queue = self.queue(s)
        starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        a, b = (queue.index(w) for w in starts[:2]); queue[a], queue[b] = queue[b], queue[a]; self.reject(s)

    def test_missing_repeat_finish_and_raw_callback_bypass_rejected(self):
        g = self.waiting(); s = g.snapshot(); queue = self.queue(s)
        queue.remove(self.named(s['resolution_frame'], 'FinishHeroPowerPayload')[0]); self.reject(s)
        s = g.snapshot(); context = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[0]['fields']['context']
        raw = {'type': 'hs_sim.engine.resolver.BehaviorCall', 'fields': {'behavior_id': 'waiting', 'context': context}}
        self.queue(s).insert(0, raw); self.reject(s)

    def test_retained_result_scope_and_repeat_index_cannot_be_confused(self):
        g = self.waiting(retained=True)
        for key, value in (('iteration', 2), ('outcome_id', None), ('repeat_index', 3)):
            s = g.snapshot(); s['state']['hero_power_payload_history'][1]['capture'][key] = value
            with self.subTest(key=key): self.reject(s)

    def test_coordinated_position_and_plan_trim_still_cannot_hide_board_source(self):
        g = self.waiting(); s = g.snapshot(); starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        self.queue(s).remove(starts[0]); state = s['state']
        state['hero_power_history'][0]['repeat_plan'] = {'repetitions': 1, 'contributors': []}
        state['hero_power_payload_batches'][0]['plan'] = {'repetitions': 1, 'contributors': []}
        state['hero_power_payload_history'].pop()
        # Synchronize the completion receipt's claimed plan too. Its actual
        # accepted board still proves that an original double source existed.
        c = self.named(s['resolution_frame'], 'FinishHeroPower')[0]['fields']['context']['fields']
        c['state']['state']['hero_power_history'][0]['repeat_plan'].update(repetitions=1, contributors=[])
        c['power']['fields']['repeat_plan']['fields'].update(repetitions=1, contributors={'tuple': []})
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'complete acceptance view'):
            self.restore(s)

    def test_coordinated_root_batch_history_and_queued_context_trim_rejected(self):
        g = self.waiting(multiple=True); s = g.snapshot(); starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        # Drop B2, and make B1 claim a one-repeat plan consistently everywhere;
        # the captured physical board still contains the original double source.
        for w in starts:
            if w['fields']['context']['fields']['power_payload']['fields']['repeat_index'] == 2:
                self.queue(s).remove(w)
        state = s['state']; state['hero_power_payload_history'] = state['hero_power_payload_history'][::2]
        for index, row in enumerate(state['hero_power_payload_history'], 1): row['capture']['id'] = index
        for item in (state['hero_power_history'][0]['repeat_plan'], state['hero_power_payload_batches'][0]['plan']):
            item.update(repetitions=1, contributors=[])
        c = self.named(s['resolution_frame'], 'FinishHeroPower')[0]['fields']['context']['fields']
        c['state']['state']['hero_power_history'][0]['repeat_plan'].update(repetitions=1, contributors=[])
        c['power']['fields']['repeat_plan']['fields'].update(repetitions=1, contributors={'tuple': []})
        for work in self.named(s['resolution_frame'], 'InvokeHeroPowerPayload'):
            c = work['fields']['context']['fields']; cs = c['state']['state']
            cs['hero_power_payload_history'] = cs['hero_power_payload_history'][::2]
            for index, row in enumerate(cs['hero_power_payload_history'], 1): row['capture']['id'] = index
            for item in (cs['hero_power_history'][0]['repeat_plan'], cs['hero_power_payload_batches'][0]['plan']):
                item.update(repetitions=1, contributors=[])
            c['power']['fields']['repeat_plan']['fields'].update(repetitions=1, contributors={'tuple': []})
            c['power_payload']['fields']['id'] = 2
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'accept|source|plan'):
            self.restore(s)

    def test_queued_extra_cannot_borrow_a_started_fresh_context(self):
        g = self.waiting(); s = g.snapshot()
        restored = self.restore(s); self.choose(restored)
        fresh = restored.snapshot()['state']; fresh['pending_choice'] = None
        invoke = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[0]
        invoke['fields']['context']['fields']['state']['state'] = fresh
        self.assertEqual(fresh['hero_power_payload_history'][1]['execution_order'], 2)
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'queued acceptance view'):
            self.restore(s)

    def test_fresh_extra_choice_restores_after_original_source_was_silenced(self):
        self.power('waiting', lambda c: [self.pause(c, Silence(c.state.players[1].board[0]))]
            if c.power_payload.repeat_index == 1 else [self.pause(c, GainArmor(1, 2))])
        g = self.game(power='waiting'); self.use(g); self.choose(g)
        self.assertEqual([r.completed for r in self.rows(g)], [True, False])
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 2]); self.check(g)
        restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.assertEqual(self.armor(g), 2); self.check(g)

    def test_final_extra_choice_cannot_shorten_surviving_original_source_policy(self):
        self.power('waiting', lambda c: [self.pause(c, GainArmor(1, 1))])
        g = self.game(power='waiting', board=('triple',)); self.use(g); self.choose(g)
        s = g.snapshot(); queue = self.queue(s)
        queue.remove(self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[0])
        s['state']['hero_power_payload_history'].pop()
        for plan in (s['state']['hero_power_history'][0]['repeat_plan'],
                     s['state']['hero_power_payload_batches'][0]['plan']):
            plan['repetitions'] = 2
            plan['contributors'][0]['ability']['hero_power_repeat']['repetitions'] = 2
        contributor = s['state']['hero_power_history'][0]['repeat_plan']['contributors'][0]
        source = s['state']['entities'][str(contributor['carrier_id'])]
        self.assertEqual(source['abilities'][0]['hero_power_repeat']['repetitions'], 3)
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'surviving ability'):
            self.restore(s)

    def test_previous_snapshot_schema_is_explicitly_rejected(self):
        g = self.waiting(); s = g.snapshot(); self.assertEqual(s['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        s['schema_version'] = 94; self.reject(s)


class PowerRepeatRepresentativeTests(unittest.TestCase):
    setUp = activations.WispriderTests.setUp
    game = activations.WispriderTests.game
    play = activations.WispriderTests.play

    def check(self, game):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.replay import build_replay, replay
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(game.snapshot())),
            build_registry()).snapshot(), game.snapshot())
        self.assertEqual(replay(build_replay(game), build_registry()).snapshot(), game.snapshot())

    def test_frozen_singalong_buddy_metadata_and_single_repeat_declaration(self):
        from hs_sim.engine.representative import EXPECTED_CARD_HASHES
        from hs_sim.targets import canonical_digest, load_baseline
        card = self.r.card('TOY_528')
        self.assertEqual((card.name, card.cost, card.attack, card.health), ('伴唱机', 3, 2, 4))
        self.assertEqual(card.metadata.tribes, ('mech',))
        self.assertEqual(card.hero_power_repeats, (HeroPowerRepeatSpec(),))
        row = next(row for row in load_baseline().support['cards'] if row['id'] == 'TOY_528')
        digest = '5f0115d3b003195df90c5eac4f485018f87420a68b0eb77b2162787d7d2b6699'
        self.assertEqual((row['data_sha256'], canonical_digest(row['data']), EXPECTED_CARD_HASHES['TOY_528']),
                         (digest, digest, digest))
        game = self.game(hand=('TOY_528',), board=()); entity = self.play(game, 'TOY_528')
        ability = active_abilities(game.state.entities[entity], 'hero_power_repeat')
        self.assertEqual(len(ability), 1)
        self.assertEqual((ability[0].hero_power_repeat, ability[0].origin), (HeroPowerRepeatSpec(), 'printed'))
        self.check(game)

    def test_manual_real_power_repeats_effect_with_one_payment_use_and_inspire(self):
        game = self.game(hero='HERO_01', power='HERO_01bp', hand=('TOY_528',), board=('AT_082',))
        self.play(game, 'TOY_528'); power = game.state.players[1].hero_power_id
        game.apply(UseHeroPower(1, power))
        state = game.state; root = state.hero_power_history[0]
        self.assertEqual((state.entities[state.players[1].hero_id].armor, state.players[1].mana), (4, 5))
        self.assertEqual((root.cost, state.entities[power].uses_this_turn, state.players[1].hero_power_uses_this_turn),
                         (2, 1, 1))
        self.assertEqual(state.entities[state.players[1].board[0]].attack, 2)
        self.assertEqual(sum(e.kind == 'mana_spent' and e.source_id == power for e in game.events), 1)
        self.assertEqual(sum(e.kind == 'hero_power_used' for e in game.events), 1)
        self.assertEqual([r.capture.repeat_index for r in state.hero_power_payload_history], [1, 2])
        completion = next(e for e in game.events if e.kind == 'hero_power_used')
        self.assertTrue(is_inspire(state, completion, 1))
        with self.assertRaises(IllegalAction): game.apply(UseHeroPower(1, power))
        self.check(game)

    def test_wisprider_and_manual_native_example_restore_four_subjects(self):
        from examples.power_repeats import run
        game, snapshot = run(); state = game.state
        self.assertEqual(snapshot['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(len(snapshot['state']['hero_power_payload_history']), 2)
        self.assertEqual([p.origin for p in state.hero_power_history], ['effect', 'manual'])
        self.assertEqual([p.repeat_plan.repetitions for p in state.hero_power_history], [2, 2])
        self.assertEqual([(r.capture.power_id, r.capture.repeat_index) for r in state.hero_power_payload_history],
                         [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual((state.players[1].mana, state.entities[state.players[2].hero_id].health), (0, 26))
        indirect = next(e for e in game.events if e.kind == 'hero_power_triggered')
        self.assertFalse(is_inspire(state, indirect, 1)); self.check(game)

    def test_two_real_sources_merge_and_silence_changes_next_indirect_root(self):
        from hs_sim.engine import PlayCard
        game = self.game(hero='HERO_01', power='HERO_01bp', board=('TOY_528', 'TOY_528'),
            hand=('EX1_332', 'EX1_332', 'EDR_519'))
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.assertEqual(len(game.state.hero_power_history[0].repeat_plan.contributors), 2)
        self.assertEqual(game.state.hero_power_history[0].repeat_plan.repetitions, 2)
        for target in tuple(game.state.players[1].board):
            card = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == 'EX1_332')
            game.apply(PlayCard(1, card, target))
        activator = self.play(game)
        state = game.state; roots = state.hero_power_history
        self.assertEqual([p.repeat_plan.repetitions for p in roots], [2, 1])
        self.assertEqual((roots[1].activator_id, roots[1].cost, roots[1].payment), (activator, None, None))
        self.assertEqual((state.entities[state.players[1].hero_id].armor, state.players[1].hero_power_uses_this_turn), (6, 1))
        self.assertEqual(len(state.hero_power_payload_history), 3); self.check(game)


if __name__ == '__main__': unittest.main()
