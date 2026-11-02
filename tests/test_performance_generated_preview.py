"""Received-card previews keep actual admission and caller isolation."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Registry, Scenario
from hs_sim.engine import generated_card_preview as preview
from hs_sim.engine.information import Information
from hs_sim.engine.model import GameState
import test_native_playable_spell_cards as fixtures


class GeneratedPreviewPerformanceTests(unittest.TestCase):
    def test_projection_matches_full_copy_for_real_admission_variants(self):
        for mode, enemy in ((None, ()), ('weapon', (fixtures.FILL,))):
            game = fixtures.NativePlayableSpellTests().game(mode=mode, enemy=enemy)
            saved, information = game.snapshot(), game._information.to_dict()
            for player in (1, 2):
                source = game._state.players[player].hand[0]
                for card in (*fixtures.MEMBERS, fixtures.SECRET, fixtures.ONGOING, 'CORE_EX1_160', fixtures.FILL):
                    args = (game._state, game.registry, game.ruleset, game._information,
                            player, card, source, game._state.turn)
                    with self.subTest(mode=mode, player=player, card=card):
                        self.assertEqual(preview.can_receive_and_play(*args, readonly=True),
                                         preview.can_receive_and_play(*args))
                        self.assertEqual(game.snapshot(), saved)
                        self.assertEqual(game._information.to_dict(), information)

    def test_fast_preview_does_not_deepcopy_the_state_or_information_history(self):
        game = fixtures.NativePlayableSpellTests().game()
        source = game._state.players[1].hand[0]
        original = preview.deepcopy
        def copying(value):
            self.assertNotIsInstance(value, (GameState, Information))
            return original(value)
        with patch.object(preview, 'deepcopy', side_effect=copying):
            self.assertTrue(preview.can_receive_and_play(game._state, game.registry, game.ruleset,
                game._information, 1, fixtures.CHEAP, source, game._state.turn, readonly=True))

    def test_materialization_failure_cannot_leave_a_card_or_advance_input_ids(self):
        game = fixtures.NativePlayableSpellTests().game()
        saved, information = game.snapshot(), game._information.to_dict()
        original = preview.create_entity
        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError('failure after hypothetical hand entry')
        with patch.object(preview, 'create_entity', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'hypothetical'):
            preview.can_receive_and_play(game._state, game.registry, game.ruleset, game._information,
                1, fixtures.CHEAP, game._state.players[1].hand[0], game._state.turn, readonly=True)
        self.assertEqual(game.snapshot(), saved)
        self.assertEqual(game._information.to_dict(), information)

    def callback_game(self, callback, visibility):
        registry = Registry('generated-preview-callback-isolation')
        registry.register_behavior('nothing', lambda c: ())
        registry.register_use_rule('extension', callback, visibility=visibility)
        registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        registry.register_card(CardDefinition('plain', 'Plain', CardType.SPELL, on_play='nothing'))
        registry.register_card(CardDefinition('candidate', 'Candidate', CardType.SPELL,
                                             on_play='nothing', use_rule='extension'))
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=('plain',), mana=3, max_mana=3),
            PlayerSetup('hero', hand=('plain',), deck=('plain',))), seed=17), registry)

    def test_omniscient_use_callback_cannot_mutate_shared_entities_or_histories(self):
        seen = []
        def callback(context):
            seen.append(len(context.state.players[2].deck))
            context.state.players[2].deck.clear()
            context.state.hand_entries.clear()
            context.state.entities[context.state.players[1].hero_id].damage = 20
            return True
        game = self.callback_game(callback, 'omniscient'); saved = game.snapshot()
        for fast in (True, True, False):
            self.assertTrue(preview.can_receive_and_play(game._state, game.registry, game.ruleset,
                game._information, 1, 'candidate', game._state.players[1].hero_id, game._state.turn, readonly=fast))
            self.assertEqual(game.snapshot(), saved)
        self.assertEqual(seen, [1, 1, 1])

    def test_player_use_callback_keeps_hidden_information_and_independent_dto(self):
        def callback(context):
            self.assertFalse(hasattr(context, 'state'))
            enemy = next(p for p in context.observation['players'] if p['id'] == 2)
            self.assertIsNone(enemy['hand'][0]['card_id'])
            context.observation['players'].clear(); context.source.clear()
            return True
        game = self.callback_game(callback, 'player'); saved = game.snapshot()
        for fast in (True, False):
            self.assertTrue(preview.can_receive_and_play(game._state, game.registry, game.ruleset,
                game._information, 1, 'candidate', game._state.players[1].hero_id, game._state.turn, readonly=fast))
            self.assertEqual(game.snapshot(), saved)

    def test_extension_information_retains_full_copy_protocol(self):
        calls = []
        class CustomInformation(Information):
            def __deepcopy__(self, memo):
                calls.append(True)
                result = CustomInformation()
                result.players = deepcopy(self.players, memo)
                return result
        game = fixtures.NativePlayableSpellTests().game()
        information = CustomInformation(); information.players = deepcopy(game._information.players)
        before = information.to_dict()
        self.assertTrue(preview.can_receive_and_play(game._state, game.registry, game.ruleset, information,
            1, fixtures.CHEAP, game._state.players[1].hand[0], game._state.turn, readonly=True))
        self.assertEqual(calls, [True])
        self.assertEqual(information.to_dict(), before)


if __name__ == '__main__':
    unittest.main()
