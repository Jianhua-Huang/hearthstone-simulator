"""Dormancy contracts at effect, action, lifecycle and persistence boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (AdvanceDormancy, Attack, AuraSpec, AwakenMinion, CardDefinition,
    CardType, EndTurn, Game, IllegalAction, Keyword, MakeDormant, PlayCard, PlayerSetup,
    ResolutionError, Scenario, SelectChoice, SnapshotError, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, ChoiceOption, CopyMinion, Damage,
    DamageBatch, Destroy, Freeze, GainArmor, GrantKeyword, Heal, RequestChoice, ReturnToHand,
    ShuffleIntoDeck, Silence, Summon, Transform)
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class DormancyTests(unittest.TestCase):
    def setUp(self):
        self.r = build_registry()
        self.card('plain', attack=2, health=5)
        self.spell('wake', lambda c: [AwakenMinion(c.state.players[1].board[0])])
        self.spell('sleep', lambda c: [MakeDormant(c.target_id, 2, c.source_id)], requires_target=True)
        self.spell('kill', lambda c: [Destroy(c.target_id)], requires_target=True)

    def card(self, name, **fields):
        self.r.register_card(CardDefinition(name, name, CardType.MINION, **fields))

    def spell(self, name, callback, **fields):
        self.r.register_behavior(name, callback)
        self.r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, **fields))

    def game(self, board=(), hand=(), enemy=(), enemy_hand=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_01', board=board, hand=hand, deck=('plain',)*10, mana=10, max_mana=10),
            PlayerSetup('HERO_08', board=enemy, hand=enemy_hand, deck=('plain',)*10, mana=10, max_mana=10)), seed=37), self.r)

    def play(self, g, name, target=None):
        p = g.state.active_player
        i = next(i for i in g.state.players[p].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(p, i, target))

    def unit(self, g, pos=0, player=1):
        return g.state.entities[g.state.players[player].board[pos]]

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def check(self, g):
        self.assertEqual(Game.from_snapshot(json.loads(json.dumps(g.snapshot())), self.r).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), self.r).snapshot(), g.snapshot())

    def test_printed_dormancy_only_enters_on_board(self):
        g = self.game(hand=('BT_004',)); i = g.state.players[1].hand[0]
        self.assertIsNone(g.state.entities[i].dormancy)
        self.play(g, 'BT_004')
        self.assertEqual(self.unit(g).dormancy.remaining_turns, 2)
        self.assertEqual(self.unit(g).id, i); self.check(g)

    def test_controller_countdown_and_observer_batch(self):
        g = self.game(board=('BT_004',), enemy=('plain', 'plain'))
        i = self.unit(g).id
        g.apply(EndTurn(1)); self.assertEqual(self.unit(g).dormancy.remaining_turns, 2)
        g.apply(EndTurn(2)); self.assertEqual(self.unit(g).dormancy.remaining_turns, 1)
        self.cycle(g)
        self.assertIsNone(self.unit(g).dormancy)
        self.assertEqual([self.unit(g, n, 2).health for n in (0, 1)], [3, 3])
        self.assertEqual(self.unit(g).id, i); self.check(g)

    def test_one_turn_rush_awakens_and_attacks_minion_only(self):
        g = self.game(board=('TSC_647',), enemy=('plain',))
        self.cycle(g); i = self.unit(g).id
        with self.assertRaises(IllegalAction): g.apply(Attack(1, i, g.state.players[2].hero_id))
        g.apply(Attack(1, i, self.unit(g, player=2).id))
        self.assertEqual(self.unit(g, player=2).health, 1); self.check(g)

    def test_vilefiend_rush_restored_at_awakening(self):
        g = self.game(board=('BT_156',), enemy=('plain',))
        self.assertNotIn(Keyword.RUSH, self.unit(g).keywords)
        self.cycle(g); self.cycle(g)
        self.assertIn(Keyword.RUSH, self.unit(g).keywords)
        g.apply(Attack(1, self.unit(g).id, self.unit(g, player=2).id)); self.check(g)

    def test_ordinary_minion_waits_after_awake(self):
        g = self.game(board=('BT_004',))
        self.cycle(g); self.cycle(g)
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))
        self.cycle(g); g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id))
        self.check(g)

    def test_dormant_cannot_attack_or_be_action_target(self):
        g = self.game(board=('plain',), hand=('CS2_029', 'BT_737'), enemy=('BT_156',))
        target = self.unit(g, player=2).id
        for card in ('CS2_029', 'BT_737'):
            i = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == card)
            self.assertNotIn(target, g.legal_targets(i))
        with self.assertRaises(IllegalAction): g.apply(Attack(1, self.unit(g).id, target))

    def test_ordinary_effects_cannot_touch_dormant_entity(self):
        def effects(c):
            i = c.state.players[1].board[0]
            return [Damage(i, 99), Heal(i, 99), Buff(i, 5, 5), Destroy(i), Silence(i), Freeze(i),
                    GrantKeyword(i, Keyword.REBORN), ReturnToHand(i), Transform(i, 'plain'),
                    CopyMinion(i, 2), ChangeControl(i, 2), ShuffleIntoDeck(i)]
        self.spell('touch', effects)
        g = self.game(board=('BT_156',), hand=('touch',)); before = self.unit(g)
        self.play(g, 'touch'); self.assertEqual(self.unit(g), before); self.check(g)

    def test_dormant_occupies_slot_and_summon_fails(self):
        self.spell('summon', lambda c: [Summon(1, 'plain')])
        g = self.game(board=('BT_004',)*7, hand=('summon', 'plain'))
        self.play(g, 'summon'); self.assertEqual(len(g.state.players[1].board), 7)
        with self.assertRaises(IllegalAction): self.play(g, 'plain')

    def test_maiev_preserves_entity_damage_and_enchantments(self):
        self.spell('buff', lambda c: [Buff(c.target_id, 3, 2), Damage(c.target_id, 2)], requires_target=True)
        g = self.game(board=('plain',), hand=('buff', 'BT_737', 'wake'))
        i = self.unit(g).id; self.play(g, 'buff', i); before = self.unit(g)
        self.play(g, 'BT_737', i); self.play(g, 'wake')
        after = self.unit(g)
        self.assertEqual((after.id, after.attack, after.health, after.enchantments),
                         (before.id, before.attack, before.health, before.enchantments)); self.check(g)

    def test_maiev_can_be_played_without_available_target(self):
        g = self.game(hand=('BT_737',)); self.play(g, 'BT_737')
        self.assertIsNone(self.unit(g).dormancy); self.check(g)

    def test_awaken_callback_repeats_after_maiev(self):
        g = self.game(board=('BT_004',), hand=('wake', 'BT_737', 'wake'), enemy=('plain',))
        self.play(g, 'wake'); self.play(g, 'BT_737', self.unit(g).id); self.play(g, 'wake')
        self.assertEqual(self.unit(g, player=2).health, 1); self.check(g)

    def test_awakening_is_not_new_summon_or_battlecry(self):
        self.r.register_behavior('armor', lambda c: [GainArmor(1, 1)])
        self.card('sleeper', attack=1, health=3, dormant_turns=1, on_play='armor', on_awaken='armor')
        g = self.game(hand=('sleeper',)); self.play(g, 'sleeper'); self.cycle(g)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual(sum(e.kind == 'minion_summoned' for e in g.events), 1)
        self.assertEqual(sum(e.kind == 'card_played' for e in g.events), 1); self.check(g)

    def test_dormant_disables_aura_and_wake_restores_it(self):
        self.card('aura', attack=1, health=5, auras=(AuraSpec(2, health=2),))
        g = self.game(board=('aura', 'plain'), hand=('sleep', 'wake'))
        self.assertEqual((self.unit(g, 1).attack, self.unit(g, 1).health), (4, 7))
        self.play(g, 'sleep', self.unit(g).id)
        self.assertEqual((self.unit(g, 1).attack, self.unit(g, 1).health), (2, 5))
        self.play(g, 'wake'); self.assertEqual(self.unit(g, 1).attack, 4); self.check(g)

    def test_dormant_target_receives_no_external_aura(self):
        self.card('aura', attack=1, health=5, auras=(AuraSpec(2, health=2),))
        g = self.game(board=('BT_004', 'aura'), hand=('wake',))
        self.assertEqual(self.unit(g).attack, 4)
        self.play(g, 'wake'); self.assertEqual(self.unit(g).attack, 6); self.check(g)

    def test_only_dormant_specific_trigger_runs_while_dormant(self):
        self.r.register_behavior('one', lambda c: [GainArmor(1, 1)])
        self.r.register_behavior('ten', lambda c: [GainArmor(1, 10)])
        self.card('sleeper', attack=1, health=3, dormant_turns=None,
            triggers=(TriggerSpec('card_played', 'one'),),
            dormant_triggers=(TriggerSpec('card_played', 'ten'),))
        g = self.game(board=('sleeper',), hand=('GAME_005', 'wake'))
        self.play(g, 'GAME_005'); self.play(g, 'wake')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 11); self.check(g)

    def test_indefinite_dormancy_requires_explicit_awaken(self):
        self.card('forever', attack=1, health=3, dormant_turns=None)
        self.spell('advance', lambda c: [AdvanceDormancy(c.state.players[1].board[0], 99)])
        g = self.game(board=('forever',), hand=('advance', 'wake'))
        self.cycle(g); self.play(g, 'advance'); self.assertIsNone(self.unit(g).dormancy.remaining_turns)
        self.play(g, 'wake'); self.assertIsNone(self.unit(g).dormancy); self.check(g)

    def test_advance_countdown_and_overshoot_awake(self):
        self.spell('advance', lambda c: [AdvanceDormancy(c.state.players[1].board[0])])
        self.spell('finish', lambda c: [AdvanceDormancy(c.state.players[1].board[0], 20)])
        g = self.game(board=('BT_004',), hand=('advance', 'finish'))
        self.play(g, 'advance'); self.assertEqual(self.unit(g).dormancy.remaining_turns, 1)
        self.play(g, 'finish'); self.assertIsNone(self.unit(g).dormancy); self.check(g)

    def test_turn_start_new_dormancy_waits_until_next_turn(self):
        self.r.register_behavior('sleep_first', lambda c: [MakeDormant(c.source_id, 1)]
            if c.event.player_id == c.player_id else [])
        self.card('watch', attack=1, health=3, triggers=(TriggerSpec('turn_started', 'sleep_first'),))
        g = self.game(board=('watch',)); self.cycle(g)
        self.assertEqual(self.unit(g).dormancy.remaining_turns, 1)
        self.cycle(g); self.assertIsNone(self.unit(g).dormancy); self.check(g)

    def test_old_countdown_cannot_tick_replaced_dormancy_instance(self):
        self.r.register_behavior('reset', lambda c: [AwakenMinion(c.source_id), MakeDormant(c.source_id, 2)]
            if c.event.player_id == c.player_id else [])
        self.card('sleeper', attack=1, health=3, dormant_turns=1,
            dormant_triggers=(TriggerSpec('turn_started', 'reset'),))
        g = self.game(board=('sleeper',)); old = self.unit(g).dormancy.id
        self.cycle(g); self.assertEqual(self.unit(g).dormancy.remaining_turns, 2)
        self.assertNotEqual(self.unit(g).dormancy.id, old); self.check(g)

    def test_reborn_printed_dormant_returns_as_new_entity_with_one_health(self):
        self.spell('reborn', lambda c: [GrantKeyword(c.target_id, Keyword.REBORN)], requires_target=True)
        g = self.game(board=('BT_004',), hand=('wake', 'reborn', 'kill'))
        self.play(g, 'wake'); old = self.unit(g).id
        self.play(g, 'reborn', old); self.play(g, 'kill', old)
        self.assertNotEqual(self.unit(g).id, old)
        self.assertEqual((self.unit(g).health, self.unit(g).dormancy.remaining_turns), (1, 2))
        self.cycle(g); self.cycle(g); self.assertEqual(self.unit(g).health, 1)
        self.assertNotIn(Keyword.REBORN, self.unit(g).keywords); self.check(g)

    def test_copy_current_awake_and_base_printed_dormancy(self):
        self.spell('copies', lambda c: [CopyMinion(c.target_id, 1, mode='current'),
                                      CopyMinion(c.target_id, 1, mode='base')], requires_target=True)
        g = self.game(board=('BT_004',), hand=('wake', 'copies'))
        self.play(g, 'wake'); self.play(g, 'copies', self.unit(g).id)
        self.assertIsNone(self.unit(g, 1).dormancy)
        self.assertEqual(self.unit(g, 2).dormancy.remaining_turns, 2); self.check(g)

    def test_transform_to_printed_dormant_initializes_lifecycle(self):
        self.spell('transform', lambda c: [Transform(c.target_id, 'BT_004')], requires_target=True)
        g = self.game(board=('plain',), hand=('transform',)); old = self.unit(g).id
        self.play(g, 'transform', old)
        self.assertEqual((self.unit(g).id, self.unit(g).dormancy.remaining_turns), (old, 2)); self.check(g)

    def test_return_and_replay_restarts_printed_dormancy(self):
        self.spell('back', lambda c: [ReturnToHand(c.target_id)], requires_target=True)
        g = self.game(board=('BT_004',), hand=('wake', 'back'))
        self.play(g, 'wake'); i = self.unit(g).id; self.play(g, 'back', i)
        self.assertIsNone(g.state.entities[i].dormancy)
        self.play(g, 'BT_004'); self.assertEqual(self.unit(g).dormancy.remaining_turns, 2); self.check(g)

    def test_silenced_awake_does_not_regain_callback_after_dormancy(self):
        self.spell('silence', lambda c: [Silence(c.target_id)], requires_target=True)
        g = self.game(board=('BT_004',), hand=('wake', 'silence', 'sleep', 'wake'), enemy=('plain',))
        self.play(g, 'wake'); i = self.unit(g).id
        self.play(g, 'silence', i); self.play(g, 'sleep', i); self.play(g, 'wake')
        self.assertEqual(self.unit(g, player=2).health, 3); self.check(g)

    def test_temporary_attachment_expires_while_dormant(self):
        self.spell('temp', lambda c: [Buff(c.target_id, attack=4, expires_turn=c.state.turn),
                                     MakeDormant(c.target_id, 1)], requires_target=True)
        g = self.game(board=('plain',), hand=('temp',))
        self.play(g, 'temp', self.unit(g).id); self.cycle(g)
        self.assertEqual(self.unit(g).attack, 2); self.check(g)

    def test_awaken_choice_suspends_turn_before_draw_and_restores(self):
        self.r.register_behavior('choice', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('yes', 'Yes', effects=(GainArmor(1, 2),)),), source_id=c.source_id)])
        self.card('sleeper', attack=1, health=3, dormant_turns=1, on_awaken='choice')
        g = self.game(board=('sleeper',)); self.cycle(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(g.state.players[1].hand), 0); self.check(g)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        action = SelectChoice(1, g.state.pending_choice.id, ('yes',))
        g.apply(action); restored.apply(action)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(len(g.state.players[1].hand), 1); self.check(g)

    def test_failed_awaken_callback_rolls_back_turn_and_countdown(self):
        self.r.register_behavior('bad', lambda c: [Summon(1, 'missing')])
        self.card('sleeper', attack=1, health=3, dormant_turns=1, on_awaken='bad')
        g = self.game(board=('sleeper',)); g.apply(EndTurn(1)); before = g.snapshot()
        with self.assertRaises(ResolutionError): g.apply(EndTurn(2))
        self.assertEqual(g.snapshot(), before)

    def test_dormancy_projection_has_no_internal_instance_id(self):
        g = self.game(board=('BT_004',))
        for viewer in (1, 2):
            row = g.observe(viewer)['players'][0]['board'][0]
            self.assertEqual(row['dormancy'], {'remaining_turns': 2})
        self.check(g)

    def test_corrupt_dormancy_snapshots_are_rejected_even_with_new_hash(self):
        g = self.game(board=('BT_004', 'BT_156')); i = str(self.unit(g).id)
        for value in ({'id': 1, 'remaining_turns': 0, 'started_turn': 1},
                      {'id': 1, 'remaining_turns': True, 'started_turn': 1},
                      {'id': 1, 'remaining_turns': 2, 'started_turn': 99},
                      {'id': self.unit(g, 1).dormancy.id, 'remaining_turns': 2, 'started_turn': 1},
                      {'id': 999999, 'remaining_turns': 2, 'started_turn': 1}, {}):
            with self.subTest(value=value):
                row = deepcopy(g.snapshot()); row['state']['entities'][i]['dormancy'] = value
                row['state_hash'] = canonical_hash({k: v for k, v in row.items()
                    if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
                with self.assertRaises(SnapshotError): Game.from_snapshot(row, self.r)

    def test_invalid_definitions_and_effects_are_rejected(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.r.register_card(CardDefinition('invalid', 'Invalid', CardType.MINION, health=1, dormant_turns=value))
        with self.assertRaises(ValueError):
            self.r.register_card(CardDefinition('invalid', 'Invalid', CardType.SPELL, dormant_turns=1))
        for constructor in (lambda: MakeDormant(1, 0), lambda: AdvanceDormancy(1, True),
                            lambda: AwakenMinion(False)):
            with self.assertRaises(ValueError): constructor()

    def test_full_board_awake_needs_no_new_slot(self):
        g = self.game(board=('BT_004',)*7)
        self.cycle(g); self.cycle(g)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertTrue(all(g.state.entities[i].active for i in g.state.players[1].board)); self.check(g)

    def test_batched_damage_skips_dormant_without_hiding_other_targets(self):
        self.spell('aoe', lambda c: [DamageBatch(tuple(Damage(i, 9) for i in c.state.players[2].board))])
        g = self.game(enemy=('BT_156', 'plain'), hand=('aoe',))
        self.play(g, 'aoe')
        self.assertEqual(len(g.state.players[2].board), 1)
        self.assertEqual(self.unit(g, player=2).health, 5); self.check(g)

    def test_asleep_taunt_does_not_protect_hero(self):
        self.card('taunt', attack=1, health=3, dormant_turns=2, keywords=(Keyword.TAUNT,))
        g = self.game(board=('plain',), enemy=('taunt',))
        g.apply(Attack(1, self.unit(g).id, g.state.players[2].hero_id)); self.check(g)

    def test_dormant_spell_damage_is_inactive_then_restored(self):
        self.card('power', attack=1, health=3, dormant_turns=None, spell_damage=2)
        g = self.game(board=('power',), hand=('CS2_029', 'wake', 'CS2_029'))
        hero = g.state.players[2].hero_id
        self.play(g, 'CS2_029', hero); self.assertEqual(g.state.entities[hero].health, 24)
        self.play(g, 'wake'); self.play(g, 'CS2_029', hero)
        self.assertEqual(g.state.entities[hero].health, 16); self.check(g)

    def test_multiple_countdowns_resume_after_first_awaken_choice(self):
        self.r.register_behavior('choice2', lambda c: [RequestChoice(c.player_id,
            (ChoiceOption('yes', 'Yes'),), source_id=c.source_id)])
        self.card('sleeper', attack=1, health=3, dormant_turns=1, on_awaken='choice2')
        g = self.game(board=('sleeper', 'TSC_647')); self.cycle(g)
        self.assertEqual(self.unit(g, 1).dormancy.remaining_turns, 1)
        restored = Game.from_snapshot(g.snapshot(), self.r)
        action = SelectChoice(1, g.state.pending_choice.id, ('yes',))
        g.apply(action); restored.apply(action)
        self.assertIsNone(self.unit(g, 1).dormancy)
        self.assertEqual(g.snapshot(), restored.snapshot()); self.check(g)

    def test_failed_make_dormant_source_rolls_back(self):
        self.spell('badsource', lambda c: [MakeDormant(c.state.players[1].board[0], 2, 999999)])
        g = self.game(board=('plain',), hand=('badsource',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'badsource')
        self.assertEqual(g.snapshot(), before)

    def test_repeated_sleep_or_wake_is_stale_without_extra_callback(self):
        self.spell('repeat', lambda c: [MakeDormant(c.state.players[1].board[0], 9),
            AwakenMinion(c.state.players[1].board[0]), AwakenMinion(c.state.players[1].board[0])])
        g = self.game(board=('BT_004',), hand=('repeat',), enemy=('plain',))
        self.play(g, 'repeat'); self.assertEqual(self.unit(g, player=2).health, 3)
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in g.events), 1); self.check(g)

    def test_real_example_uses_player_commands_restore_and_replay(self):
        from examples.awaken_minions import run
        g, snapshot = run()
        self.assertEqual(snapshot['schema_version'], 265)
        self.assertEqual(sum(e.kind == 'minion_awakened' for e in g.events), 3)


if __name__ == '__main__':
    unittest.main()
