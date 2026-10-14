"""Costs and resource accounts verified through public, transactional actions."""
from hs_sim.engine.model import CostAuraSpec
from dataclasses import replace
import unittest

from hs_sim.engine import (CardDefinition, CardType, CostSpec, EndTurn, Game, IllegalAction,
                          Keyword, PaymentType, PlayCard, PlayerSetup, Registry, Resource,
                          ResolutionError, ResolutionLimitExceeded, Ruleset, Scenario, SnapshotError,
                          TargetSpec, TriggerSpec, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddCostModifier, Buff, ChangeControl, ChangeManaCrystals,
                                  CopyMinion, Damage, DamageBatch, Destroy, GainArmor, GainResource,
                                  GainTemporaryMana, GrantCostAura, GrantKeyword, ModifyCost, Overload,
                                  RefreshMana, RemoveEnchantment, ReplaceHero, ReturnToHand, SetManaCap,
                                  Silence, SpendResource, Transform, UnlockOverload)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


SPELLS = (CardType.SPELL,)
POWERS = (CardType.HERO_POWER,)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('resource-tests-v1')
        for card in (
            CardDefinition('hero', 'hero', CardType.HERO, health=30),
            CardDefinition('minion', 'minion', CardType.MINION, cost=3, attack=2, health=3),
            CardDefinition('reborn', 'reborn', CardType.MINION, attack=1, health=1, keywords=(Keyword.REBORN,)),
            CardDefinition('risen', 'risen', CardType.MINION, attack=1, health=1, corpse_value=0),
            CardDefinition('aura', 'aura', CardType.MINION, attack=1, health=3,
                           cost_auras=(CostAuraSpec(CostSpec(delta=-1, minimum=1, card_types=SPELLS)),)),
            CardDefinition('weapon', 'weapon', CardType.WEAPON, attack=1, durability=1),
        ):
            self.registry.register_card(card)
        self.script('paid', lambda c: [GainArmor(c.player_id, 1)], cost=3)
        self.script('free', lambda c: [], cost=0)
        self.registry.register_behavior('power', lambda c: [GainArmor(c.player_id, 2)])
        self.registry.register_card(CardDefinition('power', 'power', CardType.HERO_POWER, cost=2, on_use='power'))

    def script(self, name, fn, cost=0, **fields):
        self.registry.register_behavior(name, fn)
        self.registry.register_card(CardDefinition(name, name, CardType.SPELL, cost=cost, on_play=name, **fields))

    def game(self, hand=(), board=(), enemy_board=(), rules=None, **setup):
        defaults = dict(max_mana=10, mana=10, deck=('minion',) * 12)
        defaults.update(setup)
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, **defaults),
            PlayerSetup('hero', board=enemy_board, deck=('minion',) * 12, max_mana=10, mana=10),
        )), self.registry, ruleset=rules)

    def card(self, g, name, player=1):
        return next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)

    def cast(self, g, name, target=None):
        return g.apply(PlayCard(g.state.active_player, self.card(g, name, g.state.active_player), target))

    def round(self, g):
        g.apply(EndTurn(1))
        g.apply(EndTurn(2))

    def assert_replay(self, g):
        restored = replay(build_replay(g), self.registry)
        self.assertEqual(restored.snapshot(), g.snapshot())
        self.assertEqual(Game.from_snapshot(g.snapshot(), self.registry).snapshot(), g.snapshot())
        self.assertEqual(g.clone().snapshot(), g.snapshot())

    def test_local_cost_order_and_entity_cache(self):
        self.script('modify', lambda c: [ModifyCost(c.target_id, CostSpec(delta=-2)),
                                        ModifyCost(c.target_id, CostSpec(set_to=4)),
                                        ModifyCost(c.target_id, CostSpec(delta=1))],
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=SPELLS))
        g = self.game(('modify', 'paid'))
        target = self.card(g, 'paid')
        self.cast(g, 'modify', target)
        self.assertEqual(g.quote_cost(target).amount, 5)
        self.assertEqual(g.state.entities[target].cost, 5)
        self.cast(g, 'paid')
        self.assertEqual(g.state.players[1].mana, 5)
        self.assert_replay(g)

    def test_reduction_floor_never_increases_zero_cost(self):
        g = self.game(('free', 'paid'), board=('aura',))
        self.assertEqual(g.quote_cost(self.card(g, 'free')).amount, 0)
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 2)

    def test_local_payment_enchantment_roundtrip_and_removal(self):
        self.script('modify', lambda c: [ModifyCost(c.target_id, CostSpec(set_to=2, payment=PaymentType.ARMOR),
                                                    c.source_id)], targeting=TargetSpec(zones=(Zone.HAND,), kinds=SPELLS))
        self.script('remove', lambda c: [RemoveEnchantment(c.target_id, c.state.entities[c.target_id].enchantments[0].id)],
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=SPELLS))
        g = self.game(('modify', 'remove', 'paid'), armor=2)
        paid = self.card(g, 'paid')
        self.cast(g, 'modify', paid)
        self.assertEqual((g.quote_cost(paid).amount, g.quote_cost(paid).payment), (2, PaymentType.ARMOR))
        self.assert_replay(g)
        self.cast(g, 'remove', paid)
        self.assertEqual((g.quote_cost(paid).amount, g.quote_cost(paid).payment), (3, PaymentType.MANA))

    def test_temporary_local_cost_expires_before_next_turn(self):
        self.script('modify', lambda c: [ModifyCost(c.target_id, CostSpec(delta=-2), expires_turn=c.state.turn)],
                    targeting=TargetSpec(zones=(Zone.HAND,), kinds=SPELLS))
        g = self.game(('modify', 'paid'))
        paid = self.card(g, 'paid')
        self.cast(g, 'modify', paid)
        self.assertEqual(g.quote_cost(paid).amount, 1)
        self.round(g)
        self.assertEqual(g.quote_cost(paid).amount, 3)

    def test_copied_cost_aura_stacks_with_independent_attachment_ids(self):
        self.script('copy', lambda c: [CopyMinion(c.state.players[1].board[0], 1)])
        g = self.game(('copy', 'paid'), board=('aura',))
        self.cast(g, 'copy')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 1)
        ids = [a.id for i in g.state.players[1].board for a in g.state.entities[i].abilities if a.kind == 'cost_aura']
        self.assertEqual(len(set(ids)), 2)
        self.assert_replay(g)

    def test_weapon_cost_aura_stops_on_destruction(self):
        self.registry.register_card(CardDefinition('cost_weapon', 'cost weapon', CardType.WEAPON, attack=1, durability=1,
                                                   cost_auras=(CostAuraSpec(CostSpec(delta=-1, card_types=SPELLS)),)))
        self.script('kill', lambda c: [Destroy(c.state.players[1].weapon_id)])
        g = self.game(('kill', 'paid'), weapon_card_id='cost_weapon')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 2)
        self.cast(g, 'kill')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)

    def test_quote_is_immutable_and_has_no_side_effects(self):
        from dataclasses import FrozenInstanceError
        g = self.game(('paid',), board=('aura',))
        before = g.snapshot()
        quote = g.quote_cost(self.card(g, 'paid'))
        with self.assertRaises(FrozenInstanceError):
            quote.amount = 0
        self.assertEqual(g.snapshot(), before)

    def test_impossible_scenario_mana_accounts_rejected(self):
        with self.assertRaisesRegex(ValueError, 'mana'):
            self.game(max_mana=0, mana=0, temporary_mana=2)

    def test_aura_floor_and_stacking(self):
        g = self.game(('paid',), board=('aura',) * 3)
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 1)

    def test_player_modifier_consumes_only_matching_type(self):
        self.script('prep', lambda c: [AddCostModifier(1, CostSpec(delta=-2, card_types=SPELLS), 1)])
        g = self.game(('prep', 'minion', 'paid'))
        self.cast(g, 'prep')
        self.cast(g, 'minion')
        self.assertEqual(len(g.state.players[1].cost_modifiers), 1)
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 1)
        self.cast(g, 'paid')
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.state.players[1].mana, 6)
        self.assert_replay(g)

    def test_free_matching_card_consumes_discount(self):
        self.script('prep', lambda c: [AddCostModifier(1, CostSpec(delta=-2, card_types=SPELLS), 1)])
        g = self.game(('prep', 'free', 'paid'))
        self.cast(g, 'prep')
        self.cast(g, 'free')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)

    def test_zero_mana_enumeration_uses_quote(self):
        self.script('prep', lambda c: [AddCostModifier(1, CostSpec(set_to=0, card_types=SPELLS), 1)])
        g = self.game(('prep', 'paid'), mana=0)
        paid = self.card(g, 'paid')
        self.assertNotIn(PlayCard(1, paid), g.legal_actions())
        self.cast(g, 'prep')
        self.assertIn(PlayCard(1, paid), g.legal_actions())
        self.cast(g, 'paid')
        self.assertEqual(g.state.players[1].mana, 0)

    def test_failed_action_preserves_modifier_and_accounts(self):
        self.script('prep', lambda c: [AddCostModifier(1, CostSpec(delta=-1, card_types=SPELLS), 2)])
        g = self.game(('prep', 'paid'), mana=1)
        self.cast(g, 'prep')
        before = g.snapshot()
        with self.assertRaises(IllegalAction):
            self.cast(g, 'paid')
        self.assertEqual(g.snapshot(), before)

    def test_modifier_counts_and_expiration(self):
        self.script('prep', lambda c: [AddCostModifier(1, CostSpec(delta=-1, card_types=SPELLS), 2,
                                                       c.source_id, c.state.turn)])
        g = self.game(('prep', 'paid', 'paid'))
        self.cast(g, 'prep')
        self.cast(g, 'paid')
        self.assertEqual(g.state.players[1].cost_modifiers[0].uses_remaining, 1)
        self.round(g)
        self.assertFalse(g.state.players[1].cost_modifiers)
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)

    def test_global_modifier_acquisition_order_after_local(self):
        self.script('set', lambda c: [AddCostModifier(1, CostSpec(set_to=5, card_types=SPELLS))])
        self.script('grant', lambda c: [GrantCostAura(c.state.players[1].board[0], CostAuraSpec(CostSpec(delta=-2, card_types=SPELLS)))])
        g = self.game(('set', 'grant', 'paid'), board=('aura',))
        self.cast(g, 'set')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 5)
        self.cast(g, 'grant')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)
        self.assert_replay(g)

    def test_silence_removes_printed_and_granted_cost_auras(self):
        self.script('silence', lambda c: [Silence(c.state.players[1].board[0])])
        g = self.game(('silence', 'paid'), board=('aura',))
        self.cast(g, 'silence')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)

    def test_control_moves_cost_aura_to_new_controller(self):
        self.script('take', lambda c: [ChangeControl(c.state.players[2].board[0], 1)])
        g = self.game(('take', 'paid'), enemy_board=('aura',))
        self.cast(g, 'take')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 2)

    def test_dead_cost_source_stops_modifying_prices(self):
        self.script('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        g = self.game(('kill', 'paid'), board=('aura',))
        self.cast(g, 'kill')
        self.assertEqual(g.quote_cost(self.card(g, 'paid')).amount, 3)

    def test_hero_power_uses_same_quote_and_payment(self):
        self.script('discount', lambda c: [AddCostModifier(1, CostSpec(delta=-1, card_types=POWERS), 1)])
        g = self.game(('discount',), hero_power_card_id='power', mana=1)
        power = g.state.players[1].hero_power_id
        self.assertNotIn(UseHeroPower(1, power), g.legal_actions())
        self.cast(g, 'discount')
        self.assertEqual(g.quote_cost(power).amount, 1)
        self.assertIn(UseHeroPower(1, power), g.legal_actions())
        g.apply(UseHeroPower(1, power))
        self.assertEqual(g.state.players[1].mana, 0)
        self.assert_replay(g)

    def payment_setup(self, payment, **setup):
        self.script('conversion', lambda c: [AddCostModifier(1, CostSpec(card_types=SPELLS, payment=payment), 1)])
        g = self.game(('conversion', 'paid'), **setup)
        self.cast(g, 'conversion')
        return g

    def test_health_payment_uses_armor_and_bypasses_immunity_shield(self):
        self.script('protect', lambda c: [GrantKeyword(c.state.players[1].hero_id, Keyword.IMMUNE),
                                         GrantKeyword(c.state.players[1].hero_id, Keyword.DIVINE_SHIELD),
                                         AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH), 1)])
        g = self.game(('protect', 'paid'), armor=2, mana=0)
        self.cast(g, 'protect')
        events = self.cast(g, 'paid').events
        hero = g.state.entities[g.state.players[1].hero_id]
        self.assertEqual((hero.health, hero.armor), (29, 1))  # paid also grants 1 armor
        self.assertIn(Keyword.DIVINE_SHIELD, hero.keywords)
        self.assertFalse(any(e.kind == 'damage' for e in events))
        self.assertTrue(any(e.kind == 'health_spent' and e.amount == 3 for e in events))
        self.assert_replay(g)

    def test_health_cannot_spend_last_effective_health(self):
        self.script('hurt', lambda c: [Damage(c.state.players[1].hero_id, 27),
                                      AddCostModifier(1, CostSpec(payment=PaymentType.HEALTH), 1)])
        g = self.game(('hurt', 'paid'), mana=0)
        self.cast(g, 'hurt')
        with self.assertRaisesRegex(IllegalAction, 'health'):
            self.cast(g, 'paid')

    def test_armor_payment_exact_balance(self):
        g = self.payment_setup(PaymentType.ARMOR, armor=3, mana=0)
        self.cast(g, 'paid')
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)
        self.assertEqual(g.state.players[1].mana, 0)

    def test_armor_payment_cannot_substitute_health(self):
        g = self.payment_setup(PaymentType.ARMOR, armor=2, mana=10)
        with self.assertRaisesRegex(IllegalAction, 'armor'):
            self.cast(g, 'paid')

    def test_corpse_payment_uses_bank(self):
        g = self.payment_setup(PaymentType.CORPSES, corpses=3, mana=0)
        self.cast(g, 'paid')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0)

    def test_corpse_payment_cannot_substitute_mana(self):
        g = self.payment_setup(PaymentType.CORPSES, corpses=2)
        with self.assertRaisesRegex(IllegalAction, 'corpses'):
            self.cast(g, 'paid')

    def test_temporary_mana_can_exceed_owned_crystals_and_is_spent_first(self):
        self.script('coin', lambda c: [GainTemporaryMana(1, 1)])
        g = self.game(('coin', 'paid'), max_mana=2, mana=2)
        self.cast(g, 'coin')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].max_mana), (3, 2))
        self.cast(g, 'paid')
        p = g.state.players[1]
        self.assertEqual((p.mana, p.mana_spent, p.temporary_mana), (0, 2, 0))
        self.assert_replay(g)

    def test_unused_temporary_mana_expires_without_changing_owned_crystals(self):
        self.script('coin', lambda c: [GainTemporaryMana(1, 2)])
        g = self.game(('coin',), max_mana=2, mana=1)
        self.cast(g, 'coin')
        g.apply(EndTurn(1))
        p = g.state.players[1]
        self.assertEqual((p.mana, p.max_mana, p.temporary_mana), (1, 2, 0))

    def test_temporary_mana_respects_growth_cap(self):
        self.script('coin', lambda c: [GainTemporaryMana(1, 5)])
        g = self.game(('coin',), mana=9)
        self.cast(g, 'coin')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].temporary_mana), (14, 5))
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana_cap), (10, 10))

    def test_refresh_does_not_recreate_spent_temporary_mana(self):
        self.script('refresh', lambda c: [RefreshMana(1, 10)])
        g = self.game(('paid', 'refresh'), max_mana=2, temporary_mana=1, mana=3)
        self.cast(g, 'paid')
        self.cast(g, 'refresh')
        p = g.state.players[1]
        self.assertEqual((p.mana, p.max_mana, p.temporary_mana), (2, 2, 0))

    def test_full_and_empty_crystal_growth_are_distinct(self):
        self.script('grow', lambda c: [ChangeManaCrystals(1, 2), ChangeManaCrystals(1, 1, filled=True)])
        g = self.game(('grow',), max_mana=2, mana=1)
        self.cast(g, 'grow')
        p = g.state.players[1]
        self.assertEqual((p.max_mana, p.mana, p.mana_spent), (5, 2, 3))
        self.round(g)
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (6, 6))

    def test_crystal_removal_preserves_available_until_clamped(self):
        self.script('shrink', lambda c: [ChangeManaCrystals(1, -2)])
        g = self.game(('shrink', 'shrink'), max_mana=5, mana=2)
        self.cast(g, 'shrink')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (3, 2))
        self.cast(g, 'shrink')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (1, 1))

    def test_mana_cap_expansion_and_shrink(self):
        self.script('expand', lambda c: [SetManaCap(1, 20), ChangeManaCrystals(1, 10, filled=True)])
        self.script('shrink', lambda c: [SetManaCap(1, 3)])
        g = self.game(('expand', 'shrink'))
        self.cast(g, 'expand')
        self.assertEqual((g.state.players[1].max_mana, g.state.players[1].mana), (20, 20))
        self.cast(g, 'shrink')
        self.assertEqual((g.state.players[1].mana_cap, g.state.players[1].max_mana, g.state.players[1].mana), (3, 3, 3))
        self.assert_replay(g)

    def test_overload_locks_only_next_own_turn_and_then_clears(self):
        self.script('overload', lambda c: [Overload(1, 2)])
        g = self.game(('overload',), max_mana=3, mana=3)
        self.cast(g, 'overload')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (3, 2))
        g.apply(EndTurn(1))
        self.assertEqual(g.state.players[1].overload_owed, 2)
        g.apply(EndTurn(2))
        p = g.state.players[1]
        self.assertEqual((p.mana, p.max_mana, p.overload_locked, p.overload_owed), (2, 4, 2, 0))
        self.round(g)
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_locked), (5, 0))
        self.assert_replay(g)

    def test_refresh_does_not_unlock_overload(self):
        self.script('refresh', lambda c: [RefreshMana(1, 10)])
        g = self.game(('refresh',), max_mana=5, mana=1, overload_locked=2)
        self.cast(g, 'refresh')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_locked), (3, 2))

    def test_excess_overload_is_not_discarded(self):
        self.script('coin', lambda c: [GainTemporaryMana(1, 1)])
        g = self.game(('coin', 'coin'), max_mana=10, mana=0, overload_locked=11)
        self.cast(g, 'coin')
        self.assertEqual(g.state.players[1].mana, 0)
        self.cast(g, 'coin')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_locked), (1, 11))
        self.assert_replay(g)

    def test_unlock_clears_pending_and_locked_without_refreshing_spent(self):
        self.script('unlock', lambda c: [UnlockOverload(1)])
        g = self.game(('unlock',), max_mana=5, mana=1, overload_locked=2, overload_owed=3)
        self.cast(g, 'unlock')
        p = g.state.players[1]
        self.assertEqual((p.mana, p.mana_spent, p.overload_locked, p.overload_owed), (3, 2, 0, 0))

    def test_unlock_can_preserve_pending(self):
        self.script('unlock', lambda c: [UnlockOverload(1, clear_pending=False)])
        g = self.game(('unlock',), max_mana=5, mana=3, overload_locked=2, overload_owed=3)
        self.cast(g, 'unlock')
        self.assertEqual((g.state.players[1].mana, g.state.players[1].overload_owed), (5, 3))

    def test_all_deaths_in_batch_are_credited_before_deathrattles(self):
        self.registry.register_behavior('rattle', lambda c: [GainArmor(c.player_id, c.state.players[c.player_id].resources[Resource.CORPSES])])
        self.registry.register_card(CardDefinition('rattle', 'rattle', CardType.MINION, health=1, deathrattle='rattle'))
        self.script('aoe', lambda c: [DamageBatch(tuple(Damage(i, 10) for i in c.state.players[1].board))])
        g = self.game(('aoe',), board=('rattle', 'minion'))
        self.cast(g, 'aoe')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 2)
        self.assertEqual([d.corpse_value for d in g.state.death_history], [1, 1])

    def test_reborn_produces_a_corpse_for_each_death(self):
        self.script('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        g = self.game(('kill', 'kill'), board=('reborn',))
        self.cast(g, 'kill')
        self.cast(g, 'kill')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 2)

    def test_no_corpse_trait_survives_silence_and_copy(self):
        self.script('prepare', lambda c: [Silence(c.state.players[1].board[0]), CopyMinion(c.state.players[1].board[0], 1)])
        self.script('aoe', lambda c: [DamageBatch(tuple(Damage(i, 10) for i in c.state.players[1].board))])
        g = self.game(('prepare', 'aoe'), board=('risen',))
        self.cast(g, 'prepare')
        self.cast(g, 'aoe')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0)
        self.assert_replay(g)

    def test_transform_resets_corpse_trait(self):
        self.script('transform', lambda c: [Transform(c.state.players[1].board[0], 'risen')])
        self.script('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        g = self.game(('transform', 'kill'), board=('minion',))
        self.cast(g, 'transform')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0)
        self.cast(g, 'kill')
        self.assertEqual(g.state.death_history[0].corpse_value, 0)

    def test_corpse_belongs_to_controller_at_death(self):
        self.script('take', lambda c: [ChangeControl(c.state.players[2].board[0], 1)])
        self.script('kill', lambda c: [Destroy(c.state.players[1].board[0])])
        g = self.game(('take', 'kill'), enemy_board=('minion',))
        self.cast(g, 'take')
        self.cast(g, 'kill')
        self.assertEqual([g.state.players[i].resources[Resource.CORPSES] for i in (1, 2)], [1, 0])

    def test_bounce_weapon_destruction_and_hero_replacement_do_not_give_corpses(self):
        self.script('change', lambda c: [ReturnToHand(c.state.players[1].board[0]),
                                        Destroy(c.state.players[1].weapon_id), ReplaceHero(1, 'hero')])
        g = self.game(('change',), board=('minion',), weapon_card_id='weapon', corpses=4)
        self.cast(g, 'change')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 4)
        self.assertEqual(g.state.death_history[0].corpse_value, 0)

    def test_optional_resource_branch_checks_at_execution(self):
        self.script('spend', lambda c: [GainResource(1, Resource.CORPSES, 3),
                                       SpendResource(1, Resource.CORPSES, 3, on_success=(GainArmor(1, 7),))])
        g = self.game(('spend',))
        self.cast(g, 'spend')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 0)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 7)

    def test_optional_payment_does_not_partially_spend(self):
        self.script('spend', lambda c: [SpendResource(1, Resource.CORPSES, 3,
                                                    on_success=(GainArmor(1, 9),), on_failure=(GainArmor(1, 1),))])
        g = self.game(('spend',), corpses=2)
        self.cast(g, 'spend')
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES], 2)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 1)

    def test_required_payment_failure_rolls_back_entire_action(self):
        self.script('fail', lambda c: [GainTemporaryMana(1, 2), GainResource(1, Resource.CORPSES, 1),
                                      SpendResource(1, Resource.CORPSES, 3, required=True)], cost=1)
        g = self.game(('fail',), mana=5)
        before = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.cast(g, 'fail')
        self.assertEqual(g.snapshot(), before)

    def test_engineering_turn_budget_is_rollback_not_draw(self):
        g = self.game(rules=Ruleset(max_turns=1))
        before = g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            g.apply(EndTurn(1))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(g.state.status, 'playing')

    def test_explicit_gameplay_draw_is_separate_from_engineering_budget(self):
        g = self.game(rules=Ruleset(max_turns=1, draw_after_turn=1))
        result = g.apply(EndTurn(1))
        self.assertEqual(g.state.status, 'draw')
        self.assertTrue(any(dict(e.data).get('reason') == 'configured_draw_turn' for e in result.events))
        self.assert_replay(g)

    def test_strict_resource_cost_validation(self):
        for build in (lambda: CostSpec(delta=True), lambda: CostSpec(payment='health'),
                      lambda: CostSpec(set_to=1, delta=2), lambda: CostSpec(card_types=()),
                      lambda: CostSpec(card_types=('hero',)),
                      lambda: GainResource(1, 'runes', 1), lambda: SpendResource(1, Resource.CORPSES, -1),
                      lambda: SpendResource(1, Resource.CORPSES, 1, on_success=[]),
                      lambda: AddCostModifier(1, CostSpec(), uses_remaining=0),
                      lambda: SetManaCap(1, True), lambda: Ruleset(draw_after_turn=True)):
            with self.subTest(build=build), self.assertRaises(ValueError):
                build()

    def test_old_snapshot_six_is_rejected(self):
        g = self.game()
        snapshot = g.snapshot()
        snapshot['schema_version'] = 6
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.registry)

    def test_snapshot_rejects_unknown_resource_and_stale_mana_even_with_new_digest(self):
        g = self.game()
        for key, value in (('mana', 9), ('temporary_mana', True), ('resources', {'runes': 3}),
                           ('cost_modifiers', [{'id': 1}])):
            snapshot = g.snapshot()
            snapshot['state']['players']['1'][key] = value
            # Digest validity must not conceal structural/derived corruption.
            payload = g._hash_payload()
            payload['state'] = snapshot['state']
            snapshot['state_hash'] = canonical_hash(payload)
            with self.subTest(key=key), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
