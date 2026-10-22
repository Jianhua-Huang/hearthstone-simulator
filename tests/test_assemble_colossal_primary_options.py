"""Original comparison faces retain complete reviewed Colossal material."""
from dataclasses import replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.native_assemble_entry_cards import SHAPER, POOL_ID
from hs_sim.cards.native_assemble_followup_cards import SCULPT
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, Rarity
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from test_assemble_colossal_followups import fixture as base_fixture, BLOOD, VULCANOS, WATCH, CTX
from test_assemble_card_play_followups import META, COIN, N

AUCTION, ANTONIDAS, PREY = 'JAIL_718', 'CORE_EX1_559', 'BE_998'
NOOP, UNKNOWN = 'k432.noop', 'k432.unknown'
PRIEST_SEED = 0


def recipe(primary, secondary, half='bottom'):
    return AssembleRecipe(primary, secondary, half).card_id


@lru_cache(None)
def fixture(mode='mage', role='writer'):
    r = base_fixture.__wrapped__('normal', role)
    r._version += '.k432.' + mode
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, on_play=NOOP, metadata=META))
    members = (BLOOD, PREY, AUCTION) if mode == 'priest' else (VULCANOS, ANTONIDAS, AUCTION)
    if mode == 'unknown':
        missing = CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, cost=7, attack=7, health=7,
            metadata=replace(META, collectible=True, rarity=Rarity.COMMON,
                classes=(CardClass.MAGE,), deck_identity=UNKNOWN))
        r.register_pool_card(PoolCard.from_definition(missing))
        members += (UNKNOWN,)
    r.register_pool(PoolDefinition(POOL_ID, 'k432-complete-explicit-colossal-primary-domain',
        CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


class AssembleColossalPrimaryOptionsTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='mage'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_09' if mode == 'priest' else 'HERO_08', hand=hand, board=board,
                deck=(COIN,) * 20, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', deck=(COIN,) * 20, mana=50, max_mana=50, mana_cap=50)),
            seed=PRIEST_SEED if mode == 'priest' else 432, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='board'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid):
        source = self.eid(g, cid, 'hand')
        g.apply(PlayCard(1, source))
        return source

    def pick(self, g, key):
        q = g.state.pending_choice
        g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def select_face(self, g, cid):
        q = g.state.pending_choice
        self.pick(g, next(o.id for o in q.options if o.card_id == cid))

    def count(self, g, cid, zone='board'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def portable(self, g, mode='mage'):
        saved = json.loads(json.dumps(g.snapshot()))
        reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry)
        other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'assemble_colossal_sources', 'primary_candidates'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_both_colossal_original_self_pairs_are_true_noop_options(self):
        r = fixture(); fingerprint = r.fingerprint()
        for cid in (BLOOD, VULCANOS):
            self.assertEqual(recipe_options(r, cid, cid), ())
            self.assertEqual(r.card(recipe(cid, cid)).colossal, r.card(cid).colossal)
        self.assertEqual(r.fingerprint(), fingerprint)

    def test_b_both_primary_halves_preserve_or_clear_the_actual_selected_material(self):
        r = fixture()
        for primary in (BLOOD, VULCANOS):
            options = recipe_options(r, primary, AUCTION)
            self.assertEqual([half for half, _ in options], ['top', 'bottom'])
            old = r.card(primary)
            for half, cid in options:
                face = r.card(cid)
                self.assertEqual((face.cost, face.attack, face.health, face.metadata),
                    (old.cost, old.attack, old.health, old.metadata))
                self.assertEqual(face.colossal, old.colossal if half == 'bottom' else ())
                self.assertEqual(Keyword.COLOSSAL in face.keywords, half == 'bottom')

    def test_c_real_shaper_pending_offer_restores_without_resampling_colossal_primary(self):
        g = self.game((SHAPER,)); self.play(g, SHAPER)
        cid = recipe(VULCANOS, AUCTION)
        self.assertIn(cid, [o.card_id for o in g.state.pending_choice.options])
        other = self.portable(g)
        for game in (g, other): self.select_face(game, cid)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.count(g, SHAPER), 1)
        self.assertEqual(g.registry.card(cid).colossal, g.registry.card(VULCANOS).colossal)

    def test_d_real_shaper_bottom_keeps_two_limbs_native_payment_and_new_end_draw(self):
        cid = recipe(VULCANOS, AUCTION)
        g = self.game((SHAPER,)); self.play(g, SHAPER); self.select_face(g, cid)
        mana = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 7)
        self.assertEqual(len(g.state.players[1].board), 4)
        row = g.state.colossal_history[-1]
        self.assertEqual(row.entity_id, source)
        self.assertEqual(len(row.limbs), 2); self.assertTrue(all(i is not None for i in row.limbs))
        g.apply(EndTurn(1))
        self.assertEqual(self.count(g, COIN, 'hand'), 1)
        self.portable(g)

    def test_e_real_shaper_top_removes_old_colossal_and_keeps_primary_cost(self):
        cid = recipe(VULCANOS, AUCTION, 'top')
        g = self.game((SHAPER, NOOP)); self.play(g, SHAPER); self.select_face(g, cid)
        mana = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 7)
        self.assertEqual(len(g.state.players[1].board), 2)
        self.assertNotIn(Keyword.COLOSSAL, g.state.entities[source].keywords)
        self.assertEqual(g.registry.card(cid).colossal, ())
        shaper = self.eid(g, SHAPER)
        self.play(g, NOOP)
        self.assertEqual(len(g.state.players[1].board), 1)
        self.assertEqual(g.state.entities[shaper].damage, 3)
        self.assertEqual(g.state.entities[shaper].zone, Zone.GRAVEYARD)
        self.assertEqual(g.state.entities[source].damage, 0)
        self.portable(g)

    def test_f_real_shadow_sculpt_keeps_three_limbs_and_original_two_cost_discount(self):
        cid = recipe(BLOOD, AUCTION)
        g = self.game((SCULPT,), mode='priest'); self.play(g, SCULPT)
        self.select_face(g, cid)
        held = self.eid(g, cid, 'hand')
        self.assertEqual(g.quote_cost(held).amount, 5)
        mana = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 5)
        self.assertEqual(g.state.entities[source].zone, Zone.BOARD)
        self.assertEqual(len(g.state.players[1].board), 4)
        self.assertEqual(len(g.state.colossal_history[-1].limbs), 3)
        self.portable(g, 'priest')

    def test_g_colossal_entry_wait_and_failed_resume_keep_full_original_material(self):
        cid = recipe(BLOOD, AUCTION)
        g = self.game((SCULPT,), board=(WATCH,), mode='priest')
        self.play(g, SCULPT); self.select_face(g, cid); self.play(g, cid)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'priest'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other): self.pick(game, 'go')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertTrue(all(i is not None for i in g.state.colossal_history[-1].limbs))

    def test_h_board_full_keeps_paid_primary_and_records_each_failed_appendage(self):
        cid = recipe(VULCANOS, AUCTION)
        g = self.game((SHAPER,), board=(N,) * 5); self.play(g, SHAPER); self.select_face(g, cid)
        self.play(g, cid)
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertEqual(g.state.colossal_history[-1].limbs, (None, None))
        self.assertEqual(self.count(g, cid), 1)
        self.portable(g)

    def test_i_eligible_unknown_primary_is_not_pruned_and_rolls_back_the_real_entry(self):
        g = self.game((SHAPER,), mode='unknown'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, SHAPER)
        self.assertEqual(g.snapshot(), saved)

    def test_j_missing_reviewed_original_appendages_fail_instead_of_using_primary_fields(self):
        r = fixture.__wrapped__(); r._assemble_colossal_sources.pop(VULCANOS)
        with self.assertRaises(ValueError): recipe_options(r, VULCANOS, AUCTION)


if __name__ == '__main__':
    unittest.main()
