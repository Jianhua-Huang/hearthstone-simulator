"""Dedicated action fees do not consume ordinary card discounts."""
import json
import unittest

from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, CostScope, CostSpec,
    Game, HandActionSpec, Keyword, LaunchStarship, PaymentType, PlayCard,
    PlayerSetup, Registry, Scenario, UseHandAction,
)
from hs_sim.engine.effects import AddCostModifier, Destroy
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction


def scope_registry():
    registry = Registry('fee-special-action-scopes-v1')
    metadata = CardMetadata(False, (CardClass.MAGE,), None)
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO,
        health=30, metadata=metadata))
    registry.register_card(CardDefinition('plain', 'Plain', CardType.MINION,
        attack=1, health=2, metadata=metadata))
    registry.register_card(CardDefinition('trade', 'Trade', CardType.SPELL,
        cost=7, metadata=metadata, hand_actions=(HandActionSpec('trade', 'trade', 1),)))
    registry.register_card(CardDefinition('forge', 'Forge', CardType.MINION,
        cost=3, attack=3, health=3, metadata=metadata,
        hand_actions=(HandActionSpec('forge', 'forge', 2, 'forged'),)))
    registry.register_card(CardDefinition('forged', 'Forged', CardType.MINION,
        cost=3, attack=6, health=5, metadata=metadata, keywords=(Keyword.RUSH,)))
    registry.register_card(CardDefinition('piece', 'Piece', CardType.MINION,
        attack=2, health=3, metadata=metadata, keywords=(Keyword.STARSHIP_PIECE,)))
    registry.register_card(CardDefinition('ship', 'Ship', CardType.MINION,
        cost=5, metadata=metadata, starship_for=(CardClass.NEUTRAL,)))

    def setup(context):
        effects = [
            AddCostModifier(context.player_id,
                CostSpec(delta=-9, payment=PaymentType.HEALTH, card_ids=('trade', 'forge')),
                uses_remaining=2, source_id=context.source_id, scope=CostScope.CARD),
            AddCostModifier(context.player_id, CostSpec(delta=-2),
                uses_remaining=2, source_id=context.source_id, scope=CostScope.STARSHIP_LAUNCH),
        ]
        pieces = [i for i in context.state.players[context.player_id].board
                  if context.state.entities[i].card_id == 'piece']
        return [*effects, *(Destroy(i, source_id=context.source_id) for i in pieces)]

    registry.register_behavior('setup', setup)
    registry.register_card(CardDefinition('setup', 'Setup', CardType.SPELL,
        on_play='setup', metadata=metadata))
    return registry


class CostSpecialScopeTests(unittest.TestCase):
    def game(self, card_id=None, *, starship=False):
        hand = ('setup',) + (() if card_id is None else (card_id,))
        game = Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, deck=('plain',),
                board=('piece',) if starship else (), mana=10, max_mana=10),
            PlayerSetup('hero')), seed=157), scope_registry())
        source = next(i for i in game.state.players[1].hand
                      if game.state.entities[i].card_id == 'setup')
        game.apply(PlayCard(1, source))
        self.assertTrue(game.state.play_history[-1].spell_acceptance_closed)
        return game

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        for other in (Game.from_snapshot(snapshot, scope_registry()),
                      game.clone(), replay(build_replay(game), scope_registry())):
            self.assertEqual(other.snapshot(), snapshot)
            for player_id in (1, 2):
                self.assertEqual(other.for_player(player_id).observe(), game.for_player(player_id).observe())

    def hand_action(self, card_id, action_id, amount):
        game = self.game(card_id)
        source = next(i for i in game.state.players[1].hand
                      if game.state.entities[i].card_id == card_id)
        self.assertEqual((game.quote_cost(source).amount, game.quote_cost(source).payment),
                         (0, PaymentType.HEALTH))
        original_modifiers = tuple(game.state.players[1].cost_modifiers)
        game.apply(UseHandAction(1, source, action_id))
        state = game.state
        receipt = state.cost_use_history[-1]
        self.assertEqual((receipt.origin, receipt.source_id, receipt.source_card_id,
                          receipt.amount, receipt.payment),
                         ('payment', source, card_id, amount, PaymentType.MANA))
        self.assertEqual((receipt.modifier_ids, receipt.player_modifiers, receipt.consumable_ids), ((), (), ()))
        self.assertEqual(tuple(state.players[1].cost_modifiers), original_modifiers)
        self.assertEqual((state.players[1].mana, state.entities[state.players[1].hero_id].health), (10 - amount, 30))
        self.assertEqual(len(state.play_history), 1)
        self.assertEqual(len(state.cost_use_history), 2)
        self.portable(game)

    def test_trade_uses_dedicated_mana_fee_without_card_or_launch_modifier_consumption(self):
        self.hand_action('trade', 'trade', 1)

    def test_forge_uses_dedicated_mana_fee_and_preserves_original_quote_face_in_history(self):
        self.hand_action('forge', 'forge', 2)

    def test_paid_manual_launch_consumes_only_launch_scope_and_records_payment_origin(self):
        game = self.game(starship=True)
        ship = construction(game.state, 1)
        self.assertIsNotNone(ship)
        original_card = next(m for m in game.state.players[1].cost_modifiers if m.scope == CostScope.CARD)
        original_launch = next(m for m in game.state.players[1].cost_modifiers if m.scope == CostScope.STARSHIP_LAUNCH)
        game.apply(LaunchStarship(1, ship.id))
        state = game.state
        receipt = state.cost_use_history[-1]
        self.assertEqual((receipt.source_id, receipt.source_card_id, receipt.origin,
                          receipt.amount, receipt.payment), (ship.id, 'ship', 'payment', 3, PaymentType.MANA))
        self.assertEqual(receipt.modifier_ids, (original_launch.id,))
        self.assertEqual(receipt.player_modifiers, (original_launch,))
        self.assertEqual(receipt.consumable_ids, (original_launch.id,))
        current_card = next(m for m in state.players[1].cost_modifiers if m.scope == CostScope.CARD)
        current_launch = next(m for m in state.players[1].cost_modifiers if m.scope == CostScope.STARSHIP_LAUNCH)
        self.assertEqual(current_card, original_card)
        self.assertEqual((original_launch.uses_remaining, current_launch.uses_remaining), (2, 1))
        self.assertEqual((state.players[1].mana, state.entities[state.players[1].hero_id].health), (7, 30))
        self.assertEqual(len(state.play_history), 1)
        self.assertEqual(len(state.cost_use_history), 2)
        self.portable(game)


if __name__ == '__main__':
    unittest.main()
