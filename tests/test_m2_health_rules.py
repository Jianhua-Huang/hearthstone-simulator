"""Cross-mechanism damage/healing rules through public actions and replay."""
import unittest

from hs_sim.engine import (Attack, CardDefinition, CardType, DamageKind, EndTurn, Game,
                          HealingKind, HealthFlow, HealthLayer, HealthOp, HealthRule, Keyword,
                          CostSpec, PaymentType, PlayCard, PlayerSetup, Registry, ResolutionError, Ruleset, Scenario,
                          SnapshotError, SpellSchool, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddCostModifier, ChangeControl, CopyMinion, Damage, DamageBatch, Destroy,
                                  GrantHealthRule, Heal, HealBatch, ReturnToHand, Silence, Transform)
from hs_sim.engine.replay import build_replay, replay


def outgoing(flow, operation=HealthOp.SCALE, amount=2, **kwargs):
    return HealthRule(flow, operation, amount, source_relation='friendly', **kwargs)


class HealthRuleTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('health-rule-tests-v1')
        for card in (
            CardDefinition('hero', 'hero', CardType.HERO, health=30),
            CardDefinition('plain', 'plain', CardType.MINION, attack=2, health=20),
            CardDefinition('life', 'life', CardType.MINION, attack=3, health=6, keywords=(Keyword.LIFESTEAL,)),
            CardDefinition('shield', 'shield', CardType.MINION, health=20, keywords=(Keyword.DIVINE_SHIELD,)),
            CardDefinition('immune', 'immune', CardType.MINION, health=20, keywords=(Keyword.IMMUNE,)),
            CardDefinition('spell_power', 'spell power', CardType.MINION, health=1, spell_damage=1),
        ):
            self.registry.register_card(card)
        self.script('damage', lambda c: [Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)], target=True,
                    spell_school=SpellSchool.FIRE)
        self.script('frost', lambda c: [Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)], target=True,
                    spell_school=SpellSchool.FROST)
        self.script('effect', lambda c: [Damage(c.target_id, 3, c.source_id)], target=True)
        self.script('heal', lambda c: [Heal(c.target_id, 3, c.source_id, HealingKind.SPELL)], target=True,
                    spell_school=SpellSchool.HOLY)
        self.script('silence', lambda c: [Silence(c.target_id)], target=True)

    def script(self, name, fn, target=False, **fields):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name,
                                                   requires_target=target, **fields))

    def provider(self, name, *rules, health=4):
        self.registry.register_card(CardDefinition(name, name, CardType.MINION, health=health, health_rules=rules))

    def game(self, hand=(), board=(), enemy_board=(), enemy_armor=0, power=None, weapon=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 8, mana=10, max_mana=10,
                        hero_power_card_id=power, weapon_card_id=weapon),
            PlayerSetup('hero', board=enemy_board, deck=('plain',) * 8, armor=enemy_armor, mana=10, max_mana=10),
        ), seed=41), self.registry)

    def cast(self, g, name, target=None):
        card = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, card, target))

    def hero(self, g, player=1):
        return g.state.players[player].hero_id

    def damage_events(self, result):
        return [e for e in result.events if e.kind == 'damage_dealt']

    def assert_replay(self, g):
        self.assertEqual(replay(build_replay(g), self.registry).snapshot(), g.snapshot())
        self.assertEqual(Game.from_snapshot(g.snapshot(), self.registry).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())

    def test_spell_bonus_precedes_outgoing_multiplier(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE, damage_kinds=(DamageKind.SPELL,)))
        g = self.game(('damage',), board=('double', 'spell_power'))
        result = self.cast(g, 'damage', self.hero(g, 2))
        self.assertEqual(self.damage_events(result)[0].amount, 8)
        self.assertEqual(dict(self.damage_events(result)[0].data)['spell_bonus'], 1)
        self.assert_replay(g)

    def test_two_multipliers_stack(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        g = self.game(('damage',), board=('double', 'double'))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 12)

    def test_school_specific_addition_and_fractional_multiplier(self):
        self.provider('school', outgoing(HealthFlow.DAMAGE, HealthOp.ADD, 2, schools=(SpellSchool.FIRE,)),
                      outgoing(HealthFlow.DAMAGE, HealthOp.SCALE, 3, denominator=2, schools=(SpellSchool.FIRE,)))
        g = self.game(('damage', 'frost'), board=('school',))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 7)
        self.assertEqual(self.damage_events(self.cast(g, 'frost', self.hero(g, 2)))[0].amount, 3)

    def test_spell_filter_excludes_effect_and_combat(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE, damage_kinds=(DamageKind.SPELL,)))
        g = self.game(('effect',), board=('double', 'plain'))
        self.assertEqual(self.damage_events(self.cast(g, 'effect', self.hero(g, 2)))[0].amount, 3)
        result = g.apply(Attack(1, g.state.players[1].board[1], self.hero(g, 2)))
        self.assertEqual(self.damage_events(result)[0].amount, 2)

    def test_source_relation_excludes_opponent(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        g = self.game(('damage',), enemy_board=('double',))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 3)

    def test_incoming_multiplier_matches_both_players_minions_only(self):
        self.provider('moarg', HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=HealthLayer.TARGET,
                                         target_kinds=(CardType.MINION,), damage_kinds=(DamageKind.SPELL,)))
        g = self.game(('damage', 'damage', 'damage'), board=('moarg', 'plain'), enemy_board=('plain',))
        targets = (g.state.players[1].board[1], g.state.players[2].board[0], self.hero(g, 2))
        values = [self.damage_events(self.cast(g, 'damage', t))[0].amount for t in targets]
        self.assertEqual(values, [6, 6, 3])

    def test_outgoing_then_incoming_then_cap(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        self.provider('receive', HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 3, layer=HealthLayer.TARGET,
                                           target_relation='friendly'),
                      HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 4, layer=HealthLayer.TARGET, target_relation='friendly'))
        g = self.game(('damage',), board=('double',), enemy_board=('receive',), enemy_armor=2)
        event = self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0]
        self.assertEqual((event.amount, dict(event.data)['armor_absorbed'], dict(event.data)['health_damage']), (4, 2, 2))

    def test_set_override_and_negative_addition_are_explicit(self):
        self.provider('rules', outgoing(HealthFlow.DAMAGE, HealthOp.ADD, -100),
                      outgoing(HealthFlow.DAMAGE, HealthOp.SET, 2))
        g = self.game(('damage',), board=('rules',))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 2)

    def test_prevention_and_zero_damage_preserve_shield(self):
        for operation, amount in ((HealthOp.PREVENT, 0), (HealthOp.ADD, -10)):
            with self.subTest(operation=operation):
                # Fresh registry because each Game freezes its definitions.
                self.setUp()
                self.provider('stop', outgoing(HealthFlow.DAMAGE, operation, amount))
                g = self.game(('damage',), board=('stop',), enemy_board=('shield',))
                target = g.state.players[2].board[0]
                self.assertFalse(self.damage_events(self.cast(g, 'damage', target)))
                self.assertIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_fatigue_can_be_capped_by_recipient_rule(self):
        from hs_sim.engine.effects import Draw
        self.provider('cap', HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET,
                                       target_relation='friendly', target_kinds=(CardType.HERO,)))
        self.script('fatigue', lambda c: [Damage(c.state.players[1].hero_id, 4, kind=DamageKind.FATIGUE)])
        g = self.game(('fatigue',), board=('cap',))
        self.assertEqual(self.damage_events(self.cast(g, 'fatigue'))[0].amount, 1)

    def test_all_damage_modifiers_freeze_for_simultaneous_batch(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE), health=1)
        self.script('batch', lambda c: [DamageBatch((Damage(c.state.players[1].board[0], 1, c.source_id),
                                                    Damage(c.state.players[2].hero_id, 1, c.source_id)))])
        g = self.game(('batch',), board=('double',))
        self.assertEqual([e.amount for e in self.damage_events(self.cast(g, 'batch'))], [2, 2])

    def test_sequential_effects_recompute_after_provider_dies(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE), health=1)
        self.script('sequence', lambda c: [Damage(c.state.players[1].board[0], 1, c.source_id),
                                          Damage(c.state.players[2].hero_id, 1, c.source_id)])
        g = self.game(('sequence',), board=('double',))
        self.assertEqual([e.amount for e in self.damage_events(self.cast(g, 'sequence'))], [2, 1])

    def test_healing_multiplier_caps_at_missing_health(self):
        self.provider('healer', outgoing(HealthFlow.HEALING, healing_kinds=(HealingKind.SPELL,)))
        g = self.game(('effect', 'heal'), board=('healer',))
        self.cast(g, 'effect', self.hero(g))
        result = self.cast(g, 'heal', self.hero(g))
        event = next(e for e in result.events if e.kind == 'healed')
        self.assertEqual((event.amount, dict(event.data)['modified_amount']), (3, 6))

    def test_healing_does_not_use_spell_damage(self):
        g = self.game(('effect', 'effect', 'heal'), board=('spell_power',))
        self.cast(g, 'effect', self.hero(g))
        self.cast(g, 'effect', self.hero(g))
        self.cast(g, 'heal', self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health, 27)

    def test_healing_prevention_has_no_healed_event(self):
        self.provider('stop', outgoing(HealthFlow.HEALING, HealthOp.PREVENT, 0))
        g = self.game(('effect', 'heal'), board=('stop',))
        self.cast(g, 'effect', self.hero(g))
        result = self.cast(g, 'heal', self.hero(g))
        self.assertFalse(any(e.kind == 'healed' for e in result.events))
        self.assertEqual(sum(e.kind == 'healing_prevented' for e in result.events), 1)
        self.assertEqual(g.state.entities[self.hero(g)].health, 27)

    def test_lifesteal_uses_healing_modifiers(self):
        self.provider('healer', outgoing(HealthFlow.HEALING))
        self.script('hurt', lambda c: [Damage(c.state.players[1].hero_id, 10)])
        g = self.game(('hurt',), board=('healer', 'life'))
        self.cast(g, 'hurt')
        result = g.apply(Attack(1, g.state.players[1].board[1], self.hero(g, 2)))
        self.assertEqual(g.state.entities[self.hero(g)].health, 26)
        self.assertEqual(dict(next(e for e in result.events if e.kind == 'lifesteal').data)['healed'], 6)
        self.assert_replay(g)

    def test_lifesteal_spell_retains_spell_origin_for_healing(self):
        self.provider('velen', outgoing(HealthFlow.DAMAGE, damage_kinds=(DamageKind.SPELL,)),
                      outgoing(HealthFlow.HEALING, healing_kinds=(HealingKind.SPELL,)))
        self.script('hurt', lambda c: [Damage(c.state.players[1].hero_id, 20)])
        self.script('drain', lambda c: [Damage(c.target_id, 3, c.source_id, DamageKind.SPELL)],
                    target=True, keywords=(Keyword.LIFESTEAL,))
        g = self.game(('hurt', 'drain'), board=('velen',))
        self.cast(g, 'hurt')
        result = self.cast(g, 'drain', self.hero(g, 2))
        self.assertEqual(self.damage_events(result)[0].amount, 6)
        self.assertEqual(g.state.entities[self.hero(g)].health, 22)

    def test_hero_power_healing_classification(self):
        self.registry.register_behavior('power', lambda c: [Heal(c.target_id, 2, c.source_id, HealingKind.HERO_POWER)])
        self.registry.register_card(CardDefinition('power', 'power', CardType.HERO_POWER, on_use='power', requires_target=True))
        self.provider('velen', outgoing(HealthFlow.HEALING, healing_kinds=(HealingKind.HERO_POWER,)))
        self.script('hurt', lambda c: [Damage(c.state.players[1].hero_id, 8)])
        g = self.game(('hurt',), board=('velen',), power='power')
        self.cast(g, 'hurt')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id, self.hero(g)))
        self.assertEqual(g.state.entities[self.hero(g)].health, 26)

    def test_healing_conversion_deals_damage_to_full_health_target(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0))
        g = self.game(('heal',), board=('auchenai',))
        result = self.cast(g, 'heal', self.hero(g, 2))
        self.assertEqual(g.state.entities[self.hero(g, 2)].health, 27)
        self.assertFalse(any(e.kind == 'healed' for e in result.events))
        self.assertTrue(dict(self.damage_events(result)[0].data)['converted'])
        self.assert_replay(g)

    def test_conversion_before_scaling_does_not_apply_both_flow_multipliers(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0))
        self.provider('velen', outgoing(HealthFlow.HEALING), outgoing(HealthFlow.DAMAGE))
        g = self.game(('heal',), board=('auchenai', 'velen', 'spell_power'))
        self.assertEqual(self.damage_events(self.cast(g, 'heal', self.hero(g, 2)))[0].amount, 8)

    def test_converted_heal_is_stopped_by_shield(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0))
        g = self.game(('heal',), board=('auchenai',), enemy_board=('shield',))
        target = g.state.players[2].board[0]
        result = self.cast(g, 'heal', target)
        self.assertFalse(self.damage_events(result))
        self.assertNotIn(Keyword.DIVINE_SHIELD, g.state.entities[target].keywords)

    def test_recipient_conversion_does_not_protect_opposing_controller(self):
        self.provider('convert', HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT, target_relation='friendly'))
        self.script('hurt', lambda c: [Damage(c.state.players[1].hero_id, 5)])
        g = self.game(('hurt', 'damage'), enemy_board=('convert',))
        self.cast(g, 'hurt')
        result = self.cast(g, 'damage', self.hero(g))
        self.assertEqual(self.damage_events(result)[0].amount, 3)  # not protected by enemy's friendly rule

    def test_damage_conversion_heals_without_spell_damage_bonus(self):
        self.provider('convert', HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT, target_relation='friendly',
                                           damage_kinds=(DamageKind.SPELL,)))
        g = self.game(('effect', 'damage'), board=('convert', 'spell_power'))
        self.cast(g, 'effect', self.hero(g))
        result = self.cast(g, 'damage', self.hero(g))
        self.assertEqual(g.state.entities[self.hero(g)].health, 30)
        self.assertFalse(self.damage_events(result))
        self.assertEqual(next(e.amount for e in result.events if e.kind == 'healed'), 3)

    def test_opposing_conversion_rules_apply_only_once(self):
        self.provider('both', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0),
                      outgoing(HealthFlow.DAMAGE, HealthOp.CONVERT, 0))
        g = self.game(('heal',), board=('both',))
        result = self.cast(g, 'heal', self.hero(g, 2))
        self.assertEqual(self.damage_events(result)[0].amount, 3)
        self.assertEqual(sum(e.kind == 'health_effect_converted' for e in result.events), 1)

    def test_lifesteal_conversion_runs_once_and_does_not_loop(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0))
        g = self.game(board=('auchenai', 'life'))
        result = g.apply(Attack(1, g.state.players[1].board[1], self.hero(g, 2)))
        self.assertEqual(g.state.entities[self.hero(g)].health, 27)
        self.assertEqual(sum(e.kind == 'lifesteal' for e in result.events), 1)
        self.assertEqual([e.amount for e in self.damage_events(result)], [3, 3])
        self.assert_replay(g)

    def test_lifesteal_conversion_does_not_add_spell_bonus_twice(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0))
        self.script('drain', lambda c: [Damage(c.target_id, 2, c.source_id, DamageKind.SPELL)],
                    target=True, keywords=(Keyword.LIFESTEAL,))
        g = self.game(('drain',), board=('auchenai', 'spell_power'))
        self.assertEqual([e.amount for e in self.damage_events(self.cast(g, 'drain', self.hero(g, 2)))], [3, 3])

    def bolf(self, name='bolf', **fields):
        self.provider(name, HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                                      target_relation='friendly', target_kinds=(CardType.HERO,), redirect_to='self'), **fields)

    def test_hero_damage_redirects_before_armor(self):
        self.bolf(health=20)
        g = self.game(('damage',), enemy_board=('bolf',), enemy_armor=5)
        result = self.cast(g, 'damage', self.hero(g, 2))
        target = g.state.players[2].board[0]
        self.assertEqual((g.state.entities[self.hero(g, 2)].health, g.state.entities[self.hero(g, 2)].armor), (30, 5))
        self.assertEqual(g.state.entities[target].health, 17)
        self.assertEqual(dict(self.damage_events(result)[0].data)['redirect_path'], (self.hero(g, 2), target))
        self.assert_replay(g)

    def test_redirected_hero_attack_still_consumes_last_weapon_durability(self):
        self.bolf(health=4)
        self.registry.register_card(CardDefinition('axe', 'axe', CardType.WEAPON, attack=6, durability=1))
        g = self.game(weapon='axe', enemy_board=('bolf',))
        g.apply(Attack(1, self.hero(g), self.hero(g, 2)))
        self.assertIsNone(g.state.players[1].weapon_id)
        self.assertFalse(g.state.players[2].board)
        self.assertEqual(g.state.entities[self.hero(g, 2)].health, 30)
        self.assertEqual({d.zone for d in g.state.death_history}, {Zone.WEAPON, Zone.BOARD})
        self.assert_replay(g)

    def test_redirected_lifesteal_uses_final_recipients_capped_damage(self):
        self.provider('bolf', HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                                        target_relation='friendly', target_kinds=(CardType.HERO,), redirect_to='self'),
                      HealthRule(HealthFlow.DAMAGE, HealthOp.CAP, 1, layer=HealthLayer.TARGET, target_relation='self'))
        g = self.game(('effect',), board=('life',), enemy_board=('bolf',))
        self.cast(g, 'effect', self.hero(g))
        result = g.apply(Attack(1, g.state.players[1].board[0], self.hero(g, 2)))
        self.assertEqual(next(e.amount for e in result.events if e.kind == 'lifesteal'), 1)
        self.assertEqual(g.state.entities[self.hero(g)].health, 28)

    def test_health_payment_does_not_enter_damage_replacement_rules(self):
        self.provider('convert', HealthRule(HealthFlow.DAMAGE, HealthOp.CONVERT, target_relation='friendly'))
        self.script('conversion', lambda c: [AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH), 1)])
        self.script('paid', lambda c: [], cost=3)
        g = self.game(('conversion', 'paid'), board=('convert',))
        self.cast(g, 'conversion')
        result = self.cast(g, 'paid')
        self.assertEqual(g.state.entities[self.hero(g)].health, 27)
        self.assertFalse(any(e.kind in ('damage_dealt', 'healed', 'health_effect_converted') for e in result.events))

    def test_redirected_target_uses_its_own_incoming_rules(self):
        self.bolf(health=20)
        self.provider('moarg', HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, layer=HealthLayer.TARGET,
                                         target_kinds=(CardType.MINION,), damage_kinds=(DamageKind.SPELL,)))
        g = self.game(('damage',), board=('moarg',), enemy_board=('bolf',))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 6)

    def test_redirection_does_not_split_excess_into_original_hero(self):
        self.bolf(health=1)
        g = self.game(('damage',), enemy_board=('bolf',))
        self.cast(g, 'damage', self.hero(g, 2))
        self.assertEqual(g.state.entities[self.hero(g, 2)].health, 30)
        self.assertFalse(g.state.players[2].board)

    def test_first_eligible_redirection_wins_without_duplicate_damage(self):
        self.bolf(health=20)
        g = self.game(('damage',), enemy_board=('bolf', 'bolf'))
        result = self.cast(g, 'damage', self.hero(g, 2))
        self.assertEqual(len(self.damage_events(result)), 1)
        self.assertEqual([g.state.entities[i].health for i in g.state.players[2].board], [17, 20])

    def test_redirection_cycle_rolls_back_action(self):
        rule = HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                          target_relation='friendly', target_kinds=(CardType.HERO,), redirect_to='enemy_hero')
        self.provider('redirect', rule)
        g = self.game(('damage',), board=('redirect',), enemy_board=('redirect',))
        before = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'cycle'):
            self.cast(g, 'damage', self.hero(g, 2))
        self.assertEqual(g.snapshot(), before)

    def test_stale_target_is_not_revived_by_redirection(self):
        self.provider('redirect', HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                                            redirect_to='friendly_hero'))
        self.script('stale', lambda c: [Destroy(c.target_id), Damage(c.target_id, 3, c.source_id)], target=True)
        g = self.game(('stale',), enemy_board=('plain', 'redirect'))
        result = self.cast(g, 'stale', g.state.players[2].board[0])
        self.assertFalse(self.damage_events(result))
        self.assertEqual(g.state.entities[self.hero(g, 2)].health, 30)

    def test_healing_can_be_redirected(self):
        self.provider('redirect', HealthRule(HealthFlow.HEALING, HealthOp.REDIRECT, layer=HealthLayer.TARGET,
                                            source_relation='friendly', redirect_to='friendly_hero'))
        g = self.game(('effect', 'heal'), board=('redirect',))
        self.cast(g, 'effect', self.hero(g))
        self.cast(g, 'heal', self.hero(g, 2))
        self.assertEqual(g.state.entities[self.hero(g)].health, 30)

    def test_dynamic_rule_expires_at_end_of_turn(self):
        rule = outgoing(HealthFlow.DAMAGE)
        self.script('grant', lambda c: [GrantHealthRule(c.target_id, rule, c.source_id, c.state.turn)], target=True)
        g = self.game(('grant', 'damage', 'damage'), board=('plain',))
        self.cast(g, 'grant', g.state.players[1].board[0])
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 6)
        self.assert_replay(g)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 3)

    def test_silence_removes_printed_rules(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        g = self.game(('silence', 'damage'), board=('double',))
        self.cast(g, 'silence', g.state.players[1].board[0])
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 3)

    def test_copy_gives_independent_rule_ids_and_stacks(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        self.script('copy', lambda c: [CopyMinion(c.target_id, 1)], target=True)
        g = self.game(('copy', 'damage'), board=('double',))
        self.cast(g, 'copy', g.state.players[1].board[0])
        event = self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0]
        self.assertEqual(event.amount, 12)
        self.assertEqual(len(set(dict(event.data)['rule_ids'])), 2)
        self.assert_replay(g)

    def test_control_transfer_rebinds_friendly_source_relation(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        self.script('take', lambda c: [ChangeControl(c.target_id, 1)], target=True)
        g = self.game(('take', 'damage'), enemy_board=('double',))
        self.cast(g, 'take', g.state.players[2].board[0])
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 6)

    def test_transform_removes_rule(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        self.script('change', lambda c: [Transform(c.target_id, 'plain')], target=True)
        g = self.game(('change', 'damage'), board=('double',))
        self.cast(g, 'change', g.state.players[1].board[0])
        self.assertEqual(self.damage_events(self.cast(g, 'damage', self.hero(g, 2)))[0].amount, 3)

    def test_batch_healing_converts_as_one_death_boundary(self):
        self.provider('auchenai', outgoing(HealthFlow.HEALING, HealthOp.CONVERT, 0), health=1)
        self.script('batch', lambda c: [HealBatch((Heal(c.state.players[1].board[0], 2, c.source_id),
                                                  Heal(c.state.players[2].hero_id, 2, c.source_id)))])
        g = self.game(('batch',), board=('auchenai',))
        result = self.cast(g, 'batch')
        self.assertEqual([e.amount for e in self.damage_events(result)], [2, 2])
        self.assertFalse(g.state.players[1].board)

    def test_strict_rule_effect_and_definition_validation(self):
        for construct in (
            lambda: HealthRule('damage', HealthOp.ADD),
            lambda: outgoing(HealthFlow.DAMAGE, amount=True),
            lambda: outgoing(HealthFlow.DAMAGE, denominator=0),
            lambda: outgoing(HealthFlow.DAMAGE, HealthOp.ADD, 1, denominator=2),
            lambda: outgoing(HealthFlow.DAMAGE, schools=('fire',)),
            lambda: outgoing(HealthFlow.DAMAGE, healing_kinds=(HealingKind.SPELL,)),
            lambda: HealthRule(HealthFlow.DAMAGE, HealthOp.REDIRECT, redirect_to='self'),
            lambda: Heal(1, 2, kind=HealingKind.SPELL),
            lambda: HealBatch([Heal(1, 1)]),
            lambda: GrantHealthRule(1, {}),
        ):
            with self.subTest(construct=construct), self.assertRaises(ValueError):
                construct()
        with self.assertRaises(ValueError):
            self.registry.register_card(CardDefinition('bad', 'bad', CardType.MINION, health=1, spell_school=SpellSchool.FIRE))

    def test_unknown_healing_source_fails_transactionally(self):
        self.script('bad', lambda c: [Heal(c.target_id, 2, 9999)], target=True)
        g = self.game(('bad',))
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(g, 'bad', self.hero(g))
        self.assertEqual(g.snapshot(), before)

    def test_snapshot_seven_and_unknown_rule_fields_rejected(self):
        self.provider('double', outgoing(HealthFlow.DAMAGE))
        g = self.game(board=('double',))
        snapshot = g.snapshot()
        snapshot['schema_version'] = 7
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.registry)
        snapshot = g.snapshot()
        entity_id = g.state.players[1].board[0]
        snapshot['state']['entities'][str(entity_id)]['abilities'][0]['health_rule']['unknown'] = 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
