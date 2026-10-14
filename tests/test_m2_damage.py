"""Public-action tests for classified damage and additive spell damage."""
from copy import deepcopy
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, DamageKind, EndTurn,
                          Game, Keyword, PlayCard, PlayerSetup, Registry, Scenario,
                          SnapshotError, Zone)
from hs_sim.engine.effects import (ChangeControl, CopyMinion, Damage, DamageBatch,
                                  GrantSpellDamage, Heal, RandomDamage, ReturnToHand, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay


class DamageTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('m2-damage-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.registry.register_card(CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=10))
        self.registry.register_card(CardDefinition('power', 'power', CardType.MINION, attack=1, health=1, spell_damage=1))
        self.registry.register_card(CardDefinition('power2', 'power2', CardType.MINION, health=3, spell_damage=2))
        self.registry.register_card(CardDefinition('shield', 'shield', CardType.MINION, health=3,
                                                   keywords=(Keyword.DIVINE_SHIELD,)))
        self.registry.register_card(CardDefinition('immune', 'immune', CardType.MINION, health=3,
                                                   keywords=(Keyword.IMMUNE, Keyword.DIVINE_SHIELD)))
        self.spell('spell', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL)], True)
        self.spell('effect', lambda c: [Damage(c.target_id, 2, c.source_id)], True)
        self.spell('silence', lambda c: [Silence(c.target_id)], True)

    def spell(self, name, behavior, target=False):
        self.registry.register_behavior(name, behavior)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=target))

    def game(self, hand=(), board=(), enemy_board=(), enemy_armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy_board, armor=enemy_armor, mana=10, max_mana=10),
        ), seed=27), self.registry)

    def cast(self, game, card_id, target=None):
        entity_id = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card_id)
        return game.apply(PlayCard(1, entity_id, target))

    def enemy(self, game):
        return game.state.players[2].hero_id

    def damages(self, result):
        return [event for event in result.events if event.kind == 'damage_dealt']

    def test_spell_damage_stacks_for_source_controller_only(self):
        game = self.game(hand=('spell',), board=('power', 'power2'), enemy_board=('power2',))
        event = self.damages(self.cast(game, 'spell', self.enemy(game)))[0]
        self.assertEqual(event.amount, 5)
        self.assertEqual(dict(event.data), dict(damage_kind='spell', base_amount=2, spell_bonus=3,
                                              modified_amount=5, health_damage=5, armor_absorbed=0, source_controller=1,
                                              original_target_id=self.enemy(game), rule_ids=(), redirect_path=(),
                                              converted=False, spell_school=None, floor_prevented=0))

    def test_hand_and_dead_spell_damage_sources_do_not_contribute(self):
        game = self.game(hand=('power2', 'effect', 'spell'), board=('power',))
        source = game.state.players[1].board[0]
        self.cast(game, 'effect', source)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 2)

    def test_effect_damage_is_not_inferred_from_a_spell_source(self):
        game = self.game(hand=('effect',), board=('power2',))
        event = self.damages(self.cast(game, 'effect', self.enemy(game)))[0]
        self.assertEqual(event.amount, 2)
        self.assertEqual(dict(event.data)['damage_kind'], 'effect')

    def test_simultaneous_batch_freezes_bonus_before_its_provider_dies(self):
        def batch(c):
            provider = c.state.players[1].board[0]
            return [DamageBatch((Damage(provider, 2, c.source_id, DamageKind.SPELL),
                                 Damage(c.state.players[2].hero_id, 2, c.source_id, DamageKind.SPELL)))]
        self.spell('batch', batch)
        game = self.game(hand=('batch',), board=('power',))
        result = self.cast(game, 'batch')
        self.assertEqual([e.amount for e in self.damages(result)], [3, 3])
        self.assertEqual(game.state.players[1].board, [])

    def test_separate_damage_effects_recompute_after_provider_dies(self):
        self.spell('sequential', lambda c: [
            Damage(c.state.players[1].board[0], 2, c.source_id, DamageKind.SPELL),
            Damage(c.state.players[2].hero_id, 2, c.source_id, DamageKind.SPELL)])
        game = self.game(hand=('sequential',), board=('power',))
        result = self.cast(game, 'sequential')
        self.assertEqual([e.amount for e in self.damages(result)], [3, 2])

    def test_silence_removes_printed_and_granted_spell_damage(self):
        self.spell('grant', lambda c: [GrantSpellDamage(c.target_id, 2, c.source_id)], True)
        game = self.game(hand=('grant', 'silence', 'spell'), board=('power',))
        source = game.state.players[1].board[0]
        self.cast(game, 'grant', source)
        self.assertEqual([a.spell_damage for a in game.state.entities[source].abilities], [1, 2])
        self.cast(game, 'silence', source)
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 2)

    def test_granted_spell_damage_expires_on_absolute_turn(self):
        self.spell('grant', lambda c: [GrantSpellDamage(c.target_id, 2, c.source_id, c.state.turn)], True)
        game = self.game(hand=('grant', 'spell', 'spell'), board=('plain',))
        self.cast(game, 'grant', game.state.players[1].board[0])
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 4)
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 2)

    def test_copied_spell_damage_is_active_for_new_controller(self):
        self.spell('copy', lambda c: [CopyMinion(c.target_id, c.player_id)], True)
        game = self.game(hand=('copy', 'spell'), enemy_board=('power2',))
        self.cast(game, 'copy', game.state.players[2].board[0])
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 4)

    def test_control_transfer_moves_bonus_and_return_to_hand_disables_it(self):
        self.spell('steal', lambda c: [ChangeControl(c.target_id, c.player_id)], True)
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)], True)
        game = self.game(hand=('steal', 'spell', 'bounce', 'spell'), enemy_board=('power2',))
        entity = game.state.players[2].board[0]
        self.cast(game, 'steal', entity)
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 4)
        self.cast(game, 'bounce', entity)
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 2)

    def test_hero_granted_spell_damage_contributes_without_board_slot(self):
        self.spell('grant', lambda c: [GrantSpellDamage(c.state.players[1].hero_id, 2, c.source_id)])
        game = self.game(hand=('grant', 'spell'))
        self.cast(game, 'grant')
        self.assertEqual(self.damages(self.cast(game, 'spell', self.enemy(game)))[0].amount, 4)

    def test_armor_and_overkill_are_separate_from_prevention(self):
        game = self.game(hand=('spell',), board=('power',), enemy_armor=2)
        event = self.damages(self.cast(game, 'spell', self.enemy(game)))[0]
        self.assertEqual((event.amount, dict(event.data)['armor_absorbed'], dict(event.data)['health_damage']), (3, 2, 1))
        game = self.game(hand=('spell',), board=('power2',), enemy_board=('power',))
        event = self.damages(self.cast(game, 'spell', game.state.players[2].board[0]))[0]
        self.assertEqual(event.amount, 4)  # Overkill is damage, not capped at remaining health.

    def test_shield_and_immunity_prevent_modified_amount(self):
        self.spell('area', lambda c: [DamageBatch(tuple(
            Damage(i, 2, c.source_id, DamageKind.SPELL) for i in c.state.players[2].board))])
        game = self.game(hand=('area',), board=('power',), enemy_board=('shield', 'immune'))
        result = self.cast(game, 'area')
        prevented = [e for e in result.events if e.kind == 'damage_prevented']
        self.assertEqual([dict(e.data)['modified_amount'] for e in prevented], [3, 3])
        shield, immune = game.state.players[2].board
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[shield].keywords)
        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[immune].keywords)
        self.assertFalse(self.damages(result))

    def test_zero_spell_packet_gets_bonus_but_zero_effect_does_not_break_shield(self):
        self.spell('zero_spell', lambda c: [Damage(c.target_id, 0, c.source_id, DamageKind.SPELL)], True)
        self.spell('zero_effect', lambda c: [Damage(c.target_id, 0, c.source_id)], True)
        game = self.game(hand=('zero_effect', 'zero_spell'), board=('power',), enemy_board=('shield',))
        target = game.state.players[2].board[0]
        self.cast(game, 'zero_effect', target)
        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[target].keywords)
        self.cast(game, 'zero_spell', target)
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[target].keywords)

    def test_combat_retaliation_and_fatigue_are_classified_without_spell_bonus(self):
        game = self.game(board=('plain', 'power2'), enemy_board=('plain',))
        result = game.apply(Attack(1, game.state.players[1].board[0], game.state.players[2].board[0]))
        self.assertEqual([e.amount for e in self.damages(result)], [2, 2])
        self.assertTrue(all(dict(e.data)['damage_kind'] == 'combat' for e in self.damages(result)))
        result = game.apply(EndTurn(1))
        event = self.damages(result)[0]
        self.assertEqual((event.amount, dict(event.data)['damage_kind'], event.source_id), (1, 'fatigue', None))

    def test_healing_does_not_use_spell_damage(self):
        self.spell('hurt_heal', lambda c: [Damage(c.target_id, 5, c.source_id), Heal(c.target_id, 2, c.source_id)], True)
        game = self.game(hand=('hurt_heal',), board=('power2',))
        target = game.state.players[1].hero_id
        self.cast(game, 'hurt_heal', target)
        self.assertEqual(game.state.entities[target].health, 27)

    def test_hero_power_damage_category_does_not_use_spell_damage(self):
        self.spell('power_packet', lambda c: [Damage(c.target_id, 2, c.state.players[1].hero_id, DamageKind.HERO_POWER)], True)
        game = self.game(hand=('power_packet',), board=('power2',))
        event = self.damages(self.cast(game, 'power_packet', self.enemy(game)))[0]
        self.assertEqual(event.amount, 2)
        self.assertEqual(dict(event.data)['damage_kind'], 'hero_power')

    def test_random_spell_damage_is_reproducible(self):
        self.spell('random', lambda c: [RandomDamage(tuple(c.state.players[2].board), 2, c.source_id, DamageKind.SPELL)])
        game = self.game(hand=('random',), board=('power2',), enemy_board=('plain', 'plain'))
        fork = game.clone()
        self.assertEqual(self.cast(game, 'random'), self.cast(fork, 'random'))
        self.assertEqual(self.damages(game)[0].amount, 4)

    def test_invalid_damage_source_rolls_back_entire_batch(self):
        self.spell('bad', lambda c: [DamageBatch((Damage(c.state.players[2].hero_id, 2, c.source_id),
                                                 Damage(c.state.players[2].hero_id, 3, 999999)))])
        game = self.game(hand=('bad',), board=('power',))
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'source does not exist'):
            self.cast(game, 'bad')
        self.assertEqual(game.snapshot(), before)

    def test_mislabeled_minion_spell_damage_is_rejected(self):
        self.spell('bad', lambda c: [Damage(c.state.players[2].hero_id, 2, c.state.players[1].board[0], DamageKind.SPELL)])
        game = self.game(hand=('bad',), board=('power',))
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'spell source'):
            self.cast(game, 'bad')
        self.assertEqual(game.snapshot(), before)

    def test_typed_damage_and_grants_reject_invalid_fields(self):
        for maker in (lambda: Damage(1, 2, kind='spell'), lambda: Damage(1, 2, kind=DamageKind.SPELL),
                      lambda: Damage(1, 2, 3, DamageKind.FATIGUE), lambda: GrantSpellDamage(1, True),
                      lambda: GrantSpellDamage(1, 0), lambda: GrantSpellDamage(1, 2, expires_turn=0)):
            with self.subTest(maker=maker), self.assertRaises(ValueError):
                maker()

    def test_grants_clone_snapshot_replay_and_old_schema_rejection(self):
        self.spell('grant', lambda c: [GrantSpellDamage(c.target_id, 2, c.source_id)], True)
        game = self.game(hand=('grant', 'spell'), board=('power',))
        self.cast(game, 'grant', game.state.players[1].board[0])
        restored = Game.from_snapshot(game.snapshot(), self.registry)
        self.assertEqual(self.cast(game, 'spell', self.enemy(game)), self.cast(restored, 'spell', self.enemy(restored)))
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())
        for version in (1, 2, 3):
            snapshot = deepcopy(game.snapshot())
            snapshot['schema_version'] = version
            with self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)
        snapshot = game.snapshot()
        entity = str(game.state.players[1].board[0])
        snapshot['state']['entities'][entity]['abilities'][0]['spell_damage'] = True
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
