"""Weapons, hero powers and hero replacement through transactional actions."""
from dataclasses import replace
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, DamageKind, EndTurn, Game,
                          IllegalAction, Keyword, PlayCard, PlayerSetup, Registry, Ruleset,
                          Scenario, SnapshotError, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (Buff, Damage, DamageBatch, Destroy, EquipWeapon, Freeze,
                                  GainArmor, GrantDeathrattle, GrantKeyword, ModifyWeapon, RandomDamage, RefreshHeroPower,
                                  ReplaceHero, ReplaceHeroPower, SetHeroPowerUses, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay


class EquipmentPowerTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('equipment-power-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'hero', CardType.HERO, health=30))
        self.registry.register_card(CardDefinition('new_hero', 'new hero', CardType.HERO, health=40,
                                                   keywords=(Keyword.IMMUNE,)))
        self.registry.register_card(CardDefinition('minion', 'minion', CardType.MINION, attack=3, health=4))
        self.registry.register_card(CardDefinition('shield', 'shield', CardType.MINION, attack=1, health=4,
                                                   keywords=(Keyword.DIVINE_SHIELD,)))
        self.registry.register_card(CardDefinition('power_source', 'power source', CardType.MINION,
                                                   attack=1, health=3, spell_damage=2))
        self.registry.register_card(CardDefinition('hidden', 'hidden', CardType.MINION, attack=1, health=3,
                                                   keywords=(Keyword.STEALTH,)))
        self.registry.register_behavior('rattle', lambda c: [GainArmor(c.player_id, c.death.attack)])
        self.registry.register_behavior('battlecry', lambda c: [GainArmor(c.player_id, 1)])
        for name, attack, durability, keywords, rattle in (
            ('axe', 3, 2, (), None), ('last', 4, 1, (), 'rattle'),
            ('wind', 2, 3, (Keyword.WINDFURY,), None), ('zero', 0, 2, (), None),
            ('life', 3, 1, (Keyword.LIFESTEAL, Keyword.POISONOUS), None),
        ):
            self.registry.register_card(CardDefinition(name, name, CardType.WEAPON, attack=attack,
                                                       durability=durability, keywords=keywords, deathrattle=rattle))
        self.registry.register_card(CardDefinition('cry', 'cry', CardType.WEAPON, attack=1, durability=2,
                                                   on_play='battlecry'))
        self.power('ping', lambda c: [Damage(c.target_id, 1, c.source_id, DamageKind.HERO_POWER)], requires_target=True)
        self.power('armor', lambda c: [GainArmor(c.player_id, 2)])
        self.power('dagger', lambda c: [EquipWeapon(c.player_id, 'axe')])
        self.power('recruit', lambda c: [Summon(c.player_id, 'minion')], requires_board_space=True)
        self.power('twice', lambda c: [GainArmor(c.player_id, 1)], uses_per_turn=2)
        self.spell('hurt', lambda c: [Damage(c.target_id, 5)])
        self.spell('freeze', lambda c: [Freeze(c.target_id)])
        self.spell('attack_buff', lambda c: [Buff(c.target_id, attack=2, expires_turn=c.state.turn)])
        self.spell('kill_weapon', lambda c: [Destroy(c.state.players[2].weapon_id)], targeted=False)
        self.spell('replace_power', lambda c: [ReplaceHeroPower(1, 'armor')], targeted=False)
        self.spell('refresh', lambda c: [RefreshHeroPower(1)], targeted=False)
        self.spell('raise_limit', lambda c: [SetHeroPowerUses(1, 2)], targeted=False)

    def power(self, name, fn, **fields):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.HERO_POWER, cost=2, on_use=name, **fields))

    def spell(self, name, fn, targeted=True):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name, requires_target=targeted))

    def game(self, hand=(), weapon=None, power=None, board=(), enemy_board=(), enemy_weapon=None,
             enemy_power=None, mana=10, rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('minion',)*8, mana=mana, max_mana=10,
                        weapon_card_id=weapon, hero_power_card_id=power),
            PlayerSetup('hero', board=enemy_board, deck=('minion',)*8, mana=10, max_mana=10,
                        weapon_card_id=enemy_weapon, hero_power_card_id=enemy_power),
        ), seed=94), self.registry, ruleset=rules)

    def hero(self, game, player=1):
        return game.state.entities[game.state.players[player].hero_id]

    def weapon(self, game, player=1):
        return game.state.entities[game.state.players[player].weapon_id]

    def use(self, game, target=None, player=1):
        return game.apply(UseHeroPower(player, game.state.players[player].hero_power_id, target))

    def cast(self, game, name, target=None):
        state = game.state
        card = next(i for i in state.players[1].hand if state.entities[i].card_id == name)
        return game.apply(PlayCard(1, card, target))

    def attack(self, game, target=None):
        return game.apply(Attack(1, self.hero(game).id, target or self.hero(game, 2).id))

    def next_own_turn(self, game):
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))

    def test_play_equips_same_hand_entity_without_using_board_space(self):
        game = self.game(hand=('axe',), board=('minion',)*7)
        card = game.state.players[1].hand[0]
        self.cast(game, 'axe')
        self.assertEqual(self.weapon(game).id, card)
        self.assertEqual(self.hero(game).attack, 3)
        self.assertEqual(len(game.state.players[1].board), 7)

    def test_weapon_only_contributes_during_controllers_turn(self):
        game = self.game(weapon='axe', enemy_weapon='axe')
        self.assertEqual((self.hero(game).attack, self.hero(game, 2).attack), (3, 0))
        self.attack(game)
        self.assertEqual((self.hero(game).health, self.hero(game, 2).health), (30, 27))
        game.apply(EndTurn(1))
        self.assertEqual((self.hero(game).attack, self.hero(game, 2).attack), (0, 3))
        self.assertEqual(self.weapon(game, 2).durability, 2)

    def test_last_durability_breaks_weapon_with_immutable_death_record_and_rattle(self):
        game = self.game(weapon='last')
        weapon_id = self.weapon(game).id
        self.attack(game)
        self.assertIsNone(game.state.players[1].weapon_id)
        self.assertEqual(self.hero(game).attack, 0)
        self.assertEqual(self.hero(game).armor, 4)
        record = game.state.death_history[0]
        self.assertEqual((record.entity_id, record.zone, record.attack, record.durability), (weapon_id, Zone.WEAPON, 4, 0))
        self.assertEqual(game.state.entities[weapon_id].zone, Zone.GRAVEYARD)

    def test_weapon_replacement_runs_old_rattle_and_preserves_attack_expenditure(self):
        game = self.game(weapon='last', hand=('axe',))
        self.attack(game)
        self.cast(game, 'axe')
        self.assertEqual(self.hero(game).attacks_this_turn, 1)
        with self.assertRaises(IllegalAction):
            self.attack(game)

    def test_replacing_unbroken_weapon_records_destruction_without_extra_attack(self):
        game = self.game(weapon='last', hand=('axe',))
        old = self.weapon(game).id
        self.cast(game, 'axe')
        self.assertEqual(self.hero(game).armor, 4)
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.death_history[0].durability, 1)
        self.attack(game)
        self.assertEqual(self.weapon(game).durability, 1)

    def test_windfury_weapon_changes_limit_without_resetting_used_attack(self):
        game = self.game(weapon='axe', hand=('wind',))
        self.attack(game)
        self.cast(game, 'wind')
        self.attack(game)
        self.assertEqual(self.hero(game).attacks_this_turn, 2)
        with self.assertRaises(IllegalAction):
            self.attack(game)

    def test_shield_still_consumes_durability_and_hero_takes_retaliation(self):
        game = self.game(weapon='axe', enemy_board=('shield',))
        target = game.state.players[2].board[0]
        self.attack(game, target)
        self.assertEqual(game.state.entities[target].health, 4)
        self.assertEqual(self.hero(game).health, 29)
        self.assertEqual(self.weapon(game).durability, 1)

    def test_weapon_lifesteal_poisonous_apply_on_last_charge(self):
        game = self.game(weapon='life', hand=('hurt',), enemy_board=('minion',))
        self.cast(game, 'hurt', self.hero(game).id)
        target = game.state.players[2].board[0]
        self.attack(game, target)
        self.assertEqual(self.hero(game).health, 25)
        self.assertEqual(game.state.entities[target].zone, Zone.GRAVEYARD)
        self.assertNotIn(Keyword.LIFESTEAL, self.hero(game).keywords)
        self.assertEqual(len(game.state.death_history), 2)

    def test_final_lethal_attack_still_spends_and_removes_weapon(self):
        self.spell('lethal', lambda c: [Damage(c.target_id, 27)])
        game = self.game(weapon='life', hand=('lethal',))
        self.cast(game, 'lethal', self.hero(game, 2).id)
        self.attack(game)
        self.assertEqual((game.state.status, game.state.winner), ('finished', 1))
        self.assertIsNone(game.state.players[1].weapon_id)

    def test_frozen_hero_cannot_attack_and_wears_nothing(self):
        game = self.game(weapon='axe', hand=('freeze',))
        self.cast(game, 'freeze', self.hero(game).id)
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.attack(game)
        self.assertEqual(game.snapshot(), before)

    def test_zero_attack_weapon_combines_with_hero_buff_and_still_wears(self):
        game = self.game(weapon='zero', hand=('attack_buff',))
        self.cast(game, 'attack_buff', self.hero(game).id)
        self.attack(game)
        self.assertEqual(self.weapon(game).durability, 1)
        game.apply(EndTurn(1))
        self.assertEqual(self.hero(game).attack, 0)

    def test_negative_weapon_attack_does_not_cancel_independent_hero_attack(self):
        self.spell('weaken', lambda c: [ModifyWeapon(c.state.players[1].weapon_id, attack=-10)], False)
        game = self.game(weapon='axe', hand=('weaken', 'attack_buff'))
        self.cast(game, 'weaken')
        self.cast(game, 'attack_buff', self.hero(game).id)
        self.assertEqual(self.hero(game).attack, 2)

    def test_weapon_modification_refreshes_hero_and_breaks_at_zero_durability(self):
        self.spell('sharpen', lambda c: [ModifyWeapon(c.state.players[1].weapon_id, attack=2, durability=1)], False)
        self.spell('break', lambda c: [ModifyWeapon(c.state.players[1].weapon_id, durability=-9)], False)
        game = self.game(weapon='last', hand=('sharpen', 'break'))
        self.cast(game, 'sharpen')
        self.assertEqual((self.hero(game).attack, self.weapon(game).durability), (6, 2))
        self.cast(game, 'break')
        self.assertEqual(self.hero(game).armor, 6)
        self.assertIsNone(game.state.players[1].weapon_id)

    def test_destroy_enemy_weapon_fires_its_controller_rattle(self):
        game = self.game(hand=('kill_weapon',), enemy_weapon='last')
        self.cast(game, 'kill_weapon')
        self.assertIsNone(game.state.players[2].weapon_id)
        self.assertEqual(self.hero(game, 2).armor, 4)

    def test_equip_effect_does_not_execute_weapon_battlecry(self):
        self.spell('equip', lambda c: [EquipWeapon(1, 'cry')], False)
        game = self.game(hand=('equip', 'cry'))
        self.cast(game, 'equip')
        self.assertEqual(self.hero(game).armor, 0)
        self.cast(game, 'cry')
        self.assertEqual(self.hero(game).armor, 1)

    def test_weapon_triggers_are_active_while_equipped_and_stop_after_destruction(self):
        self.registry.register_behavior('on_power', lambda c: [GainArmor(c.player_id, 1)])
        self.registry.register_card(CardDefinition('listener', 'listener', CardType.WEAPON, attack=1, durability=2,
                                                   triggers=(TriggerSpec('hero_power_used', 'on_power'),)))
        game = self.game(weapon='listener', power='armor', hand=('axe', 'refresh'))
        self.use(game)
        self.assertEqual(self.hero(game).armor, 3)
        self.cast(game, 'axe')
        self.cast(game, 'refresh')
        self.use(game)
        self.assertEqual(self.hero(game).armor, 5)

    def test_granted_weapon_keyword_expires_and_granted_rattle_survives_to_destruction(self):
        self.spell('grant', lambda c: [GrantKeyword(c.state.players[1].weapon_id, Keyword.LIFESTEAL,
                                                   expires_turn=c.state.turn),
                                       GrantDeathrattle(c.state.players[1].weapon_id, 'rattle')], False)
        game = self.game(weapon='axe', hand=('grant', 'last'))
        self.cast(game, 'grant')
        self.assertIn(Keyword.LIFESTEAL, self.hero(game).keywords)
        self.next_own_turn(game)
        self.assertNotIn(Keyword.LIFESTEAL, self.hero(game).keywords)
        self.cast(game, 'last')
        self.assertEqual(self.hero(game).armor, 3)

    def test_weapon_lifesteal_does_not_leak_into_hero_sourced_noncombat_effect(self):
        self.spell('hero_ping', lambda c: [Damage(c.target_id, 2, c.state.players[1].hero_id)])
        game = self.game(weapon='life', hand=('hurt','hero_ping'))
        self.cast(game, 'hurt', self.hero(game).id)
        self.cast(game, 'hero_ping', self.hero(game,2).id)
        self.assertEqual(self.hero(game).health, 25)

    def test_attack_declaration_replacing_weapon_uses_new_weapon_for_exchange(self):
        self.registry.register_behavior('switch', lambda c: [EquipWeapon(1, 'last')])
        self.registry.register_card(CardDefinition('switcher', 'switcher', CardType.MINION, attack=1, health=4,
                                                   triggers=(TriggerSpec('attack_declared', 'switch'),)))
        game = self.game(weapon='axe', board=('switcher',))
        self.attack(game)
        self.assertEqual(self.hero(game, 2).health, 26)
        self.assertIsNone(game.state.players[1].weapon_id)

    def test_declared_attack_cancelled_by_freeze_does_not_spend_weapon(self):
        self.registry.register_behavior('chill', lambda c: [Freeze(c.event.source_id)])
        self.registry.register_card(CardDefinition('freezer', 'freezer', CardType.MINION, attack=1, health=4,
                                                   triggers=(TriggerSpec('attack_declared', 'chill'),)))
        game = self.game(weapon='axe', enemy_board=('freezer',))
        self.attack(game)
        self.assertEqual(self.weapon(game).durability, 2)
        self.assertEqual(self.hero(game).attacks_this_turn, 1)

    def test_power_action_codec_is_strict_and_roundtrips(self):
        action = UseHeroPower(1, 2, 3)
        self.assertEqual(action_from_dict(action_to_dict(action)), action)
        for raw in ({'type':'use_hero_power','player_id':1},
                    {'type':'use_hero_power','player_id':1,'entity_id':True},
                    {'type':'use_hero_power','player_id':1,'entity_id':2,'position':0}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                action_from_dict(raw)

    def test_power_cost_usage_events_and_damage_category(self):
        game = self.game(power='ping', board=('power_source',))
        result = self.use(game, self.hero(game, 2).id)
        player = game.state.players[1]
        self.assertEqual((player.mana, player.hero_power_uses_this_turn), (8, 1))
        self.assertEqual(game.state.entities[player.hero_power_id].uses_this_turn, 1)
        self.assertEqual(self.hero(game, 2).health, 29)
        kinds = [e.kind for e in result.events]
        self.assertIn('hero_power_used', kinds)
        self.assertNotIn('card_played', kinds)
        self.assertEqual(dict(next(e for e in result.events if e.kind == 'damage_dealt').data)['damage_kind'], 'hero_power')

    def test_repeated_power_is_rejected_atomically_and_not_enumerated(self):
        game = self.game(power='armor')
        self.use(game)
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.use(game)
        self.assertEqual(game.snapshot(), before)
        self.assertFalse(any(isinstance(a, UseHeroPower) for a in game.legal_actions()))

    def test_power_refreshes_on_turn_transition(self):
        game = self.game(power='armor')
        self.use(game)
        self.next_own_turn(game)
        self.use(game)
        self.assertEqual(self.hero(game).armor, 4)
        self.assertEqual(game.state.players[1].hero_power_uses_this_turn, 1)

    def test_power_targeting_protects_enemy_stealth_and_matches_enumeration(self):
        game = self.game(power='ping', enemy_board=('hidden','minion'))
        source = game.state.players[1].hero_power_id
        allowed = game.legal_targets(source)
        self.assertNotIn(game.state.players[2].board[0], allowed)
        candidates = [a for a in game.legal_actions() if isinstance(a, UseHeroPower)]
        self.assertEqual({a.target_id for a in candidates}, set(allowed))
        for candidate in candidates:
            game.validate(candidate)

    def test_power_bad_target_insufficient_mana_and_wrong_player_roll_back(self):
        for mode in ('target', 'mana', 'player'):
            game = self.game(power='ping', enemy_power='armor', mana=1 if mode=='mana' else 10)
            action = (UseHeroPower(2, game.state.players[2].hero_power_id) if mode=='player' else
                      UseHeroPower(1, game.state.players[1].hero_power_id, None if mode=='target' else self.hero(game,2).id))
            before = game.snapshot()
            with self.subTest(mode=mode), self.assertRaises(IllegalAction):
                game.apply(action)
            self.assertEqual(game.snapshot(), before)

    def test_recruit_activation_respects_configured_board_limit(self):
        game = self.game(power='recruit', board=('minion',), rules=Ruleset(max_board=1))
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            self.use(game)
        self.assertFalse(any(isinstance(a, UseHeroPower) for a in game.legal_actions()))
        self.assertEqual(game.snapshot(), before)

    def test_recruit_power_summons_and_dagger_power_equips(self):
        for power in ('recruit','dagger'):
            with self.subTest(power=power):
                game = self.game(power=power)
                self.use(game)
                player = game.state.players[1]
                if power=='recruit':
                    self.assertEqual(len(player.board), 1)
                else:
                    self.assertEqual(self.weapon(game).card_id, 'axe')
                    self.attack(game)

    def test_replace_power_gives_new_identity_and_fresh_uses_but_preserves_turn_total(self):
        game = self.game(power='ping', hand=('replace_power',))
        old = game.state.players[1].hero_power_id
        self.use(game, self.hero(game, 2).id)
        self.cast(game, 'replace_power')
        new = game.state.players[1].hero_power_id
        self.assertNotEqual(new, old)
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        with self.assertRaises(IllegalAction):
            game.apply(UseHeroPower(1, old, self.hero(game, 2).id))
        self.use(game)
        self.assertEqual(game.state.players[1].hero_power_uses_this_turn, 2)

    def test_refresh_and_higher_limit_do_not_reset_total_uses(self):
        game = self.game(power='armor', hand=('raise_limit','refresh'))
        self.use(game)
        self.cast(game, 'raise_limit')
        self.use(game)
        self.cast(game, 'refresh')
        self.use(game)
        self.assertEqual(game.state.players[1].hero_power_uses_this_turn, 3)
        self.assertEqual(self.hero(game).armor, 6)

    def test_printed_multiple_use_limit(self):
        game = self.game(power='twice')
        self.use(game)
        self.use(game)
        with self.assertRaises(IllegalAction):
            self.use(game)

    def test_custom_activation_rule_gets_detached_state_and_requires_bool(self):
        def mutate(ctx):
            ctx.state.players[1].mana = 0
            return True
        self.registry.register_use_rule('pure', mutate)
        self.registry.register_use_rule('bad', lambda c: 1)
        self.power('custom', lambda c: [GainArmor(1, 1)], use_rule='pure')
        self.power('invalid', lambda c: [], use_rule='bad')
        game = self.game(power='custom')
        self.use(game)
        self.assertEqual(game.state.players[1].mana, 8)
        bad = self.game(power='invalid')
        before = bad.snapshot()
        with self.assertRaises(ResolutionError):
            self.use(bad)
        self.assertEqual(bad.snapshot(), before)

    def test_hero_power_failure_after_rng_and_equipment_rolls_back_payment_and_usage(self):
        self.power('broken', lambda c: [RandomDamage((c.state.players[2].hero_id,), 1),
                                        EquipWeapon(1, 'axe'), EquipWeapon(1, 'missing')])
        game = self.game(power='broken', weapon='last')
        before = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.use(game)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.history, [])

    def test_hero_replacement_preserves_health_armor_weapon_and_attack_spent(self):
        self.spell('replace_hero', lambda c: [ReplaceHero(1, 'new_hero', armor=5, hero_power_card_id='armor')], False)
        game = self.game(weapon='axe', power='ping', hand=('hurt','attack_buff','replace_hero'))
        old = self.hero(game).id
        self.cast(game, 'hurt', old)
        self.cast(game, 'attack_buff', old)
        self.use(game, self.hero(game,2).id)
        self.attack(game)
        self.cast(game, 'replace_hero')
        hero = self.hero(game)
        self.assertNotEqual(hero.id, old)
        self.assertEqual((hero.health, hero.max_health, hero.armor, hero.attack, hero.attacks_this_turn), (25, 40, 5, 5, 1))
        self.assertIn(Keyword.IMMUNE, hero.keywords)
        self.assertEqual(game.state.entities[old].zone, Zone.GRAVEYARD)
        self.use(game)
        with self.assertRaises(IllegalAction):
            self.attack(game)
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())

    def test_hero_replacement_keeps_power_usage_unless_explicitly_replaced(self):
        self.spell('replace_hero', lambda c: [ReplaceHero(1, 'hero', health=15)], False)
        game = self.game(power='armor', hand=('replace_hero',))
        power = game.state.players[1].hero_power_id
        self.use(game)
        self.cast(game, 'replace_hero')
        self.assertEqual(self.hero(game).health, 15)
        self.assertEqual(game.state.players[1].hero_power_id, power)
        with self.assertRaises(IllegalAction):
            self.use(game)

    def test_weapon_and_power_slots_reject_wrong_definitions_and_hand_power(self):
        for setup in (PlayerSetup('hero', weapon_card_id='minion'), PlayerSetup('hero', hero_power_card_id='axe'),
                      PlayerSetup('hero', hand=('ping',))):
            with self.subTest(setup=setup), self.assertRaises(ValueError):
                Game.from_scenario(Scenario((setup, PlayerSetup('hero'))), self.registry)

    def test_new_state_roundtrips_clones_and_replays_with_weapon_death_history(self):
        game = self.game(weapon='last', power='dagger')
        self.attack(game)
        self.use(game)
        self.next_own_turn(game)
        copy = game.clone()
        restored = Game.from_snapshot(game.snapshot(), self.registry)
        for branch in (game, copy, restored):
            self.attack(branch)
        self.assertEqual(game.snapshot(), copy.snapshot())
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())

    def test_snapshot_rejects_wrong_slot_cache_and_usage_types(self):
        game = self.game(weapon='axe', power='armor')
        for mode in ('slot','cache','durability','uses','keywords','power_type'):
            snapshot = game.snapshot()
            player = snapshot['state']['players']['1']
            entities = snapshot['state']['entities']
            if mode == 'slot': player['weapon_id'] = player['hero_id']
            elif mode == 'cache': entities[str(player['hero_id'])]['weapon_attack'] += 1
            elif mode == 'durability': entities[str(player['weapon_id'])]['durability'] = 0
            elif mode == 'uses': entities[str(player['hero_power_id'])]['uses_this_turn'] = True
            elif mode == 'keywords': entities[str(player['hero_id'])]['weapon_keywords'] = ['taunt']
            else: player['hero_power_id'] = player['weapon_id']
            with self.subTest(mode=mode), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)
        for version in range(1, 6):
            snapshot = game.snapshot()
            snapshot['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
