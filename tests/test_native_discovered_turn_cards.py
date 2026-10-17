"""Real Unearthed Artifacts, with an explicitly experimental complete fixture."""
from copy import deepcopy
import json
import unittest

from hs_sim.cards.native_discovered_turn_cards import CARD, BODY, load_batch
from hs_sim.engine import CardClass, EndTurn, SnapshotError
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.card_discoveries import discovered_cards
from hs_sim.engine.registry import UnsupportedDefinitionError
from tools.card_batch import check_face
from test_card_discoveries import (A, DISC, DECK, GEN, MENU, MAP, game, play, choose,
    portable, registry, rehash)


class DiscoveredTurnCardTests(unittest.TestCase):
    def test_complete_real_source_and_two_strict_primary_faces(self):
        data = load_batch(); raw = data['cards'][0]['record']; card = registry().card(CARD)
        self.assertEqual((card.cost, card.metadata.classes, card.on_play, card.spell_school),
            (2, (CardClass.MAGE,), BODY, None))
        self.assertEqual(len(data['official_observations']), 2)
        for observation in data['official_observations']:
            check_face(raw, observation['face'], observation['locale'])
        self.assertEqual({x['record']['id'] for x in data['evidence_only']},
            {'TLC_365', 'TLC_483', 'TLC_460', 'TLC_460t'})
        self.assertTrue(all(cid not in registry().cards for cid in ('TLC_365','TLC_483','TLC_460','TLC_460t')))

    def test_paid_real_entry_without_discovery_summons_one_printed_two_cost(self):
        g = game((CARD,)); play(g, CARD)
        board = g.state.players[1].board
        self.assertEqual(len(board), 1)
        self.assertEqual(g.registry.card(g.state.entities[board[0]].card_id).cost, 2)
        self.assertEqual(g.state.players[1].mana, 28)
        self.assertEqual(discovered_cards(g.state, 1), ())
        portable(self, g)

    def test_real_entry_after_pool_physical_and_map_discovery_summons_four_cost(self):
        for producer in (DISC, DECK, MAP):
            with self.subTest(producer=producer):
                g = game((producer, CARD)); play(g, producer); choose(g)
                g = portable(self, g); play(g, CARD)
                entity = g.state.entities[g.state.players[1].board[-1]]
                self.assertEqual(g.registry.card(entity.card_id).cost, 4)
                self.assertEqual(len(discovered_cards(g.state, 1)), 1)
                portable(self, g)

    def test_other_class_four_cost_minion_is_eligible_for_unrestricted_random_summon(self):
        g = game((DISC, CARD), mode='foreign_four'); play(g, DISC); choose(g); play(g, CARD)
        entity = g.state.entities[g.state.players[1].board[-1]]
        self.assertEqual(g.registry.card(entity.card_id).metadata.classes, (CardClass.WARRIOR,))
        portable(self, g, 'foreign_four')

    def test_generated_card_and_ordinary_card_menu_do_not_upgrade_real_spell(self):
        for producer in (GEN, MENU):
            with self.subTest(producer=producer):
                g = game((producer, CARD)); play(g, producer)
                if g.state.pending_choice is not None: choose(g)
                play(g, CARD)
                self.assertEqual(g.registry.card(g.state.entities[g.state.players[1].board[-1]].card_id).cost, 2)
                self.assertEqual(discovered_cards(g.state, 1), ())

    def test_next_actual_turn_resets_condition_without_deleting_discovery_history(self):
        g = game((DISC, CARD, CARD)); play(g, DISC); choose(g); play(g, CARD)
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); play(g, CARD)
        self.assertEqual([g.registry.card(g.state.entities[i].card_id).cost for i in g.state.players[1].board], [4, 2])
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        portable(self, g)

    def test_second_player_uses_own_fact_and_no_four_candidate_has_no_summon(self):
        g = game((DISC, CARD), pid=2, mode='no_four'); play(g, DISC); choose(g); play(g, CARD)
        self.assertEqual(g.state.players[2].board, [])
        self.assertEqual(len(discovered_cards(g.state, 2)), 1)
        self.assertEqual(discovered_cards(g.state, 1), ())
        portable(self, g, 'no_four')

    def test_unknown_eligible_candidate_fails_and_rolls_back_actual_hand_play(self):
        g = game((DISC, CARD), mode='unadapted'); play(g, DISC); choose(g)
        saved = g.snapshot()
        with self.assertRaises((ResolutionError, UnsupportedDefinitionError)):
            play(g, CARD)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(len(discovered_cards(g.state, 1)), 1)
        portable(self, g, 'unadapted')
