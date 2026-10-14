from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (Attack, CardClass, CardDefinition, CardType, ChoicePurpose, EndTurn, Game,
                           IllegalAction, OpeningHook, PlayCard, PlayerSetup, ResolutionError, Ruleset,
                           ResolutionLimitExceeded, Scenario, SelectChoice, SnapshotError, UseHeroPower, Zone)
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, GainArmor, RequestChoice, Summon)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from opening_fixtures import deck, metadata, registry, setup


class OpeningTests(unittest.TestCase):
    def setUp(self):
        self.registry = registry()

    def game(self, first=1, seed=71, **kwargs):
        return Game.from_decks(setup(self.registry, first, seed, **kwargs), self.registry)

    def choose(self, game, ids=()):
        pending = game.state.pending_choice
        return game.apply(SelectChoice(pending.player_id, pending.id, tuple(str(i) for i in ids)))

    def finish(self, game):
        while game.state.pending_choice is not None:
            self.choose(game)
        return game

    def portable(self, game):
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, self.registry)
        self.assertEqual(restored.snapshot(), snapshot)
        self.assertEqual(game.clone().snapshot(), snapshot)
        self.assertEqual(replay(build_replay(game), self.registry).snapshot(), snapshot)
        return restored

    def test_first_three_second_four_and_coin_is_not_in_mulligan(self):
        game = self.game()
        state = game.state
        self.assertEqual(state.action_number, 0)
        self.assertEqual(state.opening.stage, 'mulligan')
        self.assertEqual(state.pending_choice.purpose, ChoicePurpose.MULLIGAN)
        self.assertEqual([len(p.hand) for p in state.players.values()], [3, 4])
        self.assertEqual([p.mana for p in state.players.values()], [0, 0])
        self.assertFalse(any(e.card_id == 'coin' for e in state.entities.values()))
        self.assertEqual(len(game.legal_actions()), 10)
        self.portable(game)

    def test_keep_all_then_first_turn_draw_and_second_coin(self):
        game = self.game()
        first_hand = tuple(game.state.players[1].hand)
        second_hand = tuple(game.state.players[2].hand)
        self.choose(game)
        self.assertEqual(game.state.opening.completed, (1,))
        self.assertEqual(tuple(game.state.players[1].hand), first_hand)
        self.assertEqual(tuple(game.state.players[2].hand), second_hand)
        self.assertEqual(len(game.legal_actions()), 18)
        game = self.portable(game)
        self.choose(game)
        state = game.state
        self.assertEqual(state.opening.stage, 'complete')
        self.assertEqual([len(p.hand) for p in state.players.values()], [4, 5])
        self.assertEqual([len(p.deck) for p in state.players.values()], [26, 26])
        self.assertEqual([p.mana for p in state.players.values()], [1, 0])
        self.assertEqual(state.entities[state.players[2].hand[-1]].card_id, 'coin')
        self.assertEqual([e.kind for e in game.events].count('card_drawn'), 1)
        self.assertEqual([e.kind for e in game.events].count('turn_started'), 1)
        self.portable(game)

    def test_second_player_can_be_fixed_as_first(self):
        game = self.game(first=2)
        self.assertEqual(game.state.pending_choice.player_id, 2)
        self.assertEqual([len(p.hand) for p in game.state.players.values()], [4, 3])
        self.finish(game)
        self.assertEqual(game.state.active_player, 2)
        self.assertEqual([p.mana for p in game.state.players.values()], [0, 1])
        self.assertEqual(game.state.entities[game.state.players[1].hand[-1]].card_id, 'coin')

    def test_fixed_seed_reproduces_random_first_player_and_decks(self):
        a, b = self.game(first=None), self.game(first=None)
        self.assertEqual(a.snapshot(), b.snapshot())
        found = {self.game(first=None, seed=s).state.active_player for s in range(8)}
        self.assertEqual(found, {1, 2})
        self.assertNotEqual(a.snapshot()['rng_state'], self.game(first=None, seed=72).snapshot()['rng_state'])

    def test_full_mulligan_excludes_rejected_entities_until_replacements_selected(self):
        game = self.game()
        original = game.state.opening.offered
        self.choose(game, original[0])
        self.assertEqual(tuple(game.state.players[1].hand), original[0])
        game = self.portable(game)
        self.choose(game, original[1])
        state = game.state
        self.assertFalse(set(state.players[1].hand[:3]) & set(original[0]))
        self.assertFalse(set(state.players[2].hand[:4]) & set(original[1]))
        self.assertEqual(len(state.entities), 65)  # 60 cards, two heroes, two powers, one Coin
        for player in state.players.values():
            originals = set(state.opening.original_entities[player.id - 1])
            self.assertEqual(originals, (set(player.hand) | set(player.deck)) & originals)
        self.portable(game)

    def test_replacement_preserves_kept_slots_and_canonical_selection_order(self):
        game = self.game()
        hand = tuple(game.state.players[1].hand)
        self.choose(game, (hand[2], hand[0]))
        self.assertEqual(game.state.opening.selected[0], (hand[0], hand[2]))
        self.choose(game)
        new = game.state.players[1].hand
        self.assertEqual(new[1], hand[1])
        self.assertNotEqual(new[0], hand[0])
        self.assertNotEqual(new[2], hand[2])

    def test_mulligan_may_receive_another_copy_of_same_definition(self):
        # Eight copies use a declared fixture exception, not a relaxed global copy limit.
        self.registry.register_card(CardDefinition('copies', 'Copies', CardType.MINION, health=1,
                                                   metadata=metadata(max_copies=8)))
        decks = (deck(cards=('copies',) * 8), deck(CardClass.WARRIOR, cards=('copies',) * 8))
        game = self.game(decks=decks, deck_size=8)
        original = game.state.opening.offered
        self.choose(game, original[0])
        self.choose(game, original[1])
        self.assertFalse(set(game.state.players[2].hand[:4]) & set(original[1]))
        self.assertEqual([game.state.entities[i].card_id for i in game.state.players[2].hand[:4]], ['copies'] * 4)

    def test_keep_all_does_not_reshuffle_and_first_draw_uses_existing_top(self):
        game = self.game()
        before = game.snapshot()['rng_state']
        next_card = game.state.players[1].deck[0]
        self.finish(game)
        self.assertEqual(game.snapshot()['rng_state'], before)
        self.assertEqual(game.state.players[1].hand[-1], next_card)

    def test_wrong_player_normal_action_and_nonoffered_entity_fail_atomically(self):
        game = self.game()
        state = game.state
        pending = state.pending_choice
        before = game.snapshot()
        candidates = (EndTurn(1), PlayCard(1, state.players[1].hand[0]),
                      UseHeroPower(1, state.players[1].hero_power_id),
                      SelectChoice(2, pending.id, ()),
                      SelectChoice(1, pending.id, (str(state.players[1].deck[0]),)))
        for action in candidates:
            with self.subTest(action=action), self.assertRaises(IllegalAction):
                game.apply(action)
            self.assertEqual(game.snapshot(), before)

    def test_two_branches_choose_independently_and_replay(self):
        game = self.game()
        branch = self.portable(game)
        self.choose(game, game.state.opening.offered[0])
        self.choose(branch)
        self.finish(game)
        self.finish(branch)
        self.assertNotEqual(game.state.players[1].hand, branch.state.players[1].hand)
        self.portable(game)
        self.portable(branch)

    def test_coin_uses_normal_action_and_temporary_mana_account(self):
        game = self.finish(self.game())
        game.apply(EndTurn(1))
        player = game.state.players[2]
        coin = next(i for i in player.hand if game.state.entities[i].card_id == 'coin')
        game.apply(PlayCard(2, coin))
        self.assertEqual(game.state.players[2].mana, 2)
        self.assertEqual(game.state.players[2].max_mana, 1)
        game.apply(EndTurn(2))
        self.assertEqual(game.state.players[2].temporary_mana, 0)
        self.portable(game)

    def test_constructed_match_can_run_to_terminal_through_public_actions(self):
        game = self.finish(self.game())
        for _ in range(200):
            if game.state.status != 'playing':
                break
            actions = game.legal_actions()
            plays = [a for a in actions if isinstance(a, PlayCard)]
            attacks = [a for a in actions if isinstance(a, Attack)]
            game.apply(plays[0] if plays else attacks[0] if attacks else EndTurn(game.state.active_player))
        self.assertIn(game.state.status, ('finished', 'draw'))
        self.assertIsNone(game.state.pending_choice)
        self.portable(game)

    def add_hook_card(self, behavior, phase='after_mulligan'):
        self.registry.register_behavior('hook', behavior)
        self.registry.register_card(CardDefinition('hook-card', 'Hook', CardType.MINION, health=1,
            metadata=metadata(), opening_hooks=(OpeningHook(phase, 'hook'),)))
        return (deck(cards=('hook-card',) + deck().cards[1:]), deck(CardClass.WARRIOR))

    def test_after_mulligan_hook_runs_once_with_current_state_before_first_turn(self):
        decks = self.add_hook_card(lambda c: [GainArmor(c.player_id, len(c.state.players[2].hand))])
        game = self.game(decks=decks)
        self.finish(game)
        hero = game.state.entities[game.state.players[1].hero_id]
        self.assertEqual(hero.armor, 5)  # Opponent already holds the Coin.
        self.assertEqual(sum(e.kind == 'opening_effect' for e in game.events), 1)
        self.portable(game)

    def test_before_deal_hook_and_nested_choice_can_suspend_initial_setup(self):
        decks = self.add_hook_card(lambda c: [RequestChoice(c.player_id, (
            ChoiceOption('armor', 'Armor', (GainArmor(c.player_id, 3),)),))], phase='before_deal')
        game = self.game(decks=decks)
        self.assertEqual(game.state.opening.stage, 'dealing')
        self.assertFalse(game.state.players[1].hand)
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        game = self.portable(game)
        self.choose(game, ('armor',))
        self.assertEqual(game.state.opening.stage, 'mulligan')
        self.finish(game)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.portable(game)

    def test_after_mulligan_choice_before_first_turn_draw(self):
        decks = self.add_hook_card(lambda c: [RequestChoice(c.player_id, (ChoiceOption('ok', 'OK'),))])
        game = self.game(decks=decks)
        self.choose(game)
        self.choose(game)
        self.assertEqual(game.state.opening.stage, 'starting')
        self.assertEqual(len(game.state.players[1].hand), 3)
        self.assertEqual(game.state.players[1].mana, 0)
        game = self.portable(game)
        self.choose(game, ('ok',))
        self.assertEqual(game.state.opening.stage, 'complete')
        self.assertEqual(len(game.state.players[1].hand), 4)

    def test_failed_opening_hook_after_choices_rolls_back_last_selection(self):
        def broken(c):
            raise ValueError('hook failure')
        decks = self.add_hook_card(broken)
        game = self.game(decks=decks)
        self.choose(game)
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'hook failure'):
            self.choose(game, game.state.opening.offered[1])
        self.assertEqual(game.snapshot(), before)

    def test_lethal_opening_hook_terminates_without_starting_turn(self):
        decks = self.add_hook_card(lambda c: [Damage(c.state.players[2].hero_id, 30)])
        game = self.finish(self.game(decks=decks))
        self.assertEqual(game.state.winner, 1)
        self.assertFalse(any(e.kind == 'turn_started' for e in game.events))
        self.portable(game)

    def test_generated_hand_card_overflow_and_unknown_definition(self):
        self.registry.register_behavior('generate', lambda c: [AddToHand(1, 'card.1', c.source_id), AddToHand(1, 'card.2', c.source_id)])
        self.registry.register_card(CardDefinition('generate', 'Generate', CardType.SPELL, on_play='generate'))
        game = Game.from_scenario(Scenario((PlayerSetup('mage.hero', hand=('generate',) + ('card.3',) * 9),
                                            PlayerSetup('warrior.hero'))), self.registry)
        game.apply(PlayCard(1, game.state.players[1].hand[0]))
        self.assertEqual(len(game.state.players[1].hand), 10)
        self.assertEqual(sum(e.kind == 'card_burned' for e in game.events), 1)
        self.portable(game)

    def test_snapshot_rejects_opening_corruption_after_rehash(self):
        game = self.game()
        changes = (
            lambda s: s.update(match_setup=None),
            lambda s: s['state'].update(opening=None),
            lambda s: s['state']['opening'].update(first_player=2),
            lambda s: s['state']['opening'].update(stage='complete'),
            lambda s: s['state']['opening'].update(completed=[1, 1]),
            lambda s: s['state']['opening']['selected'].__setitem__(0, [9999]),
            lambda s: s['state']['opening']['original_entities'][0].__setitem__(0, 9999),
            lambda s: s['state']['players']['1'].update(deck_class='warrior'),
            lambda s: s['state']['players']['1'].update(original_deck=[]),
            lambda s: s['match_setup']['policy'].update(pool_complete=False, mode='standard'),
            lambda s: s['match_setup']['decks'][0].update(cards=[]),
            lambda s: s['state'].update(turn=2),
        )
        for change in changes:
            snapshot = deepcopy(game.snapshot())
            change(snapshot)
            snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
                if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
            with self.subTest(change=change), self.assertRaises(SnapshotError):
                Game.from_snapshot(snapshot, self.registry)
        self.choose(game)
        snapshot = game.snapshot()
        snapshot['state']['opening']['completed'][0] = True
        snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, self.registry)

    def test_setup_constraints_fail_before_returning_partial_game(self):
        with self.assertRaisesRegex(ValueError, 'room'):
            Game.from_decks(setup(self.registry), self.registry, Ruleset(max_hand=4))
        decks = (deck(cards=deck().cards[:4]), deck(CardClass.WARRIOR, cards=deck().cards[:4]))
        with self.assertRaisesRegex(ValueError, 'eight'):
            self.game(decks=decks, deck_size=4)

    def test_cumulative_opening_budget_cannot_reset_between_mulligans(self):
        game = Game.from_decks(setup(self.registry), self.registry, Ruleset(max_resolution_steps=10))
        self.choose(game)
        before = game.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):
            self.choose(game)
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_hook_metadata_and_original_decks_survive_play_and_restore(self):
        decks = self.add_hook_card(lambda c: [GainArmor(c.player_id, len(c.state.players[c.player_id].original_deck))])
        game = self.finish(self.game(decks=decks))
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 30)
        game.apply(EndTurn(1))
        restored = self.portable(game)
        self.assertEqual(restored.state.players[1].original_deck, decks[0].cards)
        self.assertEqual(restored.state.players[1].deck_class, CardClass.MAGE)

    def test_death_knight_rune_loadout_survives_opening_snapshot(self):
        from hs_sim.engine import Runes
        decks = (deck(CardClass.DEATH_KNIGHT, runes=Runes(1, 1, 1)), deck(CardClass.WARRIOR))
        game = self.game(decks=decks)
        restored = self.portable(game)
        self.finish(restored)
        self.assertEqual(restored.state.players[1].runes, Runes(1, 1, 1))
        self.portable(restored)

    def test_opening_hook_ordinary_trigger_can_choose_before_mulligan_offer(self):
        from hs_sim.engine import TriggerSpec
        self.registry.register_behavior('observe_deal', lambda c: [RequestChoice(2, (ChoiceOption('ok', 'OK'),))])
        self.registry.register_card(CardDefinition('listener', 'Listener', CardType.MINION, health=3,
            triggers=(TriggerSpec('opening_hand_dealt', 'observe_deal'),)))
        decks = self.add_hook_card(lambda c: [Summon(1, 'listener')], phase='before_deal')
        game = self.game(decks=decks)
        self.assertEqual(game.state.opening.stage, 'mulligan')
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.EFFECT)
        game = self.portable(game)
        self.choose(game, ('ok',))
        self.choose(game, ('ok',))
        self.assertEqual(game.state.pending_choice.purpose, ChoicePurpose.MULLIGAN)
        self.finish(game)
        self.portable(game)

    def test_old_ninth_schema_rejected(self):
        snapshot = self.game().snapshot()
        snapshot['schema_version'] = 9
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot'):
            Game.from_snapshot(snapshot, self.registry)


if __name__ == '__main__':
    unittest.main()
