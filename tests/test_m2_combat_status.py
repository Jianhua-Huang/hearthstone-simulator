"""Lifesteal, freeze, stealth and health-aura interaction contracts."""
import unittest

from hs_sim.engine import (Attack, AuraSpec, CardDefinition, CardType, EndTurn, Game,
                          IllegalAction, Keyword, PlayCard, PlayerSetup, Registry,
                          Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (Buff, ChangeControl, CopyMinion, Damage, DamageBatch,
                                  Destroy, Freeze, GainArmor, GrantAura, GrantKeyword,
                                  RandomDamage, ReturnToHand, Silence, Summon, Transform, Unfreeze)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay


class CombatStatusTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('combat-status-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        for name, attack, health, keywords in (
            ('big', 4, 6, ()), ('small', 1, 2, ()),
            ('life', 3, 2, (Keyword.LIFESTEAL, Keyword.CHARGE)),
            ('shield', 1, 2, (Keyword.DIVINE_SHIELD,)), ('immune', 1, 2, (Keyword.IMMUNE,)),
            ('stealth', 2, 3, (Keyword.STEALTH,)),
            ('hidden_taunt', 1, 3, (Keyword.STEALTH, Keyword.TAUNT)),
            ('wind', 1, 6, (Keyword.WINDFURY,)), ('reborn', 1, 2, (Keyword.REBORN,)),
        ):
            self.registry.register_card(CardDefinition(name, name, CardType.MINION,
                                                       attack=attack, health=health, keywords=keywords))
        self.registry.register_card(CardDefinition('aura', 'aura', CardType.MINION, attack=1, health=3,
                                                   auras=(AuraSpec(health=1),)))
        self.spell('hurt', lambda c: [Damage(c.target_id, 10, c.source_id)])
        self.spell('ping', lambda c: [Damage(c.target_id, 1, c.source_id)])
        self.spell('freeze', lambda c: [Freeze(c.target_id, c.source_id)])
        self.spell('thaw', lambda c: [Unfreeze(c.target_id)])
        self.spell('silence', lambda c: [Silence(c.target_id)])
        self.spell('bounce', lambda c: [ReturnToHand(c.target_id)])
        self.spell('kill', lambda c: [Destroy(c.target_id)])

    def spell(self, name, fn, targeted=True, keywords=()):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
                                                   requires_target=targeted, keywords=keywords))

    def game(self, hand=(), board=(), enemy_board=(), enemy_armor=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('small',)*10, mana=10, max_mana=10),
            PlayerSetup('hero', board=enemy_board, deck=('small',)*10, armor=enemy_armor, mana=10, max_mana=10),
        ), seed=14), self.registry)

    def cast(self, game, name, target=None):
        entity = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == name)
        return game.apply(PlayCard(1, entity, target))

    def hero(self, game, player=1):
        return game.state.players[player].hero_id

    def health(self, game, player=1):
        return game.state.entities[self.hero(game, player)].health

    def test_lifesteal_heals_even_when_source_dies_in_combat(self):
        game = self.game(hand=('hurt',), board=('life',), enemy_board=('big',))
        self.cast(game, 'hurt', self.hero(game))
        source = game.state.players[1].board[0]
        result = game.apply(Attack(1, source, game.state.players[2].board[0]))
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(self.health(game), 23)
        self.assertEqual(next(e.amount for e in result.events if e.kind == 'lifesteal'), 3)

    def test_lifesteal_includes_armor_and_overkill(self):
        for armor, target_minion in ((3, False), (0, True)):
            with self.subTest(armor=armor):
                game = self.game(hand=('hurt',), board=('life',), enemy_board=('small',), enemy_armor=armor)
                self.cast(game, 'hurt', self.hero(game))
                target = game.state.players[2].board[0] if target_minion else self.hero(game, 2)
                game.apply(Attack(1, game.state.players[1].board[0], target))
                self.assertEqual(self.health(game), 23)

    def test_lifesteal_shield_prevention_and_full_health_generate_no_healed_event(self):
        for target in ('shield', 'small'):
            with self.subTest(target=target):
                game = self.game(board=('life',), enemy_board=(target,))
                result = game.apply(Attack(1, game.state.players[1].board[0], game.state.players[2].board[0]))
                self.assertEqual(self.health(game), 30)
                self.assertFalse(any(e.kind == 'healed' for e in result.events))
                if target == 'shield':
                    self.assertFalse(any(e.kind == 'lifesteal' for e in result.events))

    def test_lifesteal_caps_healing_but_keeps_damage_amount(self):
        game = self.game(hand=('ping',), board=('life',))
        self.cast(game, 'ping', self.hero(game))
        result = game.apply(Attack(1, game.state.players[1].board[0], self.hero(game, 2)))
        event = next(e for e in result.events if e.kind == 'lifesteal')
        self.assertEqual((event.amount, dict(event.data)['healed']), (3, 1))

    def test_lifesteal_zero_or_prevented_damage_does_not_heal_wounded_hero(self):
        self.spell('lifezero', lambda c: [Damage(
            c.state.players[2].board[0], 0, c.state.players[1].board[0])], False)
        self.spell('lifehit', lambda c: [Damage(
            c.state.players[2].board[0], 3, c.state.players[1].board[0])], False)
        for target, spell in (('small', 'lifezero'), ('shield', 'lifehit'),
                              ('immune', 'lifehit'), ('small', 'lifehit')):
            with self.subTest(target=target, spell=spell):
                game = self.game(hand=('hurt', spell), board=('life',), enemy_board=(target,))
                self.cast(game, 'hurt', self.hero(game))
                self.assertEqual(self.health(game), 20)
                result = self.cast(game, spell)
                succeeds = target == 'small' and spell == 'lifehit'
                self.assertEqual(self.health(game), 23 if succeeds else 20)
                lifesteals = [e for e in result.events if e.kind == 'lifesteal']
                heals = [e for e in result.events if e.kind == 'healed']
                if succeeds:
                    self.assertEqual(len(lifesteals), 1)
                    self.assertEqual((lifesteals[0].amount,
                                      dict(lifesteals[0].data)['healed']), (3, 3))
                    self.assertEqual(len(heals), 1)
                else:
                    self.assertFalse(lifesteals)
                    self.assertFalse(heals)
                snapshot = game.snapshot()
                self.assertEqual(Game.from_snapshot(snapshot, self.registry).snapshot(), snapshot)
                self.assertEqual(game.clone().snapshot(), snapshot)
                self.assertEqual(replay(build_replay(game), self.registry).snapshot(), snapshot)

    def test_lifesteal_can_save_hero_from_simultaneous_lethal_retaliation(self):
        self.spell('prepare', lambda c: [Damage(c.target_id, 28), Buff(c.target_id, attack=4),
                                          GrantKeyword(c.target_id, Keyword.LIFESTEAL)])
        game = self.game(hand=('prepare',), enemy_board=('big',))
        self.cast(game, 'prepare', self.hero(game))
        game.apply(Attack(1, self.hero(game), game.state.players[2].board[0]))
        self.assertEqual(self.health(game), 2)
        self.assertEqual(game.state.status, 'playing')

    def test_lifesteal_spell_batch_heals_before_hero_death_checkpoint(self):
        self.spell('prepare', lambda c: [DamageBatch(tuple(Damage(p.hero_id, 28) for p in c.state.players.values()))], False)
        self.spell('drain', lambda c: [DamageBatch(tuple(Damage(p.hero_id, 3, c.source_id) for p in c.state.players.values()))],
                   False, (Keyword.LIFESTEAL,))
        game = self.game(hand=('prepare', 'drain'))
        self.cast(game, 'prepare')
        self.cast(game, 'drain')
        self.assertEqual((game.state.status, game.state.winner, self.health(game)), ('finished', 1, 5))

    def test_lifesteal_after_control_transfer_heals_current_controller(self):
        self.spell('steal', lambda c: [ChangeControl(c.target_id, 1)])
        game = self.game(hand=('hurt', 'steal'), enemy_board=('life',))
        self.cast(game, 'hurt', self.hero(game))
        source = game.state.players[2].board[0]
        self.cast(game, 'steal', source)
        game.apply(Attack(1, source, self.hero(game, 2)))
        self.assertEqual(self.health(game), 23)

    def test_silence_removes_lifesteal(self):
        game = self.game(hand=('hurt', 'silence'), board=('life',))
        self.cast(game, 'hurt', self.hero(game))
        source = game.state.players[1].board[0]
        self.cast(game, 'silence', source)
        game.apply(Attack(1, source, self.hero(game, 2)))
        self.assertEqual(self.health(game), 20)

    def test_freeze_ready_friendly_minion_thaws_this_end_turn(self):
        game = self.game(hand=('freeze',), board=('big',))
        source = game.state.players[1].board[0]
        self.cast(game, 'freeze', source)
        self.assertEqual(game.state.entities[source].frozen_until_owner_turn, 1)
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, source, self.hero(game, 2)))
        self.assertEqual(game.snapshot(), before)
        self.assertFalse(any(isinstance(a, Attack) and a.attacker_id == source for a in game.legal_actions()))
        game.apply(EndTurn(1))
        self.assertFalse(game.state.entities[source].frozen)

    def test_freeze_after_attack_lasts_through_next_controller_turn(self):
        game = self.game(hand=('freeze',), board=('big',))
        source = game.state.players[1].board[0]
        game.apply(Attack(1, source, self.hero(game, 2)))
        self.cast(game, 'freeze', source)
        self.assertEqual(game.state.entities[source].frozen_until_owner_turn, 2)
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertTrue(game.state.entities[source].frozen)
        game.apply(EndTurn(1))
        self.assertFalse(game.state.entities[source].frozen)

    def test_freeze_opponent_thaws_at_their_next_end_turn(self):
        game = self.game(hand=('freeze',), enemy_board=('big',))
        target = game.state.players[2].board[0]
        self.cast(game, 'freeze', target)
        game.apply(EndTurn(1))
        self.assertTrue(game.state.entities[target].frozen)
        with self.assertRaises(IllegalAction):
            game.apply(Attack(2, target, self.hero(game)))
        game.apply(EndTurn(2))
        self.assertFalse(game.state.entities[target].frozen)

    def test_summoning_sickness_and_remaining_windfury_attack_affect_thaw(self):
        game = self.game(hand=('big', 'freeze'))
        self.cast(game, 'big')
        source = game.state.players[1].board[0]
        self.cast(game, 'freeze', source)
        self.assertEqual(game.state.entities[source].frozen_until_owner_turn, 2)
        game = self.game(hand=('freeze',), board=('wind',))
        source = game.state.players[1].board[0]
        game.apply(Attack(1, source, self.hero(game, 2)))
        self.cast(game, 'freeze', source)
        self.assertEqual(game.state.entities[source].frozen_until_owner_turn, 1)

    def test_end_turn_trigger_freeze_is_not_immediately_thawed(self):
        self.registry.register_behavior('end_freeze', lambda c: [Freeze(c.source_id)] if c.event.player_id == c.player_id else [])
        self.registry.register_card(CardDefinition('watcher', 'watcher', CardType.MINION, attack=1, health=3,
                                                   triggers=(TriggerSpec('turn_ended', 'end_freeze'),)))
        game = self.game(board=('watcher',))
        source = game.state.players[1].board[0]
        game.apply(EndTurn(1))
        self.assertEqual(game.state.entities[source].frozen_until_owner_turn, 2)

    def test_freeze_during_attack_declaration_cancels_damage(self):
        self.registry.register_behavior('trap', lambda c: [Freeze(c.event.source_id)])
        self.registry.register_card(CardDefinition('watcher', 'watcher', CardType.MINION, health=3,
                                                   triggers=(TriggerSpec('attack_declared', 'trap'),)))
        game = self.game(board=('big',), enemy_board=('watcher',))
        source = game.state.players[1].board[0]
        result = game.apply(Attack(1, source, self.hero(game, 2)))
        self.assertEqual(self.health(game, 2), 30)
        self.assertEqual(game.state.entities[source].attacks_this_turn, 1)
        self.assertTrue(any(e.kind == 'attack_cancelled' for e in result.events))

    def test_frozen_defender_still_retaliates(self):
        game = self.game(hand=('freeze',), board=('big',), enemy_board=('small',))
        source, target = game.state.players[1].board[0], game.state.players[2].board[0]
        self.cast(game, 'freeze', target)
        game.apply(Attack(1, source, target))
        self.assertEqual(game.state.entities[source].damage, 1)

    def test_refreeze_does_not_extend_and_explicit_thaw_or_silence_clears(self):
        for clear in ('thaw', 'silence', 'bounce'):
            with self.subTest(clear=clear):
                game = self.game(hand=('freeze', 'freeze', clear), board=('big',))
                source = game.state.players[1].board[0]
                self.cast(game, 'freeze', source)
                deadline = game.state.entities[source].frozen_until_owner_turn
                self.cast(game, 'freeze', source)
                self.assertEqual(game.state.entities[source].frozen_until_owner_turn, deadline)
                self.cast(game, clear, source)
                self.assertFalse(game.state.entities[source].frozen)

    def test_frozen_current_copy_gets_new_controller_deadline(self):
        self.spell('copy', lambda c: [CopyMinion(c.target_id, 1)])
        game = self.game(hand=('freeze', 'copy'), enemy_board=('big',))
        target = game.state.players[2].board[0]
        self.cast(game, 'freeze', target)
        self.cast(game, 'copy', target)
        copy = game.state.entities[game.state.players[1].board[0]]
        self.assertTrue(copy.frozen)
        self.assertEqual(copy.frozen_until_owner_turn, 2)

    def test_enemy_stealth_cannot_be_attacked_or_selected(self):
        game = self.game(hand=('ping',), board=('big',), enemy_board=('stealth',))
        target = game.state.players[2].board[0]
        for action in (Attack(1, game.state.players[1].board[0], target), PlayCard(1, game.state.players[1].hand[0], target)):
            with self.subTest(action=action), self.assertRaises(IllegalAction):
                game.apply(action)
        self.assertNotIn(target, game.legal_targets(game.state.players[1].hand[0]))

    def test_stealthed_taunt_does_not_block_other_attacks(self):
        game = self.game(board=('big',), enemy_board=('hidden_taunt',))
        game.apply(Attack(1, game.state.players[1].board[0], self.hero(game, 2)))
        self.assertEqual(self.health(game, 2), 26)

    def test_friendly_stealth_is_selectable_and_attack_consumes_it(self):
        game = self.game(hand=('ping',), board=('stealth',))
        source = game.state.players[1].board[0]
        self.cast(game, 'ping', source)
        self.assertIn(Keyword.STEALTH, game.state.entities[source].keywords)
        result = game.apply(Attack(1, source, self.hero(game, 2)))
        self.assertNotIn(Keyword.STEALTH, game.state.entities[source].keywords)
        self.assertTrue(any(e.kind == 'stealth_lost' for e in result.events))

    def test_damage_from_ability_does_not_break_stealth(self):
        self.spell('fire', lambda c: [Damage(c.state.players[2].hero_id, 2, c.state.players[1].board[0])], False)
        game = self.game(hand=('fire',), board=('stealth',))
        self.cast(game, 'fire')
        self.assertIn(Keyword.STEALTH, game.state.entities[game.state.players[1].board[0]].keywords)

    def test_untargeted_random_damage_can_hit_stealth(self):
        self.spell('random', lambda c: [RandomDamage(tuple(c.state.players[2].board), 1, c.source_id)], False)
        game = self.game(hand=('random',), enemy_board=('stealth',))
        self.cast(game, 'random')
        self.assertEqual(game.state.entities[game.state.players[2].board[0]].damage, 1)

    def test_health_aura_raises_health_and_is_idempotent(self):
        game = self.game(board=('aura', 'small'))
        source, target = game.state.players[1].board
        self.assertEqual((game.state.entities[source].max_health, game.state.entities[target].health), (3, 3))
        self.assertEqual(Game.from_snapshot(game.snapshot(), self.registry).snapshot(), game.snapshot())
        self.assertEqual(game.clone().snapshot(), game.snapshot())

    def test_health_aura_removal_clamps_without_double_subtracting_damage(self):
        game = self.game(hand=('ping', 'silence'), board=('aura', 'small'))
        source, target = game.state.players[1].board
        self.cast(game, 'ping', target)
        self.cast(game, 'silence', source)
        self.assertEqual((game.state.entities[target].max_health, game.state.entities[target].health), (2, 2))

    def test_mutual_health_auras_do_not_kill_sources_during_recalculation(self):
        self.spell('hurt3', lambda c: [DamageBatch(tuple(Damage(i, 3, c.source_id) for i in c.state.players[1].board))], False)
        game = self.game(hand=('hurt3',), board=('aura', 'aura'))
        self.cast(game, 'hurt3')
        self.assertEqual([game.state.entities[i].health for i in game.state.players[1].board], [1, 1])
        self.assertEqual(game.clone().snapshot(), game.snapshot())

    def test_simultaneous_dead_aura_sources_keep_last_health_in_records(self):
        self.spell('area', lambda c: [DamageBatch(tuple(Damage(i, 8, c.source_id) for i in c.state.players[1].board[:2]))], False)
        game = self.game(hand=('area',), board=('aura', 'aura', 'small'))
        self.cast(game, 'area')
        self.assertEqual([d.max_health for d in game.state.death_history], [4, 4])
        target = game.state.entities[game.state.players[1].board[0]]
        self.assertEqual((target.max_health, target.health), (2, 2))

    def test_granted_health_aura_expiry_and_self_inclusion(self):
        self.spell('grant', lambda c: [GrantAura(c.target_id, health=2, include_self=True, expires_turn=c.state.turn)])
        game = self.game(hand=('grant',), board=('small', 'small'))
        self.cast(game, 'grant', game.state.players[1].board[0])
        self.assertEqual([game.state.entities[i].health for i in game.state.players[1].board], [4, 4])
        game.apply(EndTurn(1))
        self.assertEqual([game.state.entities[i].health for i in game.state.players[1].board], [2, 2])

    def test_silenced_recipient_keeps_external_health_aura(self):
        game = self.game(hand=('silence',), board=('aura', 'small'))
        target = game.state.players[1].board[1]
        self.cast(game, 'silence', target)
        self.assertEqual(game.state.entities[target].health, 3)

    def test_reborn_under_health_aura_returns_with_one_remaining_health(self):
        game = self.game(hand=('kill',), board=('aura', 'reborn'))
        old = game.state.players[1].board[1]
        self.cast(game, 'kill', old)
        new = game.state.entities[game.state.players[1].board[1]]
        self.assertNotEqual(new.id, old)
        self.assertEqual((new.max_health, new.health), (3, 1))

    def test_health_aura_control_transfer_moves_bonus(self):
        self.spell('steal', lambda c: [ChangeControl(c.target_id, 1)])
        game = self.game(hand=('steal',), board=('small',), enemy_board=('aura', 'small'))
        source, enemy = game.state.players[2].board
        target = game.state.players[1].board[0]
        self.cast(game, 'steal', source)
        self.assertEqual((game.state.entities[target].health, game.state.entities[enemy].health), (3, 2))

    def test_combined_state_roundtrips_and_replays(self):
        game = self.game(hand=('freeze', 'hurt'), board=('aura', 'stealth', 'life'), enemy_board=('big',))
        self.cast(game, 'freeze', game.state.players[1].board[1])
        self.cast(game, 'hurt', self.hero(game))
        game.apply(Attack(1, game.state.players[1].board[2], self.hero(game, 2)))
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())
        self.assertEqual(Game.from_snapshot(game.snapshot(), self.registry).snapshot(), game.snapshot())

    def test_bad_freeze_source_rolls_back_previous_damage_and_all_state(self):
        self.spell('bad', lambda c: [Damage(c.target_id, 1), Freeze(c.target_id, 999999)])
        game = self.game(hand=('bad',), board=('aura', 'small'))
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(game, 'bad', game.state.players[1].board[1])
        self.assertEqual(game.snapshot(), before)

    def test_invalid_health_aura_and_freeze_snapshot_fields_rejected(self):
        for maker in (lambda: GrantAura(1, health=-1), lambda: Freeze(True), lambda: Unfreeze(0)):
            with self.subTest(maker=maker), self.assertRaises(ValueError):
                maker()
        game = self.game(board=('small',))
        for field in ('aura_health', 'frozen_until_owner_turn'):
            snapshot = game.snapshot()
            snapshot['state']['entities'][str(game.state.players[1].board[0])][field] = True
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
