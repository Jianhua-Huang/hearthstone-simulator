"""Mechanism integration tests through public commands and synthetic card rules.

These check the documented prototype policy, not compatibility with an official
Hearthstone release.  No test writes engine state or invokes Resolution directly.
"""

import unittest

from hs_sim.engine.actions import Attack, EndTurn, PlayCard
from hs_sim.engine.effects import Damage, DamageBatch, Destroy, Draw, GainArmor, Summon
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.game import Game, PlayerSetup, Scenario
from hs_sim.engine.model import AuraSpec, CardDefinition, CardType, Keyword, TriggerSpec, Zone
from hs_sim.engine.registry import Registry


def make_registry():
    registry = Registry("mechanics-tests-v1")
    registry.register_card(CardDefinition("hero", "Hero", CardType.HERO, health=30))
    for card_id, attack, health, keywords in (
        ("soldier", 2, 2, ()),
        ("shield", 2, 2, (Keyword.DIVINE_SHIELD,)),
        ("immune", 2, 2, (Keyword.IMMUNE,)),
        ("taunt", 0, 5, (Keyword.TAUNT,)),
        ("charge", 2, 4, (Keyword.CHARGE,)),
        ("rush", 2, 4, (Keyword.RUSH,)),
        ("windfury", 3, 8, (Keyword.WINDFURY, Keyword.CHARGE)),
        ("token", 1, 1, ()),
    ):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
                                              attack=attack, health=health, keywords=keywords))
    registry.register_card(CardDefinition("aura", "Aura", CardType.MINION,
                                          attack=1, health=3, auras=(AuraSpec(1),)))
    return registry


