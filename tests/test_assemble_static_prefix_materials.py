"""Native static prefix material, cost receipts, aura lifecycle and real offers."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_static_prefix_materials as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.assemble_static_materials import AssembleStaticMaterialSource
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion, Destroy,
    GainArmor, InvokeBehavior, RequestChoice)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, KILL, MUTE, LOOT, N

GHOST, TICH = cards.SOURCES
P = 'k435.'
DEMON, OTHER, GIVE, COPY, BASE_COPY, WATCH, FAIL = (
    P + name for name in ('demon', 'other', 'give', 'copy', 'base_copy', 'watch', 'fail'))
CTX = GenerationContext('k435-explicit-original-static-material-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k435.' + mode
    for cid, tribe in ((DEMON, 'demon'), (OTHER, 'beast')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, cost=6, attack=1, health=8,
            metadata=replace(META, tribes=(tribe,))))
    r.register_behavior(GIVE, lambda c: (ChangeControl(c.target_id, 3-c.player_id),))
    r.register_card(CardDefinition(GIVE, GIVE, CardType.SPELL, on_play=GIVE, targeting=TargetSpec(), metadata=META))
    for cid, copy_mode in ((COPY, 'current'), (BASE_COPY, 'base')):
        r.register_behavior(cid, lambda c, copy_mode=copy_mode: (CopyMinion(c.target_id, c.player_id, mode=copy_mode),))
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), metadata=META))
    def fail(c): raise ResolutionError('K435 deliberate static-material payment continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        enemy = next(iter(c.state.players[2].board), None)
        extra = (ChoiceOption('death', 'One more actual death', (Destroy(enemy, c.source_id),)),) if enemy else ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))),
            *extra), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('card_drawn', WATCH),)))
    if mode == 'assemble':
        r.register_pool(PoolDefinition(POOL_ID, 'k435-neutral-two-and-current-seven-nine-static-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (LOOT, GHOST, TICH)), complete=True))
    r.validate(); return r


class AssembleStaticPrefixTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', board=enemy, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=435, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='board', player=1):
        return next(i for i in getattr(g.state.players[player], zone) if g.state.entities[i].card_id == cid)

    def count(self, g, cid, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def play(self, g, cid, target=None):
        source = self.eid(g, cid, 'hand'); g.apply(PlayCard(1, source, target)); return source

    def price(self, g, cid):
        return g.quote_cost(self.eid(g, cid, 'hand')).amount

    def immune(self, g, player=1):
        return Keyword.IMMUNE in g.state.entities[g.state.players[player].hero_id].keywords

    def kill_two(self, g):
        self.play(g, KILL, self.eid(g, N))
        self.play(g, KILL, self.eid(g, N, player=2))

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'assemble_static_material_sources', 'original_quote'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_two_complete_rows_four_faces_exact_original_material_and_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 2); self.assertEqual(len(d['official_observations']), 4)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((new.cost, new.attack, new.health, new.metadata, new.keyword_auras, new.minion_death_cost),
                (old.cost, old.attack, old.health, old.metadata, old.keyword_auras, old.minion_death_cost))
            self.assertEqual(recipe_options(r, cid, cid), ())
        with self.assertRaises(TypeError): r.assemble_static_material_sources['x'] = r.assemble_static_material_sources[GHOST]

    def test_b_ghost_original_and_self_count_both_players_actual_current_turn_deaths_and_pay_once(self):
        for cid in (GHOST, recipe(GHOST)):
            g = self.game((cid, KILL, KILL), (N,), (N,))
            self.assertEqual(self.price(g, cid), 7); self.kill_two(g)
            self.assertEqual(self.price(g, cid), 5)
            mana = g.state.players[1].mana; self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, mana - 5)
            self.assertEqual(self.count(g, COIN), 2)

    def test_c_borrowed_death_price_uses_original_low_primary_cost_and_zero_floor(self):
        cid = recipe(LOOT, GHOST, 'top')
        g = self.game((cid, KILL, KILL), (N,), (N,))
        self.assertEqual(self.price(g, cid), 2)
        self.play(g, KILL, self.eid(g, N)); self.assertEqual(self.price(g, cid), 1)
        self.play(g, KILL, self.eid(g, N, player=2)); self.assertEqual(self.price(g, cid), 0)
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana); self.assertEqual(self.count(g, COIN), 1)

    def test_d_replacing_ghost_prefix_clears_old_intrinsic_price_without_changing_printed_cost(self):
        cid = recipe(GHOST, LOOT, 'top')
        g = self.game((cid, KILL, KILL), (N,), (N,)); self.kill_two(g)
        self.assertIsNone(g.registry.card(cid).minion_death_cost)
        self.assertEqual(self.price(g, cid), 7)

    def test_e_original_turn_price_resets_after_owner_and_opponent_end_and_restores(self):
        cid = recipe(GHOST); g = self.game((cid, KILL, KILL), (N,), (N,)); self.kill_two(g)
        self.assertEqual(self.price(g, cid), 5)
        g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.price(g, cid), 7); self.portable(g)

    def test_f_tich_original_and_self_keep_aura_and_actual_next_demon_zero_only_once(self):
        for cid in (TICH, recipe(TICH)):
            g = self.game((cid, OTHER, DEMON, DEMON)); mana = g.state.players[1].mana
            self.play(g, cid); self.assertEqual(g.state.players[1].mana, mana - 9)
            self.assertTrue(self.immune(g)); self.assertEqual(self.price(g, DEMON), 0)
            self.play(g, OTHER); self.assertEqual(self.price(g, DEMON), 0)
            mana = g.state.players[1].mana; self.play(g, DEMON)
            self.assertEqual(g.state.players[1].mana, mana); self.assertEqual(self.price(g, DEMON), 6)

    def test_g_aura_follows_controller_but_already_granted_zero_price_stays_with_original_player(self):
        cid = recipe(TICH); g = self.game((cid, GIVE, DEMON))
        source = self.play(g, cid); self.play(g, GIVE, source)
        self.assertFalse(self.immune(g)); self.assertTrue(self.immune(g, 2))
        self.assertEqual(self.price(g, DEMON), 0); self.play(g, DEMON)
        self.assertTrue(self.immune(g, 2)); self.portable(g)

    def test_h_silence_or_death_removes_aura_but_not_the_accepted_next_demon_modifier(self):
        cid = recipe(TICH)
        for action in (MUTE, KILL):
            g = self.game((cid, action, DEMON)); source = self.play(g, cid)
            self.assertTrue(self.immune(g)); self.play(g, action, source)
            self.assertFalse(self.immune(g)); self.assertEqual(self.price(g, DEMON), 0)

    def test_i_borrowed_aura_keeps_primary_stats_and_only_selected_draw_body(self):
        cid = recipe(LOOT, TICH, 'top')
        g = self.game((cid, DEMON)); source = self.play(g, cid)
        self.assertTrue(self.immune(g)); self.assertNotIn(Keyword.IMMUNE, g.state.entities[source].keywords)
        self.assertEqual((g.state.entities[source].attack, g.state.entities[source].max_health), (2, 1))
        self.assertEqual(self.count(g, COIN), 1); self.assertEqual(self.price(g, DEMON), 6)

    def test_j_replacing_tich_prefix_removes_aura_and_moves_only_zero_cost_body_to_death(self):
        cid = recipe(TICH, LOOT, 'top')
        g = self.game((cid, KILL, DEMON)); source = self.play(g, cid)
        self.assertFalse(self.immune(g)); self.assertEqual(g.registry.card(cid).keyword_auras, ())
        self.assertEqual(self.price(g, DEMON), 6)
        self.play(g, KILL, source); self.assertEqual(self.price(g, DEMON), 0)
        self.assertFalse(self.immune(g))

    def test_k_next_demon_zero_expires_normally_while_static_aura_stays_live(self):
        cid = recipe(TICH); g = self.game((cid, DEMON)); self.play(g, cid)
        self.assertEqual(self.price(g, DEMON), 0); g.apply(EndTurn(1)); g.apply(EndTurn(2))
        self.assertEqual(self.price(g, DEMON), 6); self.assertTrue(self.immune(g))

    def test_l_initial_board_or_copy_does_not_run_battlecry_but_retains_static_aura(self):
        cid = recipe(TICH); g = self.game((COPY, DEMON), (cid,)); source = self.eid(g, cid)
        self.assertTrue(self.immune(g)); self.assertEqual(self.price(g, DEMON), 6)
        self.play(g, COPY, source); self.assertEqual(self.count(g, cid, 'board'), 2)
        self.assertEqual(self.price(g, DEMON), 6); self.portable(g)

    def test_m_current_silenced_copy_stays_silenced_but_base_copy_restores_printed_material(self):
        cid = recipe(TICH); g = self.game((MUTE, COPY, BASE_COPY), (cid,)); source = self.eid(g, cid)
        self.play(g, MUTE, source); self.assertFalse(self.immune(g))
        self.play(g, COPY, source); self.assertFalse(self.immune(g))
        self.play(g, BASE_COPY, source); self.assertTrue(self.immune(g))

    def test_n_real_mismatch_aura_offer_keeps_low_primary_and_original_entry_on_board(self):
        cid = recipe(LOOT, TICH, 'top')
        g = self.game((MISMATCH, DEMON), mode='assemble'); self.play(g, MISMATCH)
        self.pick(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        self.assertEqual(self.count(g, MISMATCH, 'board'), 1)
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 2)
        self.assertTrue(self.immune(g)); self.assertEqual(self.price(g, DEMON), 6)
        self.portable(g, 'assemble')

    def test_o_real_mismatch_death_price_offer_uses_current_death_count_on_new_two_cost_card(self):
        cid = recipe(LOOT, GHOST, 'top')
        g = self.game((MISMATCH, KILL), (N,), mode='assemble'); self.play(g, KILL, self.eid(g, N))
        self.play(g, MISMATCH); self.pick(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        self.assertEqual(self.price(g, cid), 1)
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 1)
        self.assertEqual(self.count(g, COIN), 1)

    def test_p_missing_changed_empty_or_duplicate_complete_material_is_rejected(self):
        r = fixture.__wrapped__(); profile = r.assemble_static_material_sources[TICH]
        with self.assertRaises(ValueError): r.register_assemble_static_material_source(profile)
        with self.assertRaises(ValueError): AssembleStaticMaterialSource(TICH)
        with self.assertRaises(ValueError):
            r.register_assemble_static_material_source(replace(profile, keyword_auras=(replace(profile.keyword_auras[0], target='enemy_hero'),)))
        for cid in cards.SOURCES:
            r = fixture.__wrapped__(); r._assemble_static_material_sources.pop(cid)
            with self.assertRaises(ValueError): recipe_options(r, cid, cid)
        r = fixture.__wrapped__(); r._cards[TICH] = replace(r.card(TICH), health=r.card(TICH).health + 1)
        with self.assertRaises(TargetValidationError): cards.register_assemble_static_prefix_materials(r)

    def test_q_original_paid_death_price_receipt_survives_later_waiting_death_restore_and_rollback(self):
        cid = recipe(GHOST)
        g = self.game((cid, KILL), (WATCH, N), (N,)); self.play(g, KILL, self.eid(g, N))
        mana = g.state.players[1].mana; self.play(g, cid); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(g.state.players[1].mana, mana - 6)
        other = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other):
            self.pick(game, 'death')
            while game.state.pending_choice is not None: self.pick(game)
            self.assertEqual(game.state.players[1].mana, mana - 6)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.count(g, COIN), 2)


if __name__ == '__main__':
    unittest.main()
