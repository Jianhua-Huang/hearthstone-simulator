"""Ordered stat operations and their lifecycle contracts, not official calibration."""
from dataclasses import replace
import unittest

from hs_sim.engine import (AuraSpec, CardDefinition, CardType, Enchantment, EndTurn, Game,
                          Keyword, PlayCard, PlayerSetup, Registry, Scenario, SnapshotError,
                          StatReference, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, CopyMinion, Damage, Destroy,
                                  DoubleStats, Heal, RandomDamage, RemoveEnchantment,
                                  ReturnToHand, SetStats, ShuffleIntoDeck, Silence,
                                  SwapStats, Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import state_from_dict


class StatTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('stat-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        for name, attack, health, keywords in (
            ('big', 4, 7, ()), ('zero', 0, 3, ()), ('small', 1, 2, ()),
            ('reborn', 2, 3, (Keyword.REBORN,)),
        ):
            self.registry.register_card(CardDefinition(name, name, CardType.MINION,
                                                       attack=attack, health=health, keywords=keywords))
        self.registry.register_card(CardDefinition('aura', 'aura', CardType.MINION,
                                                   attack=1, health=4, auras=(AuraSpec(1, health=2),)))
        self.spell('buff', lambda c: [Buff(c.target_id, 3, 2, c.source_id)])
        self.spell('set', lambda c: [SetStats(c.target_id, attack=1, health=5, source_id=c.source_id)])
        self.spell('attack', lambda c: [SetStats(c.target_id, attack=1)])
        self.spell('inner', lambda c: [SetStats(c.target_id, attack=StatReference.HEALTH)])
        self.spell('swap', lambda c: [SwapStats(c.target_id, c.source_id)])
        self.spell('double', lambda c: [DoubleStats(c.target_id, health=True, source_id=c.source_id)])
        self.spell('hurt', lambda c: [Damage(c.target_id, 3)])
        self.spell('heal', lambda c: [Heal(c.target_id, 99)])
        self.spell('silence', lambda c: [Silence(c.target_id)])
        self.spell('kill', lambda c: [Destroy(c.target_id)])

    def spell(self, name, fn):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL,
                                                   on_play=name, requires_target=True))

    def game(self, hand=(), board=('big',), enemy_board=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('small',)*10, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy_board, deck=('small',)*10, mana=10, max_mana=10),
        ), seed=71), self.registry)

    def cast(self, game, name, target):
        state = game.state
        card = next(i for i in state.players[1].hand if state.entities[i].card_id == name)
        return game.apply(PlayCard(1, card, target))

    def target(self, game):
        return game.state.players[1].board[-1]

    def assert_stats(self, game, target, attack, health, maximum=None):
        entity = game.state.entities[target]
        self.assertEqual((entity.attack, entity.health, entity.max_health),
                         (attack, health, health if maximum is None else maximum))

    def test_add_set_add_preserves_acquisition_order(self):
        game = self.game(hand=('buff', 'set', 'buff'))
        target = self.target(game)
        for spell in ('buff', 'set', 'buff'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 4, 7)
        self.assertEqual(len(game.state.entities[target].enchantments), 3)

    def test_setting_one_stat_leaves_other_stat_and_damage_unchanged(self):
        game = self.game(hand=('hurt', 'attack'))
        target = self.target(game)
        self.cast(game, 'hurt', target)
        self.cast(game, 'attack', target)
        self.assert_stats(game, target, 1, 4, 7)

    def test_setting_health_clears_damage_without_healed_or_damage_events(self):
        game = self.game(hand=('hurt', 'set'))
        target = self.target(game)
        self.cast(game, 'hurt', target)
        result = self.cast(game, 'set', target)
        self.assert_stats(game, target, 1, 5)
        self.assertFalse(any(e.kind in ('healed', 'damage_dealt', 'lifesteal') for e in result.events))

    def test_inner_fire_reads_remaining_health_and_does_not_track_later_damage(self):
        game = self.game(hand=('hurt', 'inner', 'heal'))
        target = self.target(game)
        self.cast(game, 'hurt', target)
        self.cast(game, 'inner', target)
        self.assert_stats(game, target, 4, 4, 7)
        self.cast(game, 'heal', target)
        self.assert_stats(game, target, 4, 7)

    def test_references_are_read_at_execution_after_prior_effects(self):
        self.spell('chain', lambda c: [Damage(c.target_id, 3),
                                       SetStats(c.target_id, attack=StatReference.HEALTH)])
        game = self.game(hand=('chain',))
        target = self.target(game)
        self.cast(game, 'chain', target)
        self.assert_stats(game, target, 4, 4, 7)

    def test_max_health_reference_differs_from_remaining_health(self):
        self.spell('maximum', lambda c: [SetStats(c.target_id, attack=StatReference.MAX_HEALTH)])
        game = self.game(hand=('hurt', 'maximum'))
        target = self.target(game)
        self.cast(game, 'hurt', target)
        self.cast(game, 'maximum', target)
        self.assert_stats(game, target, 7, 4, 7)

    def test_swap_reads_both_values_before_writing(self):
        game = self.game(hand=('buff', 'hurt', 'swap'))
        target = self.target(game)
        for spell in ('buff', 'hurt', 'swap'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 6, 7)

    def test_zero_attack_swap_kills_and_preserves_set_in_death_history(self):
        game = self.game(hand=('swap',), board=('zero',))
        target = self.target(game)
        self.cast(game, 'swap', target)
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        record = game.state.death_history[0]
        self.assertEqual((record.attack, record.max_health, record.damage), (3, 0, 0))
        self.assertEqual(record.enchantments[-1].set_health, 0)

    def test_zero_health_set_on_hero_ends_game(self):
        self.spell('zero_health', lambda c: [SetStats(c.target_id, health=0)])
        game = self.game(hand=('zero_health',))
        self.cast(game, 'zero_health', game.state.players[2].hero_id)
        self.assertEqual((game.state.status, game.state.winner), ('finished', 1))

    def test_double_injured_health_adds_remaining_health_to_maximum(self):
        game = self.game(hand=('hurt', 'double', 'heal'))
        target = self.target(game)
        self.cast(game, 'hurt', target)
        self.cast(game, 'double', target)
        self.assert_stats(game, target, 4, 8, 11)
        self.cast(game, 'heal', target)
        self.assert_stats(game, target, 4, 11)

    def test_double_both_stats_is_one_attachment_with_frozen_operands(self):
        self.spell('both', lambda c: [DoubleStats(c.target_id, attack=True, health=True)])
        game = self.game(hand=('both', 'double'))
        target = self.target(game)
        self.cast(game, 'both', target)
        self.assert_stats(game, target, 8, 14)
        self.cast(game, 'double', target)
        self.assert_stats(game, target, 8, 28)
        self.assertEqual(len(game.state.entities[target].enchantments), 2)
        self.assertEqual(Game.from_snapshot(game.snapshot(), self.registry).snapshot(), game.snapshot())

    def test_set_then_double_then_set_discards_prior_modifiers_for_that_stat(self):
        game = self.game(hand=('set', 'double', 'set'))
        target = self.target(game)
        for spell in ('set', 'double', 'set'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 1, 5)

    def test_auras_apply_after_local_set_and_can_be_removed(self):
        game = self.game(hand=('set', 'kill'), board=('aura', 'big'))
        aura, target = game.state.players[1].board
        self.cast(game, 'set', target)
        self.assert_stats(game, target, 2, 7)
        self.cast(game, 'kill', aura)
        self.assert_stats(game, target, 1, 5)

    def test_inner_fire_reads_visible_health_before_attack_aura_reapplication(self):
        game = self.game(hand=('inner', 'kill'), board=('aura', 'big'))
        aura, target = game.state.players[1].board
        self.cast(game, 'inner', target)
        self.assert_stats(game, target, 10, 9)
        self.cast(game, 'kill', aura)
        self.assert_stats(game, target, 9, 7)

    def test_double_freezes_current_aura_in_operand_only_once(self):
        game = self.game(hand=('double', 'kill'), board=('aura', 'big'))
        aura, target = game.state.players[1].board
        self.cast(game, 'double', target)
        self.assert_stats(game, target, 5, 18)
        self.cast(game, 'kill', aura)
        self.assert_stats(game, target, 4, 16)

    def test_swap_reapplies_both_auras_after_simultaneous_read(self):
        game = self.game(hand=('swap',), board=('aura', 'big'))
        target = self.target(game)
        self.cast(game, 'swap', target)
        self.assert_stats(game, target, 10, 7)

    def test_temporary_set_expires_and_reveals_earlier_additions(self):
        self.spell('temporary', lambda c: [SetStats(c.target_id, attack=1, health=2,
                                                  expires_turn=c.state.turn)])
        game = self.game(hand=('buff', 'temporary', 'buff'))
        target = self.target(game)
        for spell in ('buff', 'temporary', 'buff'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 4, 4)
        game.apply(EndTurn(1))
        self.assert_stats(game, target, 10, 11)

    def test_expired_earlier_add_does_not_change_later_set(self):
        self.spell('temporary', lambda c: [Buff(c.target_id, 5, 5, expires_turn=c.state.turn)])
        game = self.game(hand=('temporary', 'set'))
        target = self.target(game)
        self.cast(game, 'temporary', target)
        self.cast(game, 'set', target)
        game.apply(EndTurn(1))
        self.assert_stats(game, target, 1, 5)

    def test_temporary_health_set_expiry_does_not_restore_old_damage(self):
        self.spell('low', lambda c: [SetStats(c.target_id, health=5, expires_turn=c.state.turn)])
        self.spell('high', lambda c: [SetStats(c.target_id, health=10, expires_turn=c.state.turn)])
        for name, expected in (('low', 4), ('high', 7)):
            with self.subTest(name=name):
                game = self.game(hand=('hurt', name, 'hurt'))
                target = self.target(game)
                for spell in ('hurt', name, 'hurt'):
                    self.cast(game, spell, target)
                game.apply(EndTurn(1))
                self.assert_stats(game, target, 4, expected, 7)

    def test_temporary_double_health_removal_clamps_remaining_health(self):
        self.spell('temporary', lambda c: [DoubleStats(c.target_id, health=True, expires_turn=c.state.turn)])
        game = self.game(hand=('hurt', 'temporary', 'hurt'))
        target = self.target(game)
        for spell in ('hurt', 'temporary', 'hurt'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 4, 5, 11)
        game.apply(EndTurn(1))
        self.assert_stats(game, target, 4, 5, 7)

    def test_remove_specific_set_reveals_original_chain(self):
        self.spell('remove', lambda c: [RemoveEnchantment(c.target_id, c.state.entities[c.target_id].enchantments[1].id)])
        game = self.game(hand=('buff', 'set', 'buff', 'remove'))
        target = self.target(game)
        for spell in ('buff', 'set', 'buff', 'remove'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 10, 11)

    def test_silence_removes_set_double_but_keeps_external_aura(self):
        game = self.game(hand=('set', 'double', 'silence'), board=('aura', 'big'))
        target = self.target(game)
        for spell in ('set', 'double', 'silence'):
            self.cast(game, spell, target)
        self.assert_stats(game, target, 5, 9)
        self.assertFalse(game.state.entities[target].enchantments)

    def test_current_copy_preserves_order_damage_and_new_attachment_identity(self):
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1)])
        game = self.game(hand=('set', 'buff', 'hurt', 'copy'))
        target = self.target(game)
        for spell in ('set', 'buff', 'hurt', 'copy'):
            self.cast(game, spell, target)
        copied = self.target(game)
        self.assertNotEqual(copied, target)
        self.assert_stats(game, copied, 4, 4, 7)
        old = game.state.entities[target].enchantments
        new = game.state.entities[copied].enchantments
        self.assertEqual([replace(e, id=1) for e in old], [replace(e, id=1) for e in new])
        self.assertTrue(set(e.id for e in old).isdisjoint(e.id for e in new))

    def test_base_copy_ignores_set_and_double(self):
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1, mode='base')])
        game = self.game(hand=('set', 'double', 'copy'))
        target = self.target(game)
        for spell in ('set', 'double', 'copy'):
            self.cast(game, spell, target)
        self.assert_stats(game, self.target(game), 4, 7)

    def test_resetting_lifecycle_discards_operations(self):
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)])
        self.spell('shuffle', lambda c: [ShuffleIntoDeck(c.target_id)])
        self.spell('transform', lambda c: [Transform(c.target_id, 'small')])
        for operation, attack, health in (('bounce', 4, 7), ('shuffle', 4, 7), ('transform', 1, 2)):
            with self.subTest(operation=operation):
                game = self.game(hand=('set', operation))
                target = self.target(game)
                self.cast(game, 'set', target)
                self.cast(game, operation, target)
                self.assert_stats(game, target, attack, health)
                self.assertFalse(game.state.entities[target].enchantments)

    def test_control_transfer_preserves_operations_and_recomputes_auras(self):
        self.spell('give', lambda c: [ChangeControl(c.target_id, 2)])
        game = self.game(hand=('set', 'give'), enemy_board=('aura',))
        target = self.target(game)
        self.cast(game, 'set', target)
        self.cast(game, 'give', target)
        self.assert_stats(game, target, 2, 7)

    def test_reborn_does_not_copy_stat_sets(self):
        game = self.game(hand=('set', 'kill'), board=('reborn',))
        old = self.target(game)
        self.cast(game, 'set', old)
        self.cast(game, 'kill', old)
        new = self.target(game)
        self.assertNotEqual(new, old)
        self.assert_stats(game, new, 2, 1, 3)
        self.assertFalse(game.state.entities[new].enchantments)

    def test_stale_target_is_skipped_without_new_attachment(self):
        self.spell('late', lambda c: [Destroy(c.target_id), SwapStats(c.target_id), DoubleStats(c.target_id, health=True)])
        game = self.game(hand=('late',))
        result = self.cast(game, 'late', self.target(game))
        self.assertEqual(sum(e.kind == 'effect_skipped' for e in result.events), 2)

    def test_failure_after_random_damage_and_set_rolls_back_entire_transaction(self):
        self.spell('bad', lambda c: [RandomDamage(tuple(c.state.players[1].board), 1),
                                    SwapStats(c.target_id), SetStats(c.target_id, attack=3, source_id=999999)])
        game = self.game(hand=('bad',), board=('big', 'big'))
        before, history = game.snapshot(), game.history
        with self.assertRaises(ResolutionError):
            self.cast(game, 'bad', self.target(game))
        self.assertEqual((game.snapshot(), game.history), (before, history))

    def test_invalid_effect_operands_and_ambiguous_attachment_rejected(self):
        makers = (lambda: SetStats(1), lambda: SetStats(1, attack=True), lambda: SetStats(1, health=-1),
                  lambda: SetStats(1, attack='health'), lambda: DoubleStats(1),
                  lambda: DoubleStats(1, health=1), lambda: SwapStats(0),
                  lambda: Enchantment(1, attack=2, set_attack=3), lambda: Enchantment(1, set_health=True),
                  lambda: Enchantment(1, set_attack=StatReference.HEALTH))
        for maker in makers:
            with self.subTest(maker=maker), self.assertRaises(ValueError):
                maker()

    def test_double_dispatches_buff_through_custom_mechanics(self):
        mechanics = default_mechanics('stat-custom-buff-v1')
        mechanics.replace(Buff, lambda r, effect: [])
        game = Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=('double',), board=('big',)), PlayerSetup('hero'),
        )), self.registry, mechanics=mechanics)
        target = self.target(game)
        self.cast(game, 'double', target)
        self.assert_stats(game, target, 4, 7)
        self.assertFalse(game.state.entities[target].enchantments)

    def test_snapshot_rejects_stale_cache_malformed_operand_and_reordered_attachments(self):
        game = self.game(hand=('buff', 'set'))
        target = self.target(game)
        for spell in ('buff', 'set'):
            self.cast(game, spell, target)
        for mode in ('cache', 'operand', 'order', 'missing'):
            snapshot = game.snapshot()
            entity = snapshot['state']['entities'][str(target)]
            if mode == 'cache':
                entity['attack_bonus'] += 1
            elif mode == 'operand':
                entity['enchantments'][-1]['set_attack'] = True
            elif mode == 'order':
                entity['enchantments'].reverse()
            else:
                del entity['enchantments'][-1]['set_health']
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)
        # Decoder also rejects new fields with wrong types independently of hashes.
        state = game.snapshot()['state']
        state['entities'][str(target)]['enchantments'][-1]['set_health'] = []
        with self.assertRaises(ValueError):
            state_from_dict(state)

    def test_clone_snapshot_replay_preserve_order_and_never_repeat_doubling(self):
        game = self.game(hand=('hurt', 'double', 'inner', 'swap'))
        target = self.target(game)
        for spell in ('hurt', 'double', 'inner'):
            self.cast(game, spell, target)
        restored = Game.from_snapshot(game.snapshot(), self.registry)
        clone = game.clone()
        for branch in (game, restored, clone):
            self.cast(branch, 'swap', target)
            self.assert_stats(branch, target, 8, 8)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(game.snapshot(), clone.snapshot())
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())
        for version in (1, 2, 3, 4):
            snapshot = game.snapshot()
            snapshot['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
