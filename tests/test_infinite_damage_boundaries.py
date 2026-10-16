"""Empty public requests and explicit separation from ordinary integer damage."""
from types import SimpleNamespace
import unittest
from hs_sim.cards import build_registry
from hs_sim.engine import CardDefinition, CardType, Game, PlayCard, PlayerSetup, Scenario
from hs_sim.engine.effects import Damage
from hs_sim.engine.health_rules import prepare_health
from hs_sim.engine.infinite_damage import INFINITE_HEALTH_VALUE, RandomInfiniteDamageMinion, choose
from hs_sim.engine.model import DamageKind, HealthFlow, HealthOp, HealthRule


class InfiniteDamageBoundaryTests(unittest.TestCase):
    def game(self):
        registry = build_registry(); meta = registry.card('END_024').metadata
        registry.register_behavior('infinite.bound.empty', lambda c: (RandomInfiniteDamageMinion((), c.source_id),))
        registry.register_card(CardDefinition('infinite.bound.empty', 'Empty pool', CardType.SPELL,
            on_play='infinite.bound.empty', metadata=meta))
        registry.register_card(CardDefinition('infinite.bound.double', 'Source multiplier', CardType.MINION,
            health=5, health_rules=(HealthRule(HealthFlow.DAMAGE, HealthOp.SCALE, 2, source_relation='friendly'),), metadata=meta))
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=('END_024', 'infinite.bound.empty'), board=('infinite.bound.double',)),
            PlayerSetup('HERO_08', board=('CORE_CS2_182',))), seed=231), registry)

    def test_empty_public_request_keeps_rng_and_emits_one_skip(self):
        game = self.game(); before = game.snapshot()['rng_state']
        source = next(e for e in game.state.players[1].hand if game.state.entities[e].card_id == 'infinite.bound.empty')
        game.apply(PlayCard(1, source))
        self.assertEqual(game.snapshot()['rng_state'], before)
        self.assertEqual(sum(event.kind == 'random_choice_skipped' for event in game.events), 1)
        self.assertFalse(game.state.damage_history)

    def test_ordinary_large_integer_damage_is_not_globally_clamped(self):
        game = self.game(); source = game.state.players[1].hand[0]; target = game.state.players[2].board[0]
        instruction = Damage(target, INFINITE_HEALTH_VALUE, source, DamageKind.SPELL); before = game.snapshot()
        ordinary = prepare_health(game.state, game.registry, instruction)
        explicit = prepare_health(game.state, game.registry, instruction, numeric_limit=INFINITE_HEALTH_VALUE)
        self.assertEqual((ordinary.amount, explicit.amount), (2*INFINITE_HEALTH_VALUE, INFINITE_HEALTH_VALUE))
        self.assertIsNone(ordinary.numeric_limit); self.assertEqual(game.snapshot(), before)

    def test_empty_public_request_does_not_hide_unknown_callback(self):
        game = self.game(); source = game.state.players[1].hand[0]
        with self.assertRaises(ValueError):
            choose(SimpleNamespace(state=game.state, registry=game.registry),
                   RandomInfiniteDamageMinion((), source, 'unknown.infinite.callback'))


if __name__ == '__main__': unittest.main()
