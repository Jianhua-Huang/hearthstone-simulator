"""Real Priest Imbue activation in the complete local constructed host."""
from functools import lru_cache
import json
import unittest

from hs_sim.engine import (CardClass, CardType, EndTurn, Game, IllegalAction,
                           PlayCard, PlayerSetup, Scenario, SelectChoice,
                           UseHeroPower)
from hs_sim.engine.player_api import PlayerPort
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import MOON_POOL_ID, MOON_SAMPLE_IDS
from hs_sim.engine.runtime import RuntimeMode
from hs_sim.local_pool_format import build_cn37_local_pool_format


@lru_cache(maxsize=2)
def local_format(role='writer'):
    return build_cn37_local_pool_format()


class PriestImbueLocalHostTests(unittest.TestCase):
    def game(self, mode=RuntimeMode.DEBUG, mana=10):
        fmt = local_format()
        game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_09', hand=('EDR_449',),
                        hero_power_card_id='HERO_09bp', mana=mana, max_mana=10,
                        deck=('CS2_182',) * 4),
            PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp',
                        mana=10, max_mana=10, deck=('CS2_182',) * 4),
        ), seed=66, generation_context=fmt.context), fmt.registry, mode=mode)
        source = game.state.players[1].hand[0]
        game.apply(PlayCard(1, source))
        self.assertEqual(game.state.entities[game.state.players[1].hero_power_id].card_id,
                         'EDR_449p')
        return game

    def test_real_imbue_then_moon_power_opens_both_constructed_offers(self):
        for mode in (RuntimeMode.DEBUG, RuntimeMode.RELEASE):
            with self.subTest(mode=mode):
                game = self.game(mode)
                power = game.state.players[1].hero_power_id
                game.apply(UseHeroPower(1, power))
                choice = game.state.pending_choice
                self.assertIsNotNone(choice)
                self.assertEqual([game.registry.card(option.card_id).kind
                                  for option in choice.options],
                                 [CardType.MINION, CardType.SPELL])
                self.assertEqual(game.state.players[1].mana, 6)
                self.assertEqual(game.state.entities[power].uses_this_turn, 1)

    def test_bound_alias_preserves_complete_standard_members_weights_and_exclusions(self):
        fmt = local_format()
        ordinary = fmt.registry.pool('constructed.cards', fmt.context)
        moon = fmt.registry.pool(MOON_POOL_ID, fmt.context)
        self.assertEqual(moon.members, ordinary.members)
        self.assertEqual(moon.excluded_card_ids, ordinary.excluded_card_ids)
        self.assertEqual(moon.complete, ordinary.complete)
        self.assertEqual((moon.target_id, moon.mode),
                         (fmt.context.target_id, fmt.context.mode))
        self.assertGreater(len(moon.members), len(MOON_SAMPLE_IDS))
        self.assertFalse(fmt.formal_pool_complete)

    def test_original_representative_ten_card_inventory_is_unchanged(self):
        fmt = local_format()
        sample = fmt.registry.pool(MOON_POOL_ID,
                                  GenerationContext('local-2026-09-23', 'experimental'))
        self.assertEqual(tuple(member.card_id for member in sample.members), MOON_SAMPLE_IDS)
        self.assertFalse(sample.complete)

    def test_both_offers_are_priest_cards_with_captured_imbue_discount(self):
        game = self.game()
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        standard_ids = {m.card_id for m in game.registry.pool(
            'constructed.cards', local_format().context).members}
        for option in game.state.pending_choice.options:
            definition = game.registry.card(option.card_id)
            self.assertIn(option.card_id, standard_ids)
            self.assertIn(CardClass.PRIEST, definition.metadata.classes)
            self.assertEqual(option.preview.cost, max(0, definition.cost - 1))
            self.assertLessEqual(option.preview.cost, game.state.players[1].mana)

    def test_pending_offers_restore_clone_and_replay_then_deliver_either_kind(self):
        for kind in (CardType.MINION, CardType.SPELL):
            with self.subTest(kind=kind):
                game = self.game()
                game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
                pending = json.loads(json.dumps(game.snapshot()))
                independent = local_format('independent-reader').registry
                restored = Game.from_snapshot(pending, independent)
                self.assertEqual(restored.snapshot(), pending)
                self.assertEqual(game.clone().snapshot(), pending)
                self.assertEqual(replay(build_replay(game), independent).snapshot(), pending)
                choice = game.state.pending_choice
                option = next(o for o in choice.options
                              if game.registry.card(o.card_id).kind == kind)
                action = SelectChoice(1, choice.id, (option.id,))
                game.apply(action)
                restored.apply(action)
                self.assertEqual(game.snapshot(), restored.snapshot())
                card = game.state.entities[game.state.players[1].hand[-1]]
                self.assertEqual(card.card_id, option.card_id)
                self.assertEqual(card.hand_lifetime.expires_turn, game.state.turn)

    def test_invalid_choice_rolls_back_and_unused_temporary_card_expires(self):
        game = self.game()
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        before = game.snapshot()
        choice = game.state.pending_choice
        with self.assertRaises(IllegalAction):
            game.apply(SelectChoice(1, choice.id, ('missing-offer',)))
        self.assertEqual(game.snapshot(), before)
        game.apply(SelectChoice(1, choice.id, (choice.options[0].id,)))
        card_id = game.state.players[1].hand[-1]
        game.apply(EndTurn(1))
        self.assertNotIn(card_id, game.state.players[1].hand)

    def test_player_port_use_and_select_are_accepted_without_private_receipts(self):
        game = self.game(RuntimeMode.RELEASE)
        port = PlayerPort(game, 1)
        current = port.legal_actions()
        action = next(a for a in current['actions'] if a['type'] == 'use_hero_power')
        reply = port.submit({'revision': current['revision'], 'action': action})
        self.assertTrue(reply['accepted'], reply['error'])
        for viewer in (1, 2):
            public = json.dumps(PlayerPort(game, viewer).observe())
            for private in ('eligible_ids', 'PoolOfferReceipt', 'rng_state'):
                self.assertNotIn(private, public)
        current = port.legal_actions()
        action = next(a for a in current['actions'] if a['type'] == 'select_choice')
        reply = port.submit({'revision': current['revision'], 'action': action})
        self.assertTrue(reply['accepted'], reply['error'])
        self.assertEqual(len(game.state.players[1].hand), 1)

    def test_affordability_uses_mana_left_after_the_two_mana_power(self):
        game = self.game(mana=4)
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        self.assertEqual(game.state.players[1].mana, 0)
        choice = game.state.pending_choice
        self.assertIsNotNone(choice)
        self.assertTrue(all(option.preview.cost == 0 for option in choice.options))


if __name__ == '__main__':
    unittest.main()
