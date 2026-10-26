"""Real Standard cards for the two deterministic client comparison recipes.

These are local behavior/limitation checks, not observations of a live server.
Only preparation is supplied as a scenario; the relevant cards are paid and
played through the normal public action path.
"""
from functools import lru_cache
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import EndTurn, Game, PlayerSetup, Scenario, Zone
from hs_sim.engine.errors import ResolutionError
from card_batch_testkit import CardBatchTestMixin


CHAINS = 'CATA_496'
CONFINEMENT = 'JAIL_997'
LIBRARIAN = 'CORE_SW_066'
TARGET = 'CORE_CS2_179'
FILLER = 'CORE_EX1_028'
PREPARED = ('CORE_NEW1_018',) * 2 + ('CORE_EX1_103',) * 2 + ('CORE_GIL_534',) * 2


@lru_cache(maxsize=2)
def fixture(mode=None, role='writer'):
    if mode is not None or role not in ('writer', 'independent-reader'):
        raise ValueError('Unknown local boundary fixture')
    return build_registry()


def leases(entity):
    return tuple(e for e in entity.enchantments if e.control_return_player_id is not None)


class CN37LocalControlBoundaryTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)
    mode = None

    def game(self, *, prepared=0):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07', hand=(TARGET, CHAINS, LIBRARIAN, FILLER),
                board=PREPARED[:prepared], deck=(FILLER,) * 8, mana=10, max_mana=10),
            PlayerSetup('HERO_07', hand=(CHAINS, CONFINEMENT),
                deck=(FILLER,) * 8, mana=10, max_mana=10),
        ), active_player=1, seed=540), fixture())

    def end(self, game):
        game.apply(EndTurn(game.state.active_player))

    def borrowed(self, game):
        target = self.play(game, TARGET)
        self.end(game)
        self.play(game, CHAINS, target, player=2)
        self.assertEqual(game.state.entities[target].controller, 2)
        return target

    def prepared_return(self, *, full, dormant):
        game = self.game(prepared=6 if full else 5)
        target = self.borrowed(game)
        if dormant:
            self.play(game, CONFINEMENT, target, player=2)
            self.assertIsNotNone(game.state.entities[target].dormancy)
            self.assertFalse(game.state.entities[target].active)
        self.end(game)
        self.play(game, FILLER)
        self.assertEqual(len(game.state.players[1].board), 7 if full else 6)
        self.assertEqual(game.state.entities[target].controller, 2)
        self.assertEqual(len(leases(game.state.entities[target])), 1)
        return game, target

    def test_t6_real_double_chains_and_librarian_keep_original_controller_after_silence(self):
        game = self.game()
        target = self.borrowed(game)
        self.end(game)
        self.play(game, CHAINS, target)
        self.assertEqual(len(leases(game.state.entities[target])), 2)
        restored = self.portable(game)
        for current in (game, restored):
            self.play(current, LIBRARIAN, target)
            entity = current.state.entities[target]
            self.assertEqual((entity.controller, entity.zone, leases(entity)), (1, Zone.BOARD, ()))
            self.assertEqual(current.state.players[1].mana, 4)
            self.end(current)
            self.end(current)
            self.assertEqual((current.state.entities[target].controller,
                current.state.entities[target].zone), (1, Zone.BOARD))
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_t7_room_control_returns_same_dormant_entity_and_restores_continuation(self):
        game, target = self.prepared_return(full=False, dormant=True)
        restored = self.portable(game)
        for current in (game, restored):
            self.end(current)
            entity = current.state.entities[target]
            self.assertEqual((entity.controller, entity.zone, leases(entity)), (1, Zone.BOARD, ()))
            self.assertIsNotNone(entity.dormancy)
            self.assertEqual(len(current.state.players[1].board), 7)
        self.assertEqual(game.snapshot(), restored.snapshot())

    def test_t7_active_control_full_destination_uses_existing_destroy_policy(self):
        game, target = self.prepared_return(full=True, dormant=False)
        self.end(game)
        entity = game.state.entities[target]
        self.assertEqual((entity.controller, entity.zone), (2, Zone.GRAVEYARD))
        self.assertEqual(len(game.state.players[1].board), 7)
        self.assertEqual(next(d.controller for d in game.state.death_history
            if d.entity_id == target), 2)

    def test_t7_dormant_full_destination_is_explicit_limitation_and_atomic_on_restore(self):
        game, target = self.prepared_return(full=True, dormant=True)
        restored = self.portable(game)
        for current in (game, restored):
            before = current.snapshot()
            with self.assertRaisesRegex(ResolutionError, 'Dormant full-board control return'):
                self.end(current)
            self.assertEqual(current.snapshot(), before)
            self.assertEqual(current.state.active_player, 1)
            self.assertEqual(current.state.entities[target].controller, 2)
            self.assertIsNotNone(current.state.entities[target].dormancy)
            self.assertEqual(len(leases(current.state.entities[target])), 1)
        self.assertEqual(game.snapshot(), restored.snapshot())


if __name__ == '__main__':
    unittest.main()