class MechanicsTests(unittest.TestCase):
    def setUp(self):
        self.registry = make_registry()

    def spell(self, card_id, behavior, *, targeted=False):
        self.registry.register_behavior(card_id, behavior)
        self.registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
                                                  on_play=card_id, requires_target=targeted))

    def game(self, *, hand=(), board=(), deck=(), opponent_hand=(), opponent_board=(),
             opponent_deck=(), opponent_armor=0, active_player=1):
        return Game.from_scenario(
            Scenario((PlayerSetup("hero", hand=hand, board=board, deck=deck,
                                  max_mana=10, mana=10),
                      PlayerSetup("hero", hand=opponent_hand, board=opponent_board,
                                  deck=opponent_deck, armor=opponent_armor)),
                     active_player=active_player),
            self.registry,
        )

    def play(self, game, card_id, target_id=None, player_id=1, position=None):
        state = game.state
        entity_id = next(i for i in state.players[player_id].hand if state.entities[i].card_id == card_id)
        return game.apply(PlayCard(player_id, entity_id, target_id, position))

    def test_attack_damage_is_simultaneous_and_both_minions_die(self):
        game = self.game(board=("soldier",), opponent_board=("soldier",))
        before = game.state
        attacker, defender = before.players[1].board[0], before.players[2].board[0]
        result = game.apply(Attack(1, attacker, defender))
        after = game.state
        self.assertEqual(after.players[1].board, [])
        self.assertEqual(after.players[2].board, [])
        self.assertEqual(after.entities[attacker].damage, 2)
        self.assertEqual(after.entities[defender].damage, 2)
        damage = [event for event in result.events if event.kind == "damage_dealt"]
        deaths = [event for event in result.events if event.kind == "minion_died"]
        self.assertEqual({(event.source_id, event.target_id) for event in damage},
                         {(attacker, defender), (defender, attacker)})
        self.assertLess(max(event.sequence for event in damage), min(event.sequence for event in deaths))

    def test_zero_damage_preserves_shield_then_positive_damage_consumes_it_once(self):
        self.spell("zero", lambda ctx: (Damage(ctx.target_id, 0, ctx.source_id),), targeted=True)
        self.spell("ping", lambda ctx: (Damage(ctx.target_id, 1, ctx.source_id),), targeted=True)
        game = self.game(hand=("zero", "ping", "ping"), opponent_board=("shield",))
        target = game.state.players[2].board[0]
        self.play(game, "zero", target)
        self.assertIn(Keyword.DIVINE_SHIELD, game.state.entities[target].keywords)
        self.assertEqual(game.state.entities[target].health, 2)
        result = self.play(game, "ping", target)
        self.assertNotIn(Keyword.DIVINE_SHIELD, game.state.entities[target].keywords)
        self.assertEqual(game.state.entities[target].health, 2)
        self.assertEqual(sum(e.kind == "shield_lost" for e in result.events), 1)
        self.play(game, "ping", target)
        self.assertEqual(game.state.entities[target].health, 1)

    def test_area_damage_respects_immunity_and_armor_absorbs_before_health(self):
        def blast(ctx):
            opponent = ctx.state.players[2]
            return (DamageBatch(tuple(Damage(i, 4, ctx.source_id)
                                      for i in (opponent.hero_id, *opponent.board))),)

        self.spell("blast", blast)
        game = self.game(hand=("blast",), opponent_board=("immune",), opponent_armor=3)
        result = self.play(game, "blast")
        state = game.state
        hero = state.entities[state.players[2].hero_id]
        immune = state.entities[state.players[2].board[0]]
        self.assertEqual((hero.armor, hero.health), (0, 29))
        self.assertEqual(immune.health, 2)
        damage = next(e for e in result.events if e.kind == "damage_dealt")
        self.assertEqual(dict(damage.data)['armor_absorbed'], 3)
        self.assertEqual(dict(damage.data)['health_damage'], 1)
        self.assertTrue(any(e.kind == "damage_prevented" and dict(e.data).get("reason") == "immune"
                            for e in result.events))

    def test_taunt_blocks_other_targets_and_immune_taunt_does_not(self):
        self.registry.register_card(CardDefinition("immune_taunt", "Immune taunt", CardType.MINION,
                                                  attack=0, health=5,
                                                  keywords=(Keyword.IMMUNE, Keyword.TAUNT)))
        game = self.game(board=("soldier",), opponent_board=("taunt", "soldier"))
        state = game.state
        attacker = state.players[1].board[0]
        for defender in (state.players[2].hero_id, state.players[2].board[1]):
            with self.subTest(defender=defender), self.assertRaises(IllegalAction):
                game.apply(Attack(1, attacker, defender))
        game.apply(Attack(1, attacker, state.players[2].board[0]))
        second = self.game(board=("soldier",), opponent_board=("immune_taunt",))
        state = second.state
        second.apply(Attack(1, state.players[1].board[0], state.players[2].hero_id))
        self.assertEqual(second.state.entities[state.players[2].hero_id].health, 28)

    def test_new_ordinary_minion_waits_until_its_next_turn(self):
        game = self.game(hand=("soldier",))
        self.play(game, "soldier")
        state = game.state
        attacker, defender = state.players[1].board[0], state.players[2].hero_id
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, attacker, defender))
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        game.apply(Attack(1, attacker, defender))
        self.assertEqual(game.state.entities[defender].health, 27)  # 1 fatigue + 2 attack.

    def test_charge_can_attack_a_hero_immediately(self):
        game = self.game(hand=("charge",))
        self.play(game, "charge")
        state = game.state
        game.apply(Attack(1, state.players[1].board[0], state.players[2].hero_id))
        self.assertEqual(game.state.entities[state.players[2].hero_id].health, 28)

    def test_rush_can_attack_minions_but_not_heroes_on_summoning_turn(self):
        game = self.game(hand=("rush",), opponent_board=("soldier",))
        self.play(game, "rush")
        state = game.state
        attacker = state.players[1].board[0]
        with self.assertRaises(IllegalAction):
            game.apply(Attack(1, attacker, state.players[2].hero_id))
        game.apply(Attack(1, attacker, state.players[2].board[0]))
        self.assertEqual(game.state.players[2].board, [])
        self.assertEqual(game.state.entities[attacker].health, 2)

    def test_windfury_allows_two_attacks_and_resets_next_turn(self):
        game = self.game(hand=("windfury",))
        self.play(game, "windfury")
        state = game.state
        attack = Attack(1, state.players[1].board[0], state.players[2].hero_id)
        game.apply(attack)
        game.apply(attack)
        with self.assertRaises(IllegalAction):
            game.apply(attack)
        self.assertEqual(game.state.entities[attack.defender_id].health, 24)
        game.apply(EndTurn(1))
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[attack.attacker_id].attacks_this_turn, 0)
        game.apply(attack)
        self.assertEqual(game.state.entities[attack.attacker_id].attacks_this_turn, 1)

    def test_batch_removes_every_dead_minion_before_any_deathrattle_summon(self):
        self.registry.register_behavior("hatch", lambda ctx: (Summon(ctx.player_id, "token"),))
        self.registry.register_card(CardDefinition("egg", "Egg", CardType.MINION,
                                                  health=1, deathrattle="hatch"))
        self.spell("wipe", lambda ctx: (DamageBatch(tuple(Damage(i, 1, ctx.source_id)
                                                         for i in ctx.state.players[1].board)),))
        game = self.game(hand=("wipe",), board=("egg",) * 7)
        eggs = set(game.state.players[1].board)
        result = self.play(game, "wipe")
        state = game.state
        self.assertEqual(len(state.players[1].board), 7)
        self.assertEqual([state.entities[i].card_id for i in state.players[1].board], ["token"] * 7)
        self.assertTrue(all(state.entities[i].zone == Zone.GRAVEYARD for i in eggs))
        deaths = [e.sequence for e in result.events if e.kind == "minion_died"]
        summons = [e.sequence for e in result.events if e.kind == "minion_summoned"]
        self.assertEqual((len(deaths), len(summons)), (7, 7))
        self.assertLess(max(deaths), min(summons))

    def test_lethally_damaged_trigger_source_keeps_its_captured_reaction(self):
        def react(ctx):
            if ctx.event.target_id != ctx.source_id:
                return ()
            # The event snapshot predates removal from the board, even though
            # the current damage is already lethal when the event is emitted.
            amount = 1 if ctx.source.zone == Zone.BOARD and ctx.source.health == 0 else 100
            return (GainArmor(ctx.player_id, amount),)

        self.registry.register_behavior("react", react)
        self.registry.register_card(CardDefinition("watcher", "Watcher", CardType.MINION,
                                                  health=1, triggers=(TriggerSpec("damage_dealt", "react"),)))
        self.spell("kill", lambda ctx: (Damage(ctx.target_id, 1, ctx.source_id),), targeted=True)
        game = self.game(hand=("kill",), board=("watcher",))
        target = game.state.players[1].board[0]
        result = self.play(game, "kill", target)
        state = game.state
        self.assertEqual(state.entities[target].zone, Zone.GRAVEYARD)
        self.assertEqual(state.entities[state.players[1].hero_id].armor, 1)
        kinds = [e.kind for e in result.events]
        self.assertLess(kinds.index("minion_died"), kinds.index("armor_gained"))

    def test_prototype_trigger_order_is_active_player_then_entry_order(self):
        self.registry.register_behavior("observe", lambda ctx: (GainArmor(ctx.player_id, ctx.source.attack),))
        for card_id, attack in (("observer_a", 1), ("observer_b", 2)):
            self.registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
                                                      attack=attack, health=2,
                                                      triggers=(TriggerSpec("damage_dealt", "observe"),)))
        self.spell("ping", lambda ctx: (Damage(ctx.state.players[1].hero_id, 1, ctx.source_id),))
        game = self.game(board=("observer_a", "observer_b"),
                         opponent_board=("observer_b", "observer_a"),
                         opponent_hand=("ping",), active_player=2)
        result = self.play(game, "ping", player_id=2)
        order = [(e.player_id, e.amount) for e in result.events if e.kind == "armor_gained"]
        self.assertEqual(order, [(2, 2), (2, 1), (1, 1), (1, 2)])

    def test_prototype_reactions_precede_deathrattles_and_caller_continuation(self):
        self.registry.register_behavior("react", lambda ctx: (GainArmor(ctx.player_id, 1),))
        self.registry.register_behavior("rattle", lambda ctx: (GainArmor(ctx.player_id, 10),))
        self.registry.register_card(CardDefinition("watcher", "Watcher", CardType.MINION,
                                                  health=1, deathrattle="rattle",
                                                  triggers=(TriggerSpec("damage_dealt", "react"),)))
        self.spell("sequence", lambda ctx: (Damage(ctx.target_id, 1, ctx.source_id),
                                             GainArmor(ctx.player_id, 100)), targeted=True)
        game = self.game(hand=("sequence",), board=("watcher",))
        result = self.play(game, "sequence", game.state.players[1].board[0])
        self.assertEqual([e.amount for e in result.events if e.kind == "armor_gained"], [1, 10, 100])

    def test_attack_aura_is_derived_idempotently_and_removed_with_its_source(self):
        self.spell("zero", lambda ctx: (Damage(ctx.state.players[2].hero_id, 0),))
        self.spell("destroy", lambda ctx: (Destroy(ctx.target_id),), targeted=True)
        game = self.game(hand=("zero", "zero", "destroy"), board=("aura", "soldier"))
        aura, soldier = game.state.players[1].board
        self.assertEqual(game.state.entities[aura].attack, 1)
        self.assertEqual(game.state.entities[soldier].attack, 3)
        for _ in range(2):
            self.play(game, "zero")
            self.assertEqual(game.state.entities[soldier].attack, 3)
            self.assertEqual(game.state.entities[soldier].attack_bonus, 0)
        self.play(game, "destroy", aura)
        self.assertEqual(game.state.entities[aura].zone, Zone.GRAVEYARD)
        self.assertEqual(game.state.entities[soldier].attack, 2)
        self.assertEqual(game.state.entities[soldier].aura_attack, 0)

    def test_drawing_preserves_order_burns_overflow_and_increments_fatigue(self):
        self.spell("draw_five", lambda ctx: (Draw(ctx.player_id, 5),))
        game = self.game(hand=("draw_five",) + ("soldier",) * 8,
                         deck=("charge", "rush", "shield"))
        result = self.play(game, "draw_five")
        state = game.state
        player = state.players[1]
        self.assertEqual(player.deck, [])
        self.assertEqual(len(player.hand), 10)
        self.assertEqual([state.entities[i].card_id for i in player.hand[-2:]], ["charge", "rush"])
        self.assertEqual([state.entities[i].card_id for i in player.graveyard], ["draw_five", "shield"])
        self.assertEqual(player.fatigue, 2)
        self.assertEqual(state.entities[player.hero_id].health, 27)
        self.assertEqual([e.amount for e in result.events if e.kind == "fatigue"], [1, 2])
        self.assertEqual(sum(e.kind == "card_burned" for e in result.events), 1)
        self.assertFalse(any(e.kind == "minion_died" for e in result.events))

    def test_end_turn_changes_player_refills_mana_and_draws(self):
        game = Game.from_scenario(Scenario((PlayerSetup("hero"),
                                            PlayerSetup("hero", deck=("charge", "rush"),
                                                        max_mana=3, mana=0))), self.registry)
        result = game.apply(EndTurn(1))
        state = game.state
        player = state.players[2]
        self.assertEqual((state.active_player, state.turn), (2, 2))
        self.assertEqual((player.max_mana, player.mana), (4, 4))
        self.assertEqual([state.entities[i].card_id for i in player.hand], ["charge"])
        self.assertEqual([state.entities[i].card_id for i in player.deck], ["rush"])
        self.assertEqual([e.kind for e in result.events], ["turn_ended", "turn_started", "card_drawn"])

    def test_hero_death_finishes_game_and_cancels_later_effects(self):
        self.spell("lethal", lambda ctx: (Damage(ctx.state.players[2].hero_id, 30),
                                           Damage(ctx.state.players[1].hero_id, 30)))
        game = self.game(hand=("lethal",))
        self.play(game, "lethal")
        state = game.state
        self.assertEqual((state.status, state.winner), ("finished", 1))
        self.assertEqual(state.entities[state.players[1].hero_id].health, 30)
        self.assertEqual(game.legal_actions(), ())
        with self.assertRaises(IllegalAction):
            game.apply(EndTurn(1))

    def test_both_heroes_dying_in_one_batch_is_a_draw(self):
        self.spell("mutual", lambda ctx: (DamageBatch(tuple(Damage(p.hero_id, 30)
                                                           for p in ctx.state.players.values())),))
        game = self.game(hand=("mutual",))
        result = self.play(game, "mutual")
        state = game.state
        self.assertEqual((state.status, state.winner), ("draw", None))
        self.assertEqual([state.entities[p.hero_id].health for p in state.players.values()], [0, 0])
        self.assertEqual(game.legal_actions(), ())
        self.assertEqual(sum(e.kind == "game_ended" for e in result.events), 1)


if __name__ == "__main__":
    unittest.main()
