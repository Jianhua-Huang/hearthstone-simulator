"""Target domains and null-target policies share validation and enumeration."""
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
                          PlayCard, PlayerSetup, Registry, Scenario, TargetMode, TargetSpec, Zone)
from hs_sim.engine.effects import GainArmor, ShuffleIntoDeck
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.replay import build_replay, replay


class TargetingTests(unittest.TestCase):
    def setUp(self):
        self.registry = Registry('targeting-tests-v1')
        self.registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        self.registry.register_card(CardDefinition('plain', 'Plain', CardType.MINION, attack=1, health=3))
        self.registry.register_card(CardDefinition('immune', 'Immune', CardType.MINION, health=3, keywords=(Keyword.IMMUNE,)))
        self.registry.register_card(CardDefinition('blank_spell', 'Blank spell', CardType.SPELL))
        self.registry.register_behavior('targeted', lambda c: [GainArmor(c.player_id, 1 if c.target_id is None else 2)])

    def card(self, spec=None, *, rule='any_entity', legacy=False, behavior='targeted'):
        self.registry.register_card(CardDefinition('test', 'Test', CardType.MINION, cost=2, health=3,
                                                   on_play=behavior, requires_target=legacy, target_rule=rule, targeting=spec))

    def game(self, board=(), enemy_board=(), hand=('test',), enemy_hand=(), deck=()):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board),
        )), self.registry)

    def source(self, game):
        return next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == 'test')

    def choices(self, game):
        return {a.target_id for a in game.legal_actions() if isinstance(a, PlayCard) and a.entity_id == self.source(game)}

    def board_spec(self, mode=TargetMode.REQUIRED, relation='any'):
        return TargetSpec(mode, (Zone.BOARD,), (CardType.MINION,), relation)

    def test_required_target_with_no_candidates_rejects_without_spending(self):
        self.card(self.board_spec())
        game = self.game()
        before = game.snapshot()
        self.assertEqual(game.legal_targets(self.source(game)), ())
        self.assertEqual(self.choices(game), set())
        with self.assertRaises(IllegalAction):
            game.apply(PlayCard(1, self.source(game)))
        self.assertEqual(game.snapshot(), before)

    def test_if_available_no_candidates_commits_and_calls_behavior_with_none(self):
        self.card(self.board_spec(TargetMode.IF_AVAILABLE))
        game = self.game()
        self.assertEqual(self.choices(game), {None})
        source = self.source(game)
        game.apply(PlayCard(1, source))
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(game.state.players[1].board, [source])
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 1)

    def test_if_available_cannot_skip_legal_target(self):
        self.card(self.board_spec(TargetMode.IF_AVAILABLE))
        game = self.game(board=('plain',))
        target = game.state.players[1].board[0]
        self.assertEqual(self.choices(game), {target})
        before = game.snapshot()
        with self.assertRaises(IllegalAction):
            game.apply(PlayCard(1, self.source(game)))
        self.assertEqual(game.snapshot(), before)
        game.apply(PlayCard(1, self.source(game), target))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 2)

    def test_optional_target_enumerates_none_and_targets(self):
        self.card(self.board_spec(TargetMode.OPTIONAL))
        game = self.game(board=('plain',), enemy_board=('plain',))
        expected = {None, *game.state.players[1].board, *game.state.players[2].board}
        self.assertEqual(self.choices(game), expected)
        for action in game.legal_actions():
            fork = game.clone()
            fork.apply(action)

    def test_controller_relation_and_nonexistent_target_are_enforced(self):
        self.card(self.board_spec(relation='enemy'))
        game = self.game(board=('plain',), enemy_board=('plain',))
        self.assertEqual(game.legal_targets(self.source(game)), tuple(game.state.players[2].board))
        for target in (game.state.players[1].board[0], game.state.players[2].hero_id, 999999):
            before = game.snapshot()
            with self.subTest(target=target), self.assertRaises(IllegalAction):
                game.apply(PlayCard(1, self.source(game), target))
            self.assertEqual(game.snapshot(), before)

    def test_targetless_uses_filtered_candidates_not_raw_board_count(self):
        self.card(self.board_spec(TargetMode.IF_AVAILABLE, 'friendly'))
        game = self.game(enemy_board=('plain',))
        self.assertEqual(self.choices(game), {None})
        game.apply(PlayCard(1, self.source(game)))

    def test_enemy_immune_is_unselectable_but_friendly_immune_can_be_selected(self):
        self.card(self.board_spec(TargetMode.IF_AVAILABLE))
        game = self.game(board=('immune',), enemy_board=('immune',))
        self.assertEqual(self.choices(game), set(game.state.players[1].board))

    def test_only_enemy_immune_allows_targetless_if_available(self):
        self.card(self.board_spec(TargetMode.IF_AVAILABLE))
        game = self.game(enemy_board=('immune',))
        self.assertEqual(self.choices(game), {None})

    def test_non_character_hand_spell_is_a_valid_target_in_explicit_domain(self):
        self.registry.register_behavior('shuffle', lambda c: [ShuffleIntoDeck(c.target_id, c.player_id)])
        self.card(TargetSpec(zones=(Zone.HAND,), kinds=(CardType.SPELL,), relation='friendly'), behavior='shuffle')
        game = self.game(hand=('test', 'blank_spell', 'plain'), enemy_hand=('blank_spell',))
        target = game.state.players[1].hand[1]
        self.assertEqual(self.choices(game), {target})
        game.apply(PlayCard(1, self.source(game), target))
        self.assertEqual(game.state.players[1].deck, [target])
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), game.snapshot())

    def test_deck_domain_and_predicate_can_select_non_character_entities(self):
        self.registry.register_target_rule('cost_zero', lambda c: c.state.entities[c.target_id].cost == 0)
        self.card(TargetSpec(zones=(Zone.DECK,), kinds=(CardType.SPELL,), relation='friendly'), rule='cost_zero')
        game = self.game(deck=('blank_spell', 'plain'))
        self.assertEqual(self.choices(game), {game.state.players[1].deck[0]})
        game.apply(PlayCard(1, self.source(game), game.state.players[1].deck[0]))

    def test_source_excluded_unless_profile_explicitly_permits_it(self):
        self.card(TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,)))
        game = self.game()
        self.assertEqual(self.choices(game), set())
        self.setUp()
        self.card(TargetSpec(zones=(Zone.HAND,), kinds=(CardType.MINION,), exclude_source=False))
        game = self.game()
        self.assertEqual(self.choices(game), {self.source(game)})
        game.apply(PlayCard(1, self.source(game), self.source(game)))

    def test_legacy_requires_target_remains_character_only(self):
        self.card(legacy=True)
        game = self.game(hand=('test', 'blank_spell'), board=('plain',))
        self.assertEqual(self.choices(game), {game.state.players[1].hero_id, game.state.players[2].hero_id,
                                             *game.state.players[1].board})

    def test_no_target_definition_rejects_supplied_target(self):
        self.card()
        game = self.game()
        self.assertEqual(self.choices(game), {None})
        with self.assertRaises(IllegalAction):
            game.apply(PlayCard(1, self.source(game), game.state.players[2].hero_id))

    def test_predicate_cannot_mutate_authoritative_state(self):
        def rule(ctx):
            ctx.state.players[1].mana = 999
            ctx.state.entities[ctx.target_id].damage = 999
            return True
        self.registry.register_target_rule('mutating', rule)
        self.card(self.board_spec(), rule='mutating')
        game = self.game(board=('plain',))
        before = game.snapshot()
        self.assertTrue(game.legal_targets(self.source(game)))
        self.assertEqual(game.snapshot(), before)

    def test_predicate_error_or_non_boolean_is_not_hidden_as_no_candidates(self):
        for handler in (lambda ctx: 1, lambda ctx: 1 / 0):
            with self.subTest(handler=handler):
                self.setUp()
                self.registry.register_target_rule('invalid', handler)
                self.card(self.board_spec(TargetMode.IF_AVAILABLE), rule='invalid')
                game = self.game(board=('plain',))
                before = game.snapshot()
                with self.assertRaises(ResolutionError):
                    game.legal_actions()
                with self.assertRaises(ResolutionError):
                    game.apply(PlayCard(1, self.source(game)))
                self.assertEqual(game.snapshot(), before)

    def test_target_spec_and_ambiguous_definition_rejected(self):
        for fields in (dict(mode='optional'), dict(zones=()), dict(kinds=(CardType.SPELL, CardType.SPELL)),
                       dict(zones=('hand',)), dict(relation='opponent'), dict(exclude_source=1)):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                TargetSpec(**fields)
        with self.assertRaises(ValueError):
            self.card(TargetSpec(), legacy=True)

    def test_target_query_rejects_foreign_hand_and_boolean_id(self):
        self.card(TargetSpec())
        game = self.game(enemy_hand=('plain',))
        for value in (True, game.state.players[2].hand[0], 99999):
            with self.subTest(value=value), self.assertRaises(IllegalAction):
                game.legal_targets(value)


if __name__ == '__main__':
    unittest.main()
