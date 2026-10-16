"""M5-13d-02l-02: one root activation and durable on_use ability facts."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import test_m5_power_activations as foundation
from hs_sim.engine import (CardDefinition, CardType, ChooseBranch, ChooseOneSpec,
    EndTurn, Game, HeroPowerReference, IllegalAction, Keyword, PlayerSetup,
    ResolutionError, ResolutionLimitExceeded, RewindSpec, Ruleset, Scenario,
    SelectChoice, SnapshotError, TriggerHeroPower, TriggerSpec, UseHeroPower)
from hs_sim.engine.effects import (ChoiceOption, Damage, Effect, GainArmor,
    ReplaceHeroPower, RequestChoice, Summon)
from hs_sim.engine.hero_powers import RemoveHeroPower
from hs_sim.engine.lifecycle import active_abilities, attachment_id
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.power_payloads import activated_power_payloads
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash


@dataclass(frozen=True)
class InstallPowerPayloads(Effect):
    """Test-only ability installation using the ordinary effect dispatcher."""
    target_id: int
    behaviors: tuple[str, ...]
    source_id: int | None = None
    consumed: bool = False
    expires_turn: int | None = None
    clear_existing: bool = False


def install_power_payloads(r, effect):
    power = r.state.entities[effect.target_id]
    if effect.clear_existing:
        power.abilities = [a for a in power.abilities if a.kind != 'on_use']
    for behavior in effect.behaviors:
        r.registry.behavior(behavior)
        power.abilities.append(AbilityInstance(attachment_id(r.state), 'on_use',
            source_id=effect.source_id, behavior_id=behavior, consumed=effect.consumed,
            expires_turn=effect.expires_turn))


class PowerPayloadTests(unittest.TestCase):
    power = foundation.PowerActivationTests.power
    script = foundation.PowerActivationTests.script
    watch = foundation.PowerActivationTests.watch
    play = foundation.PowerActivationTests.play
    use = foundation.PowerActivationTests.use
    source = foundation.PowerActivationTests.source
    armor = foundation.PowerActivationTests.armor
    choose = foundation.PowerActivationTests.choose
    choice_power = foundation.PowerActivationTests.choice_power

    def setUp(self):
        foundation.PowerActivationTests.setUp(self)
        self.mechanics = default_mechanics('power-payload-fixtures-v1')
        self.mechanics.register(InstallPowerPayloads, install_power_payloads)

    def game(self, hand=('trigger',), power='power', board=(), enemy=(), mana=10,
             rules=None, seed=61, extras=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board,
            deck=('plain',)*4, hero_power_card_id=power,
            additional_hero_power_card_ids=extras, mana=mana, max_mana=10),
            PlayerSetup('hero', hand=('plain',), board=enemy, deck=('plain',)*4,
                hero_power_card_id='power', mana=10, max_mana=10)), seed=seed),
            self.r, rules, self.mechanics)

    def restore(self, snapshot):
        return Game.from_snapshot(json.loads(json.dumps(snapshot)), self.r, self.mechanics)

    def check(self, g):
        s = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(self.restore(s).snapshot(), s)
        self.assertEqual(g.clone().snapshot(), s)
        self.assertEqual(replay(build_replay(g), self.r, self.mechanics).snapshot(), s)

    def reject(self, s):
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError) as error:
            self.restore(s)
        self.assertNotIn('digest mismatch', str(error.exception))

    def rows(self, g): return g.state.hero_power_payload_history
    def batches(self, g): return g.state.hero_power_payload_batches
    def pause(self, c, effect):
        return RequestChoice(c.player_id, (ChoiceOption('ok', 'ok', (effect,)),),
                             source_id=c.source_id)

    def installer(self, behaviors, **kw):
        self.script('install', lambda c: [InstallPowerPayloads(
            c.state.players[1].hero_power_id, tuple(behaviors), c.source_id, **kw)])

    def multiple(self, behavior='power', hand=(), **kw):
        self.installer((behavior, behavior))
        g = self.game(hand=('install', *hand), **kw)
        self.play(g, 'install')
        return g

    def waiting(self, multiple=False):
        self.power('waiting', lambda c: [self.pause(c, GainArmor(1, 2))])
        if multiple:
            g = self.multiple(power='waiting')
        else:
            g = self.game(power='waiting', hand=())
        self.use(g)
        return g

    def rewind_power(self, cid='rewinding', fn=None, retries=1):
        self.power(cid, fn or (lambda c: [GainArmor(1, c.rewind_attempt+1)]),
                   keywords=(Keyword.REWIND,), rewind=RewindSpec(retries))

    def retainer(self):
        self.r.register_card(CardDefinition('retainer', 'retainer', CardType.MINION,
            health=4, retain_rewind_outcomes=True))

    def named(self, value, suffix):
        """Return all serialized dataclass/control objects with this type name."""
        found = []
        if isinstance(value, dict):
            if str(value.get('type', '')).endswith('.'+suffix): found.append(value)
            for key, child in value.items():
                if key == 'fields' and value.get('type') == 'hs_sim.engine.paid_hand_acceptance.PaidHandChoiceBoundaryProof':
                    for field, operand in child.items():
                        if field != 'work':
                            found.extend(self.named(operand, suffix))
                else:
                    found.extend(self.named(child, suffix))
        elif isinstance(value, list):
            for child in value: found.extend(self.named(child, suffix))
        return found

    def test_manual_root_freezes_printed_payload_and_single_completion(self):
        g = self.game(hand=()); ability = active_abilities(self.source(g), 'on_use')[0]
        self.use(g); root = g.state.hero_power_history[0]; row = self.rows(g)[0]
        self.assertEqual(root.payloads, (ability,))
        self.assertEqual((row.capture.power_id, row.capture.batch_id, row.capture.id), (1, 1, 1))
        self.assertEqual(row.capture.ability, ability)
        self.assertEqual((row.execution_order, row.completed, row.interrupted), (1, True, False))
        self.assertEqual((g.state.players[1].mana, self.source(g).uses_this_turn,
            g.state.players[1].hero_power_uses_this_turn), (8, 1, 1))
        self.assertEqual([e.kind for e in g.events if e.kind.startswith('hero_power')],
                         ['hero_power_started', 'hero_power_used'])
        self.check(g)

    def test_indirect_zero_mana_records_payload_without_payment_or_use(self):
        g = self.game(mana=0); activator = self.play(g); root = g.state.hero_power_history[0]
        self.assertEqual((root.origin, root.activator_id, root.cost, root.payment),
                         ('effect', activator, None, None))
        self.assertEqual((self.rows(g)[0].capture.power_id, self.armor(g)), (1, 1))
        self.assertEqual((g.state.players[1].mana, self.source(g).uses_this_turn,
            g.state.players[1].hero_power_uses_this_turn), (0, 0, 0))
        self.assertEqual([e.kind for e in g.events if e.kind.startswith('hero_power')],
                         ['hero_power_trigger_started', 'hero_power_triggered'])
        self.check(g)

    def test_same_behavior_instances_preserve_independent_ability_ids(self):
        g = self.multiple(); abilities = active_abilities(self.source(g), 'on_use'); self.use(g)
        self.assertEqual([r.capture.ability for r in self.rows(g)], list(abilities))
        self.assertEqual(len({r.capture.ability.id for r in self.rows(g)}), 3)
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 2, 3])
        self.assertEqual([r.capture.ability.origin for r in self.rows(g)], ['printed', 'granted', 'granted'])
        self.assertEqual(self.armor(g), 3); self.assertEqual(len(self.batches(g)), 1)
        self.assertEqual((g.state.players[1].mana, self.source(g).uses_this_turn), (8, 1))
        self.assertEqual(sum(e.kind == 'hero_power_used' for e in g.events), 1); self.check(g)

    def test_multiple_callbacks_keep_original_accepted_state(self):
        self.power('make', lambda c: [Summon(1, 'plain')])
        self.r.register_behavior('count', lambda c: [GainArmor(1, len(c.state.players[1].board))])
        self.installer(('count',)); g = self.game(hand=('install',), power='make')
        self.play(g, 'install'); self.use(g)
        self.assertEqual((len(g.state.players[1].board), self.armor(g)), (1, 0))
        self.assertEqual(len(self.rows(g)), 2); self.check(g)

    def test_identity_controls_preserve_legacy_events_and_physical_state(self):
        def run(legacy):
            self.setUp()
            self.power('probe', lambda c: [Damage(c.state.players[1].board[0], 4), Summon(1, 'plain')])
            self.r.register_behavior('count', lambda c: [GainArmor(1, len(c.state.players[1].board))])
            self.installer(('count', 'power'))
            g = self.game(power='probe', board=('plain',), hand=('install',)); self.play(g, 'install')
            if legacy:
                def old_schedule(r, power, **kw):
                    return [r.call(a.behavior_id, power.source_id, power.player_id,
                                   power.target_id, power=power) for a in power.payloads]
                with patch('hs_sim.engine.power_payloads.schedule', old_schedule), \
                        patch('hs_sim.engine.power_payloads.validate_history', lambda *args: None), \
                        patch('hs_sim.engine.power_payloads.validate_queue', lambda *args: None):
                    self.use(g)
            else:
                self.use(g); self.check(g)
            return g
        current = run(False); legacy = run(True)
        self.assertEqual(current.events, legacy.events)
        a = current.snapshot()['state']; b = legacy.snapshot()['state']
        for key in ('hero_power_payload_history', 'hero_power_payload_batches'):
            a.pop(key); b.pop(key)
        self.assertEqual(a, b)

    def test_payload_context_names_exact_ability_and_original_root(self):
        def inspect(c):
            self.assertIsNotNone(c.power_payload)
            self.assertEqual(c.power_payload.power_id, c.power.id)
            self.assertIn(c.power_payload.ability, c.power.payloads)
            self.assertEqual(c.source_id, c.power.source_id)
            self.assertEqual((c.target_id, c.power_payload.iteration), (c.power.target_id, 1))
            return [GainArmor(1, c.power_payload.id)]
        self.power('inspect', inspect); g = self.multiple('inspect', power='inspect')
        self.use(g); self.assertEqual(self.armor(g), 6); self.check(g)

    def test_start_and_finish_reactions_have_root_but_no_subject_context(self):
        def inspect(c):
            self.assertIsNotNone(c.power); self.assertIsNone(c.power_payload)
            return [GainArmor(1, 2)]
        self.watch('start', inspect, 'hero_power_started')
        self.watch('finish', inspect, 'hero_power_used')
        g = self.game(hand=(), board=('start', 'finish')); self.use(g)
        self.assertEqual(self.armor(g), 5); self.check(g)

    def test_payment_reaction_choice_restores_before_root_payload_was_captured(self):
        def paid(c):
            self.assertIsNone(c.power)
            self.assertEqual(c.state.hero_power_history[-1].payloads, ())
            self.assertIsNone(c.power_payload)
            return [self.pause(c, GainArmor(1, 2))]
        self.watch('paywait', paid, 'mana_spent')
        g = self.game(board=('paywait',), hand=()); self.use(g)
        self.assertEqual(len(activated_power_payloads(g.state, 1)), 0); self.check(g)
        restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_noop_behavior_still_has_actual_completed_fact(self):
        self.power('noop', lambda c: []); g = self.game(power='noop', hand=()); self.use(g)
        self.assertEqual((self.rows(g)[0].execution_order, self.rows(g)[0].completed), (1, True))
        self.assertTrue(g.state.hero_power_history[0].completed); self.check(g)

    def test_empty_active_power_has_root_and_no_payload_batch(self):
        self.installer((), clear_existing=True); g = self.game(hand=('install',))
        self.play(g, 'install'); self.use(g)
        self.assertEqual(g.state.hero_power_history[0].payloads, ())
        self.assertTrue(g.state.hero_power_history[0].completed)
        self.assertFalse(self.rows(g)); self.assertFalse(self.batches(g)); self.check(g)

    def test_consumed_grants_do_not_enter_frozen_root(self):
        self.installer(('power',), consumed=True); g = self.game(hand=('install',))
        self.play(g, 'install'); self.use(g)
        self.assertEqual(len(g.state.hero_power_history[0].payloads), 1)
        self.assertEqual(len(self.rows(g)), 1); self.assertEqual(self.armor(g), 1); self.check(g)

    def test_expired_grants_do_not_enter_next_activation(self):
        self.installer(('power',), expires_turn=1); g = self.game(hand=('install',))
        self.play(g, 'install'); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.use(g)
        self.assertEqual(len(g.state.hero_power_history[0].payloads), 1)
        self.assertEqual(self.armor(g), 1); self.check(g)

    def test_passive_indirect_failure_has_no_subjects(self):
        self.r.register_card(CardDefinition('passive', 'passive', CardType.HERO_POWER,
            passive_hero_power=True, triggers=(TriggerSpec('turn_started', 'power'),)))
        g = self.game(power='passive'); self.play(g); root = g.state.hero_power_history[0]
        self.assertEqual((root.failure, root.payloads, root.completed), ('passive', (), True))
        self.assertFalse(self.rows(g)); self.assertFalse(self.batches(g)); self.check(g)

    def test_no_target_failure_has_no_subjects(self):
        from hs_sim.engine import TargetSpec
        self.power('target', lambda c: [GainArmor(1, 7)],
                   targeting=TargetSpec(kinds=(CardType.MINION,), relation='enemy'))
        g = self.game(power='target'); self.play(g)
        self.assertEqual(g.state.hero_power_history[0].failure, 'no_target')
        self.assertEqual(g.state.hero_power_history[0].payloads, ())
        self.assertFalse(self.rows(g)); self.assertFalse(self.batches(g)); self.check(g)

    def test_invalid_explicit_target_failure_never_starts_subject(self):
        self.script('badtarget', lambda c: [TriggerHeroPower(1, c.source_id, 99999, targeting='explicit')])
        g = self.game(hand=('badtarget',)); self.play(g, 'badtarget')
        self.assertEqual(g.state.hero_power_history[0].failure, 'invalid_target')
        self.assertEqual(activated_power_payloads(g.state, 1), ()); self.check(g)

    def test_illegal_manual_action_rolls_back_without_identity(self):
        g = self.game(mana=1); before = g.snapshot()
        with self.assertRaises(IllegalAction): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_start_replacement_keeps_old_accepted_abilities(self):
        self.power('other', lambda c: [GainArmor(1, 9)])
        self.watch('replace', lambda c: [ReplaceHeroPower(1, 'other')], 'hero_power_started')
        g = self.multiple(board=('replace',)); old = self.source(g).id; self.use(g)
        self.assertEqual((self.armor(g), self.source(g).card_id), (3, 'other'))
        self.assertEqual(g.state.hero_power_history[0].source_id, old)
        self.assertEqual({r.capture.ability.behavior_id for r in self.rows(g)}, {'power'}); self.check(g)

    def test_indirect_start_removal_keeps_old_payload(self):
        self.watch('remove', lambda c: [RemoveHeroPower(1)], 'hero_power_trigger_started')
        g = self.game(board=('remove',)); old = self.source(g).id; self.play(g)
        self.assertIsNone(g.state.players[1].hero_power_id)
        self.assertEqual((self.armor(g), g.state.hero_power_history[0].source_id), (1, old))
        self.assertTrue(self.rows(g)[0].completed); self.check(g)

    def test_start_added_ability_is_not_in_already_accepted_payload(self):
        self.watch('installwatch', lambda c: [InstallPowerPayloads(
            c.power.source_id, ('power',), c.source_id)], 'hero_power_started')
        g = self.game(board=('installwatch',)); self.use(g)
        self.assertEqual((len(g.state.hero_power_history[0].payloads), len(self.rows(g))), (1, 1))
        self.assertEqual(len(active_abilities(self.source(g), 'on_use')), 2); self.check(g)

    def test_same_entity_nested_roots_and_lifo_completion(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id), GainArmor(1, 2)]
            if c.power.origin == 'manual' else [GainArmor(1, 1)])
        g = self.game(power='nested', hand=()); self.use(g)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1])
        self.assertEqual([r.capture.power_id for r in self.rows(g)], [1, 2])
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 2])
        self.assertEqual([e.kind for e in g.events if e.kind in ('hero_power_used', 'hero_power_triggered')],
                         ['hero_power_triggered', 'hero_power_used'])
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_nested_subject_execution_order_differs_from_capture_order(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id)]
            if c.power.origin == 'manual' else [])
        self.installer(('power',)); g = self.game(power='nested', hand=('install',))
        self.play(g, 'install'); self.use(g)
        self.assertEqual([r.capture.power_id for r in self.rows(g)], [1, 1, 2, 2])
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, 4, 2, 3])
        self.assertEqual([r.capture.id for r in activated_power_payloads(g.state, 1)], [1, 3, 4, 2])
        self.assertEqual(self.armor(g), 2); self.check(g)

    def test_multiple_installed_slots_have_separate_root_and_ability_identity(self):
        g = self.game(extras=('power',), hand=()); ids = g.state.players[1].hero_power_ids
        g.apply(UseHeroPower(1, ids[1])); g.apply(UseHeroPower(1, ids[0]))
        self.assertEqual([p.source_id for p in g.state.hero_power_history], [ids[1], ids[0]])
        self.assertEqual(len({r.capture.ability.id for r in self.rows(g)}), 2)
        self.assertEqual((self.armor(g), g.state.players[1].mana,
                          g.state.players[1].hero_power_uses_this_turn), (2, 6, 2)); self.check(g)

    def test_directed_indirect_slot_uses_frozen_reference(self):
        self.power('other', lambda c: [GainArmor(1, 4)])
        self.script('directed', lambda c: [TriggerHeroPower(1, c.source_id,
            power=HeroPowerReference.capture(c.state.entities[c.state.players[1].additional_hero_power_ids[0]]))])
        g = self.game(extras=('other',), hand=('directed',)); self.play(g, 'directed')
        self.assertEqual(g.state.hero_power_history[0].card_id, 'other')
        self.assertEqual(self.rows(g)[0].capture.ability.behavior_id, 'other')
        self.assertEqual(self.armor(g), 4); self.check(g)

    def test_queued_siblings_are_not_activated_until_they_begin(self):
        g = self.waiting(multiple=True); rows = self.rows(g)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r.execution_order for r in rows], [1, None, None])
        self.assertEqual(len(activated_power_payloads(g.state, 1, completed=False)), 1)
        self.assertTrue(all(not r.completed and not r.interrupted for r in rows)); self.check(g)
        self.choose(g); self.assertTrue(all(r.completed for r in self.rows(g)))
        self.assertEqual(self.armor(g), 4); self.check(g)

    def test_independent_choices_resume_each_ability_with_own_identity(self):
        self.power('wait', lambda c: [self.pause(c, GainArmor(1, c.power_payload.id))])
        g = self.multiple('wait', power='wait'); self.use(g)
        for index in range(3):
            self.assertEqual([r.execution_order for r in self.rows(g)],
                             list(range(1, index+2))+[None]*(2-index))
            restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.armor(g), 6)

    def test_nested_pending_choice_restores_all_distinct_subject_closers(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')]
            if c.power.origin == 'manual' else [self.pause(c, GainArmor(1, 2))])
        g = self.game(power='nested', hand=()); self.use(g)
        self.assertEqual(len(self.rows(g)), 2)
        self.assertTrue(all(not r.completed for r in self.rows(g))); self.check(g)
        restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertTrue(all(r.completed for r in self.rows(g))); self.check(g)

    def test_random_indirect_choices_finish_subject_without_player_pause(self):
        self.choice_power(); g = self.game(power='choice'); self.play(g)
        self.assertIsNone(g.state.pending_choice); self.assertTrue(self.rows(g)[0].completed)
        self.assertTrue(any(e.kind == 'hero_power_choice_automatic' for e in g.events)); self.check(g)

    def test_player_indirect_choice_restores_pending_subject(self):
        self.choice_power(); self.script('ask', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')])
        g = self.game(power='choice', hand=('ask',)); self.play(g, 'ask'); self.check(g)
        self.assertEqual(len(activated_power_payloads(g.state, 1, completed=False)), 1)
        restored = self.restore(g.snapshot()); self.choose(g, '3'); self.choose(restored, '3')
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)

    def test_invalid_choice_preserves_running_and_queued_identity(self):
        g = self.waiting(multiple=True); before = g.snapshot(); c = g.state.pending_choice
        with self.assertRaises(ValueError): g.apply(SelectChoice(c.player_id, c.id, ()))
        self.assertEqual(g.snapshot(), before)

    def test_callback_failure_rolls_back_payment_batches_and_roots(self):
        def fail(c): raise ValueError('payload fixture fails')
        self.power('bad', fail); g = self.game(power='bad', hand=()); before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'payload fixture fails'): self.use(g)
        self.assertEqual(g.snapshot(), before)

    def test_post_choice_failure_rolls_back_only_selected_action(self):
        self.power('badchoice', lambda c: [RequestChoice(1, (
            ChoiceOption('bad', 'bad', (TriggerHeroPower(1, 99999),)),
            ChoiceOption('ok', 'ok', (GainArmor(1, 3),))), source_id=c.source_id)])
        g = self.game(power='badchoice', hand=()); self.use(g); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), before); self.choose(g, 'ok')
        self.assertTrue(self.rows(g)[0].completed); self.check(g)

    def test_recursive_subject_work_uses_shared_resolution_budget(self):
        self.power('loop', lambda c: [TriggerHeroPower(1, c.source_id)])
        g = self.game(power='loop', rules=Ruleset(max_resolution_steps=30)); before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded): self.play(g)
        self.assertEqual(g.snapshot(), before)

    def test_terminal_start_reaction_keeps_queued_subject_interrupted(self):
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30, c.source_id)], 'hero_power_started')
        g = self.multiple(board=('fatal',)); self.use(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertTrue(all(r.interrupted and not r.completed and r.execution_order is None for r in self.rows(g)))
        self.assertEqual(activated_power_payloads(g.state, 1), ())
        self.assertEqual(self.armor(g), 0); self.check(g)

    def test_terminal_first_subject_interrupts_unstarted_siblings(self):
        self.power('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30, c.source_id), GainArmor(1, 9)])
        g = self.multiple(power='fatal'); self.use(g)
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, None, None])
        self.assertTrue(all(r.interrupted and not r.completed for r in self.rows(g)))
        self.assertEqual(len(activated_power_payloads(g.state, 1)), 1)
        self.assertEqual(self.armor(g), 0); self.check(g)

    def test_ordinary_rewind_replaces_abandoned_subject_facts(self):
        self.rewind_power(); g = self.game(power='rewinding', hand=()); self.use(g); self.check(g)
        self.assertEqual(len(self.rows(g)), 1); self.choose(g, 'retry')
        self.assertEqual((len(g.state.hero_power_history), len(self.rows(g)), len(self.batches(g))), (1, 1, 1))
        self.assertEqual((self.rows(g)[0].capture.id, self.rows(g)[0].execution_order), (1, 1))
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn), (2, 8, 1))
        self.check(g)

    def test_retained_results_have_new_batches_and_frozen_root_payload(self):
        self.rewind_power(); self.retainer(); g = self.game(power='rewinding', board=('retainer',), hand=())
        self.use(g); rows = self.rows(g); root = g.state.hero_power_history[0]
        self.assertEqual([r.capture.iteration for r in rows], [1, 2])
        self.assertEqual([r.capture.outcome_id for r in rows], [1, 1])
        self.assertEqual([r.capture.batch_id for r in rows], [1, 2])
        self.assertEqual([r.capture.power_id for r in rows], [1, 1])
        self.assertEqual([b.payloads for b in self.batches(g)], [root.payloads, root.payloads])
        self.assertEqual((self.armor(g), g.state.players[1].mana, self.source(g).uses_this_turn), (3, 8, 1))
        self.assertEqual(sum(e.kind == 'hero_power_used' for e in g.events), 1); self.check(g)

    def test_retained_second_result_uses_new_state_and_original_ability_set(self):
        self.rewind_power('replace', lambda c: [ReplaceHeroPower(1, 'power'), Summon(1, 'plain'),
            GainArmor(1, len(c.state.players[1].board)+c.rewind_attempt+1)])
        self.retainer(); g = self.game(power='replace', board=('retainer',), hand=()); old = self.source(g).id
        self.use(g)
        self.assertEqual(self.source(g).card_id, 'power')
        self.assertEqual([r.capture.ability.behavior_id for r in self.rows(g)], ['replace', 'replace'])
        self.assertEqual(g.state.hero_power_history[0].source_id, old)
        self.assertEqual((self.armor(g), len(g.state.players[1].board)), (6, 3)); self.check(g)

    def test_retained_multi_subject_choices_restore_per_result(self):
        self.rewind_power('rewait', lambda c: [self.pause(c, GainArmor(1, c.rewind_attempt+1))])
        self.retainer(); g = self.multiple('rewait', power='rewait', board=('retainer',)); self.use(g)
        for _ in range(6):
            restored = self.restore(g.snapshot()); self.choose(g); self.choose(restored)
            self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)
        self.assertEqual(self.armor(g), 9); self.assertEqual(len(self.rows(g)), 6)
        self.assertEqual([b.iteration for b in self.batches(g)], [1, 2])

    def test_retained_nested_same_entity_uses_exact_root_and_outcome(self):
        self.rewind_power('nested', lambda c: [TriggerHeroPower(1, c.source_id), GainArmor(1, 2)]
            if c.power.origin == 'manual' else [GainArmor(1, 1)])
        self.retainer(); g = self.game(power='nested', board=('retainer',), hand=()); self.use(g)
        self.assertEqual([p.parent_id for p in g.state.hero_power_history], [None, 1, 1])
        self.assertEqual([r.capture.power_id for r in self.rows(g)], [1, 2, 2, 1, 3, 3])
        self.assertEqual([r.capture.outcome_id for r in self.rows(g)], [1, 2, 2, 1, 3, 3])
        self.assertEqual(self.armor(g), 8); self.check(g)

    def test_retained_start_reaction_terminal_has_no_started_result_or_batch(self):
        self.rewind_power(); self.retainer()
        self.watch('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30, c.source_id)], 'hero_power_started')
        g = self.game(power='rewinding', board=('retainer', 'fatal'), hand=()); self.use(g)
        self.assertEqual(g.state.status, 'finished')
        self.assertFalse(self.rows(g)); self.assertFalse(self.batches(g))
        self.assertTrue(g.state.hero_power_history[0].interrupted)
        self.assertTrue(g.state.rewind_outcomes[0].interrupted)
        self.assertEqual(g.state.rewind_outcomes[0].completed, 0); self.check(g)

    def test_retained_first_subject_terminal_preserves_one_interrupted_batch(self):
        self.rewind_power('fatal', lambda c: [Damage(c.state.players[2].hero_id, 30), GainArmor(1, 9)])
        self.retainer(); g = self.multiple(power='fatal', board=('retainer',)); self.use(g)
        self.assertEqual(len(self.batches(g)), 1)
        self.assertEqual([r.execution_order for r in self.rows(g)], [1, None, None])
        self.assertTrue(all(r.interrupted and not r.completed for r in self.rows(g)))
        self.assertTrue(g.state.hero_power_history[0].interrupted)
        self.assertTrue(g.state.rewind_outcomes[0].interrupted)
        self.assertEqual(self.armor(g), 0); self.check(g)

    def test_query_filters_root_origin_completion_and_turn(self):
        g = self.game(hand=('trigger', 'trigger')); self.use(g); self.play(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g)
        self.assertEqual([r.capture.id for r in activated_power_payloads(g.state, 1, origin='manual')], [1])
        self.assertEqual([r.capture.id for r in activated_power_payloads(g.state, 1, power_id=2)], [2])
        self.assertEqual([r.capture.id for r in activated_power_payloads(g.state, 1, turn=1, completed=True)], [1, 2])
        self.assertEqual(activated_power_payloads(g.state, 2), ())
        self.assertEqual(activated_power_payloads(g.state, 1, completed=False), ()); self.check(g)

    def test_query_arguments_reject_invalid_types_and_values(self):
        g = self.game()
        for player, kw in ((True, {}), (3, {}), (1, {'power_id': True}),
                (1, {'power_id': 0}), (1, {'completed': 1}), (1, {'origin': 'spell'}),
                (1, {'turn': False}), (1, {'turn': 0})):
            with self.subTest(player=player, kw=kw), self.assertRaises(ValueError):
                activated_power_payloads(g.state, player, **kw)

    def test_player_ports_hide_payload_identity_and_pending_queue(self):
        g = self.waiting(multiple=True)
        for viewer in (1, 2):
            text = json.dumps((g.observe(viewer), g.player_events(viewer), g.for_player(viewer).legal_actions()))
            for secret in ('hero_power_payload_history', 'hero_power_payload_batches',
                    'execution_order', 'power_payload', 'batch_id', 'payloads', 'HeroPowerPayloadCapture'):
                self.assertNotIn('"'+secret+'"', text)
        self.assertEqual(g.for_player(2).legal_actions()['actions'],[{'type':'concede'}]); self.check(g)

    def test_choose_one_payload_keeps_branch_target_and_root_context(self):
        def inspect(c):
            self.assertEqual((c.power.branch_id, c.target_id), ('a', c.power.target_id))
            self.assertEqual(c.power_payload.ability.behavior_id, 'engine.choose_one')
            return [GainArmor(1, 3)]
        self.r.register_behavior('branch_a', inspect)
        self.r.register_behavior('branch_b', lambda c: [GainArmor(1, 8)])
        spec = ChooseOneSpec((ChooseBranch('a', 'a', 'branch_a'), ChooseBranch('b', 'b', 'branch_b')),
                            ChooseBranch('both', 'both', 'branch_a'))
        self.r.register_card(CardDefinition('choicebranch', 'choicebranch', CardType.HERO_POWER,
            cost=2, choose_one=spec))
        g = self.game(power='choicebranch', hand=()); g.apply(UseHeroPower(1, self.source(g).id, branch_id='a'))
        self.assertEqual(self.armor(g), 3); self.check(g)

    def test_root_payload_corruption_rejected_after_rehash(self):
        g = self.waiting()
        for key, value in (('id', 99999), ('kind', 'on_play'), ('behavior_id', 'power'),
                           ('consumed', True), ('origin', 'granted')):
            s = g.snapshot(); s['state']['hero_power_history'][0]['payloads'][0][key] = value
            with self.subTest(key=key): self.reject(s)

    def test_root_missing_or_duplicate_payload_rejected(self):
        g = self.waiting()
        for change in ('missing', 'empty', 'duplicate'):
            s = g.snapshot(); root = s['state']['hero_power_history'][0]
            if change == 'missing': del root['payloads']
            elif change == 'empty': root['payloads'] = []
            else: root['payloads'].append(dict(root['payloads'][0]))
            with self.subTest(change=change): self.reject(s)

    def test_batch_link_and_iteration_corruption_rejected(self):
        g = self.waiting()
        for key, value in (('id', 2), ('power_id', 99), ('power_id', True),
                           ('outcome_id', 1), ('iteration', 2), ('iteration', True)):
            s = g.snapshot(); s['state']['hero_power_payload_batches'][0][key] = value
            with self.subTest(key=key, value=value): self.reject(s)

    def test_batch_payload_order_and_missing_ability_rejected(self):
        g = self.waiting(multiple=True)
        for change in ('reverse', 'delete', 'duplicate'):
            s = g.snapshot(); payloads = s['state']['hero_power_payload_batches'][0]['payloads']
            if change == 'reverse': payloads.reverse()
            elif change == 'delete': payloads.pop()
            else: payloads[-1] = dict(payloads[0])
            with self.subTest(change=change): self.reject(s)

    def test_capture_root_batch_id_outcome_iteration_corruption_rejected(self):
        g = self.waiting()
        for key, value in (('id', 2), ('batch_id', 2), ('power_id', 2),
                           ('outcome_id', 1), ('iteration', 2)):
            s = g.snapshot(); s['state']['hero_power_payload_history'][0]['capture'][key] = value
            with self.subTest(key=key): self.reject(s)

    def test_capture_ability_must_equal_frozen_batch_member(self):
        g = self.waiting()
        for key, value in (('id', 999), ('behavior_id', 'power'), ('origin', 'granted'), ('consumed', True)):
            s = g.snapshot(); s['state']['hero_power_payload_history'][0]['capture']['ability'][key] = value
            with self.subTest(key=key): self.reject(s)

    def test_missing_batch_capture_or_state_field_rejected(self):
        g = self.waiting(multiple=True)
        for key in ('hero_power_payload_batches', 'hero_power_payload_history'):
            for mode in ('delete', 'empty'):
                s = g.snapshot()
                if mode == 'delete': del s['state'][key]
                else: s['state'][key] = []
                with self.subTest(key=key, mode=mode): self.reject(s)
        s = g.snapshot(); s['state']['hero_power_payload_history'].pop(); self.reject(s)

    def test_status_and_execution_order_corruption_rejected(self):
        g = self.waiting(multiple=True)
        for changes in ({'completed': True}, {'interrupted': True}, {'execution_order': 2},
                        {'execution_order': True}, {'execution_order': None}):
            s = g.snapshot(); s['state']['hero_power_payload_history'][0].update(changes)
            with self.subTest(changes=changes): self.reject(s)
        s = g.snapshot(); s['state']['hero_power_payload_history'][1]['execution_order'] = 1; self.reject(s)

    def test_extra_history_and_batch_fields_rejected(self):
        g = self.waiting()
        for key in ('hero_power_payload_batches', 'hero_power_payload_history'):
            s = g.snapshot(); s['state'][key][0]['unknown'] = 1
            with self.subTest(key=key): self.reject(s)

    def test_completed_record_deletion_and_execution_order_gap_rejected(self):
        g = self.multiple(); self.use(g)
        s = g.snapshot(); s['state']['hero_power_payload_history'].pop(); self.reject(s)
        s = g.snapshot(); s['state']['hero_power_payload_history'][1]['execution_order'] = 99; self.reject(s)

    def test_missing_or_wrong_subject_completion_marker_rejected(self):
        g = self.waiting(); s = g.snapshot()
        markers = self.named(s['resolution_frame'], 'FinishHeroPowerPayload')
        self.assertEqual(len(markers), 1)
        markers[0]['fields']['record_id'] = 999; self.reject(s)
        s = g.snapshot(); queue = s['resolution_frame']['fields']['continuation']['tuple']
        original = len(queue)
        queue[:] = [item for item in queue if not self.named(item, 'FinishHeroPowerPayload')]
        self.assertLess(len(queue), original); self.reject(s)

    def test_duplicate_subject_completion_marker_rejected(self):
        g = self.waiting(); s = g.snapshot()
        markers = self.named(s['resolution_frame'], 'FinishHeroPowerPayload')
        s['resolution_frame']['fields']['continuation']['tuple'].append(markers[0])
        self.reject(s)

    def test_missing_queued_subject_start_rejected(self):
        g = self.waiting(multiple=True); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        self.assertEqual(len(starts), 2)
        queue[:] = [item for item in queue if item is not starts[0]]
        self.assertEqual(len(self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')), 1)
        self.reject(s)

    def test_same_behavior_queued_abilities_cannot_swap_execution_positions(self):
        g = self.waiting(multiple=True); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        a, b = (queue.index(w) for w in starts)
        queue[a], queue[b] = queue[b], queue[a]
        self.reject(s)

    def test_coordinated_queue_record_and_batch_deletion_cannot_shrink_root(self):
        g = self.waiting(multiple=True); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        last = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[-1]
        queue.remove(last)
        s['state']['hero_power_payload_history'].pop()
        s['state']['hero_power_payload_batches'][0]['payloads'].pop()
        self.assertEqual(len(s['state']['hero_power_history'][0]['payloads']), 3)
        self.reject(s)

    def test_coordinated_root_and_context_shrink_cannot_hide_accepted_ability(self):
        g = self.waiting(multiple=True); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        self.assertEqual(len(starts), 2)
        queue.remove(starts[-1])

        def shrink(state):
            state['hero_power_history'][0]['payloads'].pop()
            state['hero_power_payload_batches'][0]['payloads'].pop()
            state['hero_power_payload_history'].pop()

        shrink(s['state'])
        context = starts[0]['fields']['context']['fields']
        captured_state = context['state']['state']
        shrink(captured_state)
        context['power']['fields']['payloads']['tuple'].pop()
        source_id = str(context['source_id'])
        self.assertEqual(len(captured_state['entities'][source_id]['abilities']), 3)
        self.assertEqual(len(captured_state['hero_power_history'][0]['payloads']), 2)
        self.assertEqual(len(self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')), 1)
        s['state_hash'] = canonical_hash({k: v for k, v in s.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'complete accepted ability set'):
            self.restore(s)

    def test_subject_completion_cannot_follow_its_root_completion(self):
        g = self.waiting(); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        marker = self.named(s['resolution_frame'], 'FinishHeroPowerPayload')[0]
        queue.remove(marker); queue.append(marker)
        self.assertLess(queue.index(self.named(s['resolution_frame'], 'FinishHeroPower')[0]), queue.index(marker))
        self.reject(s)

    def test_subject_completion_cannot_follow_its_result_completion(self):
        self.rewind_power('rewait', lambda c: [self.pause(c, GainArmor(1, 1))]); self.retainer()
        g = self.game(power='rewait', hand=(), board=('retainer',)); self.use(g); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        marker = self.named(s['resolution_frame'], 'FinishHeroPowerPayload')[0]
        queue.remove(marker)
        end = self.named(s['resolution_frame'], 'FinishRewindOutcome')[0]
        queue.insert(queue.index(end)+1, marker)
        self.reject(s)

    def test_same_entity_child_context_cannot_borrow_outer_root(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')]
            if c.power.origin == 'manual' else [self.pause(c, GainArmor(1, 1))])
        self.installer(('power',)); g = self.game(power='nested', hand=('install',))
        self.play(g, 'install'); self.use(g); s = g.snapshot()
        starts = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')
        contexts = [w['fields']['context']['fields'] for w in starts]
        child = next(c for c in contexts if c['power']['fields']['id'] == 2)
        outer = next(c for c in contexts if c['power']['fields']['id'] == 1)
        self.assertEqual(child['source_id'], outer['source_id'])
        child['power'] = outer['power']; self.reject(s)

    def test_outer_payload_cannot_finish_before_pending_same_entity_child_root(self):
        self.power('nested', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')]
            if c.power.origin == 'manual' else [self.pause(c, GainArmor(1, 1))])
        g = self.game(power='nested', hand=()); self.use(g); self.check(g); s = g.snapshot()
        queue = s['resolution_frame']['fields']['continuation']['tuple']
        parent = next(w for w in self.named(s['resolution_frame'], 'FinishHeroPowerPayload')
                      if w['fields']['record_id'] == 1)
        queue.remove(parent); queue.insert(0, parent); self.reject(s)

    def test_outer_queued_payload_cannot_start_before_start_reaction_child_root(self):
        self.power('waiting', lambda c: [self.pause(c, GainArmor(1, 1))])
        self.watch('nest', lambda c: [TriggerHeroPower(1, c.source_id, choices='player')], 'hero_power_started')
        g = self.game(power='waiting', board=('nest',), hand=()); self.use(g); self.check(g)
        self.assertEqual([r.execution_order for r in self.rows(g)], [None, 1])
        s = g.snapshot(); queue = s['resolution_frame']['fields']['continuation']['tuple']
        parent = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[0]
        queue.remove(parent); queue.insert(0, parent); self.reject(s)

    def test_raw_behavior_call_cannot_bypass_queued_payload_start(self):
        g = self.waiting(multiple=True); s = g.snapshot()
        context = self.named(s['resolution_frame'], 'InvokeHeroPowerPayload')[0]['fields']['context']
        behavior = context['fields']['power_payload']['fields']['ability']['fields']['behavior_id']
        raw = {'type': 'hs_sim.engine.resolver.BehaviorCall',
               'fields': {'behavior_id': behavior, 'context': context}}
        s['resolution_frame']['fields']['continuation']['tuple'].insert(0, raw)
        self.reject(s)

    def test_completed_retained_result_cannot_hide_next_batch_by_forging_finish(self):
        self.rewind_power('rewait', lambda c: [self.pause(c, GainArmor(1, 1))]); self.retainer()
        g = self.game(power='rewait', hand=(), board=('retainer',)); self.use(g); self.choose(g)
        s = g.snapshot(); self.assertEqual(s['state']['rewind_outcomes'][0]['completed'], 1)
        self.assertEqual(len(s['state']['hero_power_payload_batches']), 2)
        s['state']['hero_power_payload_batches'].pop(); s['state']['hero_power_payload_history'].pop()
        s['state']['rewind_outcomes'][0].update(completed=2, running=False, finished=True)
        self.reject(s)

    def test_recovery_rejects_previous_snapshot_schema(self):
        g = self.waiting(); s = g.snapshot(); self.assertEqual(s['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        s['schema_version'] = 93; self.reject(s)


class PowerPayloadRepresentativeTests(unittest.TestCase):
    def test_native_player_example_restores_and_replays_existing_cards(self):
        from examples.power_payloads import run
        game, snapshot = run()
        self.assertEqual(snapshot['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual([p.origin for p in game.state.hero_power_history], ['effect', 'manual'])
        self.assertEqual(len(game.state.hero_power_payload_history), 2)
        self.assertTrue(all(p.completed for p in game.state.hero_power_payload_history))


if __name__ == '__main__': unittest.main()
