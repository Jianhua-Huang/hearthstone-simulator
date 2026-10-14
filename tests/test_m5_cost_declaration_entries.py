"""Required cost declarations are validated even for stale effect targets."""
import unittest

from hs_sim.engine import (
    CardDefinition, CardType, Game, PlayCard, PlayerSetup, Registry,
    RepeatCostFilter, RepeatMatchSpec, Scenario, SpellRepeatSpec,
)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.spell_repeats import GrantSpellRepeatAura


def declaration_registry(profile):
    registry = Registry('fee-stale-declaration-' + profile)
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    spec = SpellRepeatSpec(2, 'any', RepeatMatchSpec(recipient_cost=
        RepeatCostFilter('window_quote', maximum=0, quote_profile_id=profile)))

    def grant(context):
        return [GrantSpellRepeatAura(999999, spec, source_id=context.source_id)]

    registry.register_behavior('grant', grant)
    registry.register_card(CardDefinition('grant', 'Grant', CardType.SPELL, on_play='grant'))
    return registry


class CostDeclarationEntryTests(unittest.TestCase):
    def game(self, profile):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=('grant',)), PlayerSetup('hero'))),
            declaration_registry(profile))

    def test_unknown_cost_profile_is_rejected_before_stale_aura_exit(self):
        game = self.game('fee.missing')
        before = game.snapshot()
        action = PlayCard(1, game.state.players[1].hand[0])
        with self.assertRaises((ValueError, ResolutionError)):
            game.apply(action)
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.state.play_history, [])
        self.assertEqual(game.state.cost_use_history, [])

    def test_known_cost_profile_keeps_ordinary_stale_effect_behavior(self):
        profile = 'repeat.cost.accepted_hand'
        game = self.game(profile)
        game.apply(PlayCard(1, game.state.players[1].hand[0]))
        self.assertTrue(game.state.play_history[-1].spell_acceptance_closed)
        self.assertEqual(len(game.state.cost_use_history), 1)
        self.assertFalse(any(a.kind == 'spell_repeat'
            for entity in game.state.entities.values() for a in entity.abilities))
        snapshot = game.snapshot()
        for other in (game.clone(), Game.from_snapshot(snapshot, declaration_registry(profile)),
                      replay(build_replay(game), declaration_registry(profile))):
            self.assertEqual(other.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(other.for_player(player).observe(), game.for_player(player).observe())


if __name__ == '__main__':
    unittest.main()
