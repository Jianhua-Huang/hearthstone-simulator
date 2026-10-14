"""Public opening regression: a free launch consumes cost uses at action zero."""
import json
import unittest

from hs_sim.engine import (
    CardClass, CardDefinition, CardMetadata, CardType, ChoicePurpose, CostSpec,
    DeckPolicy, DeckSpec, Game, Keyword, LaunchStarshipEffect, MatchSetup,
    OpeningHook, Rarity, Registry, SelectChoice,
)
from hs_sim.engine.effects import AddCostModifier, Destroy, InvokeBehavior, Summon
from hs_sim.engine.model import CostScope
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.starships import construction


def bootstrap_registry(finite):
    registry = Registry('cost-action-zero-' + ('finite' if finite else 'empty'))

    def noop(context):
        return []

    def bootstrap(context):
        effects = []
        if finite:
            effects.append(AddCostModifier(context.player_id, CostSpec(delta=-2), 2,
                source_id=context.source_id, scope=CostScope.STARSHIP_LAUNCH))
        return [*effects, Summon(context.player_id, 'piece'),
            InvokeBehavior('destroy-piece', context.source_id, context.player_id),
            InvokeBehavior('launch-built', context.source_id, context.player_id)]

    def destroy_piece(context):
        pieces = [i for i in context.state.players[context.player_id].board
                  if context.state.entities[i].card_id == 'piece']
        if len(pieces) != 1:
            raise AssertionError('Opening must create exactly one physical piece')
        return [Destroy(pieces[0], source_id=context.source_id)]

    def launch_built(context):
        ship = construction(context.state, context.player_id)
        if ship is None or ship.components != ('piece',):
            raise AssertionError('Opening must construct the actual dead piece')
        return [LaunchStarshipEffect(context.player_id, ship.id)]

    for name, behavior in (('noop', noop), ('bootstrap', bootstrap),
                           ('destroy-piece', destroy_piece), ('launch-built', launch_built)):
        registry.register_behavior(name, behavior)

    def metadata(collectible=True, card_class=CardClass.NEUTRAL, max_copies=None):
        return CardMetadata(collectible, (card_class,), Rarity.COMMON, max_copies=max_copies)

    registry.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, cost=2,
        on_use='noop', metadata=metadata(False, CardClass.MAGE)))
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30,
        initial_hero_power='power', metadata=metadata(False, CardClass.MAGE)))
    registry.register_card(CardDefinition('coin', 'Coin', CardType.SPELL,
        on_play='noop', metadata=metadata(False)))
    registry.register_card(CardDefinition('filler', 'Filler', CardType.MINION,
        attack=1, health=2, metadata=metadata(max_copies=8)))
    registry.register_card(CardDefinition('hook', 'Hook', CardType.MINION, health=1,
        opening_hooks=(OpeningHook('before_deal', 'bootstrap'),), metadata=metadata(max_copies=1)))
    registry.register_card(CardDefinition('piece', 'Piece', CardType.MINION,
        attack=2, health=3, keywords=(Keyword.STARSHIP_PIECE,), metadata=metadata(False)))
    registry.register_card(CardDefinition('ship', 'Ship', CardType.MINION, cost=5,
        starship_for=(CardClass.NEUTRAL,), metadata=metadata(False)))
    return registry


def bootstrap_setup(registry):
    decks = (
        DeckSpec('hero', 'power', CardClass.MAGE, ('hook',) + ('filler',) * 7),
        DeckSpec('hero', 'power', CardClass.MAGE, ('filler',) * 8),
    )
    policy = DeckPolicy('cost-opening-pool', 'synthetic-only', 'experimental',
                        tuple(registry.cards), deck_size=8)
    return MatchSetup(decks, policy, 'coin', 19, 1)


class CostBootstrapTests(unittest.TestCase):
    def portable(self, game, finite):
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, bootstrap_registry(finite))
        cloned = game.clone()
        replayed = replay(build_replay(game), bootstrap_registry(finite))
        for other in (restored, cloned, replayed):
            self.assertEqual(other.snapshot(), snapshot)
            self.assertEqual(other.legal_actions(), game.legal_actions())
            for player_id in (1, 2):
                self.assertEqual(other.observe(player_id), game.observe(player_id))
                self.assertEqual(other.for_player(player_id).observe(), game.for_player(player_id).observe())
        original = game.observe(1)
        detached = game.observe(1)
        detached.clear()
        self.assertEqual(game.observe(1), original)
        return restored

    def exercise(self, finite):
        registry = bootstrap_registry(finite)
        game = Game.from_decks(bootstrap_setup(registry), registry)
        state = game.state
        self.assertEqual(state.action_number, 0)
        self.assertEqual(state.opening.stage, 'mulligan')
        self.assertEqual(state.pending_choice.purpose, ChoicePurpose.MULLIGAN)
        self.assertEqual([p.mana for p in state.players.values()], [0, 0])
        self.assertEqual(len(state.starship_history), 1)
        launch = state.starship_history[0]
        self.assertEqual(launch.action, 0)
        ship = state.entities[launch.entity_id]
        self.assertTrue(ship.active)
        self.assertFalse(ship.starship_building)
        self.assertEqual((ship.attack, ship.health, ship.components), (2, 3, ('piece',)))
        self.assertFalse(any(event.kind.endswith('_spent') for event in game.events))
        self.assertEqual(len(state.cost_use_history), 1)
        receipt = state.cost_use_history[0]
        self.assertEqual((receipt.action, receipt.origin, receipt.source_id), (0, 'effect_launch', ship.id))
        self.assertEqual(receipt.amount, 3 if finite else 5)
        self.assertEqual(len(receipt.player_modifiers), int(finite))
        self.assertEqual(len(state.players[1].cost_modifiers), int(finite))
        if finite:
            original = receipt.player_modifiers[0]
            current = state.players[1].cost_modifiers[0]
            self.assertEqual((original.id, original.uses_remaining), (current.id, 2))
            self.assertEqual(current.uses_remaining, 1)
            self.assertEqual(receipt.consumable_ids, (current.id,))
        else:
            self.assertEqual(receipt.consumable_ids, ())
        game = self.portable(game, finite)
        while game.state.pending_choice is not None:
            choice = game.state.pending_choice
            game.apply(SelectChoice(choice.player_id, choice.id, ()))
            game = self.portable(game, finite)
        self.assertEqual(game.state.action_number, 2)
        self.assertEqual(game.state.opening.stage, 'complete')
        self.assertEqual([p.mana for p in game.state.players.values()], [1, 0])
        self.assertEqual(game.state.cost_use_history, state.cost_use_history)
        if finite:
            self.assertEqual(game.state.players[1].cost_modifiers[0].uses_remaining, 1)

    def test_action_zero_free_effect_launch_without_cost_modifier_is_portable(self):
        self.exercise(False)

    def test_action_zero_free_effect_launch_consumes_one_scope_use_without_payment(self):
        self.exercise(True)


if __name__ == '__main__':
    unittest.main()
