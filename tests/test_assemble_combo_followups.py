"""Actual Combo and shared Battlecry/Combo/Deathrattle native source boundaries."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_combo_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, UseHeroPower)
from hs_sim.engine.assemble_faces import (AssemblePrefix, AssembleRecipe, AssembleSuffix,
    compatible, prefix_timings)
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import ChoiceOption, GainArmor, InvokeBehavior, RequestChoice, Summon
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, KILL, LOOT, N

DEFIAS, OPU = cards.SOURCES
TOKEN, FAN, AUCTION = cards.TOKEN, cards.FAN, cards.AUCTION
SHARK, BATTLECRY = 'TRL_092', 'CORE_UNG_809'
NOOP, WATCH, FAIL, SUMMON_OPU = ('k434.' + name for name in ('noop', 'watch', 'fail', 'summon_opu'))
CTX = GenerationContext('k434-explicit-two-real-rogue-sources-and-reviewed-draw', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k434.' + mode
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, on_play=NOOP, metadata=META))
    def fail(c): raise ResolutionError('K434 deliberate actual native Combo continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        if mode == 'token_wait':
            target = c.state.entities.get(c.event.target_id)
            if c.event.kind != 'minion_summoned' or target is None or target.card_id != TOKEN: return ()
        elif mode == 'draw_wait':
            if c.event.kind != 'card_drawn' or c.event.player_id != c.player_id: return ()
        else: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id)))),
            c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('minion_summoned', WATCH), TriggerSpec('card_drawn', WATCH))))
    r.register_behavior(SUMMON_OPU, lambda c: (Summon(c.player_id, recipe(OPU)),))
    r.register_card(CardDefinition(SUMMON_OPU, SUMMON_OPU, CardType.SPELL, on_play=SUMMON_OPU, metadata=META))
    if mode == 'assemble':
        r.register_pool(PoolDefinition(POOL_ID, 'k434-one-two-cost-primary-two-real-high-cost-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (DEFIAS, OPU, AUCTION)), complete=True))
    r.validate(); return r


class AssembleComboTests(unittest.TestCase):
    def game(self, hand=(), board=(), enemy=(), mode='normal', hero_power=None):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_03', hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50,
                mana_cap=50, hero_power_card_id=hero_power),
            PlayerSetup('HERO_08', board=enemy, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=434, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='board'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def count(self, g, cid, zone='board'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def play(self, g, cid, target=None):
        source = self.eid(g, cid, 'hand'); g.apply(PlayCard(1, source, target)); return source

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def drain(self, g):
        while g.state.pending_choice is not None: self.pick(g)

    def fans(self, g):
        return [cast for cast in g.state.cast_history if cast.card_id == FAN]

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'combo_acceptance', 'combo_submission_receipt_id'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_five_full_rows_ten_faces_exact_self_and_only_one_reviewed_timing_amendment(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 5); self.assertEqual(len(d['official_observations']), 10)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        for cid, row in rows.items(): self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual((new.cost, new.attack, new.health, new.metadata, new.keywords),
                (old.cost, old.attack, old.health, old.metadata, old.keywords))
            self.assertEqual((new.battlecry, new.combo, new.deathrattle), (old.battlecry, old.combo, old.deathrattle))
            self.assertEqual(recipe_options(r, cid, cid), ())
        expected = deepcopy(d['timing_amendment']['original_template'])
        expected['suffix']['allowed_timings'].append('combo')
        self.assertEqual(canonical_digest(asdict(r.assemble_templates[AUCTION])), canonical_digest(expected))
        self.assertEqual(prefix_timings(r.assemble_templates[OPU].prefix), ('battlecry', 'combo', 'deathrattle'))

    def test_b_defias_original_and_self_have_only_real_enabled_combo_and_one_payment(self):
        for cid in (DEFIAS, recipe(DEFIAS)):
            for enabled in (False, True):
                g = self.game((NOOP, cid))
                if enabled: self.play(g, NOOP)
                mana = g.state.players[1].mana; self.play(g, cid)
                self.assertEqual(g.state.players[1].mana, mana - 2)
                self.assertEqual(self.count(g, TOKEN), int(enabled))
                self.assertEqual(len(g.state.combo_history), int(enabled))
                self.assertFalse(g.state.battlecry_history)

    def test_c_hero_power_and_previous_turn_card_do_not_enable_current_combo(self):
        cid = recipe(DEFIAS); g = self.game((cid,), hero_power='HERO_03bp')
        g.apply(UseHeroPower(1, g.state.players[1].hero_power_id)); self.play(g, cid)
        self.assertEqual(self.count(g, TOKEN), 0); self.assertFalse(g.state.combo_history)
        g = self.game((NOOP, cid)); self.play(g, NOOP); g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, cid)
        self.assertEqual(self.count(g, TOKEN), 0); self.assertFalse(g.state.combo_history)

    def test_d_opu_original_and_self_cast_original_fan_for_bc_and_only_enabled_combo(self):
        for cid in (OPU, recipe(OPU)):
            for enabled in (False, True):
                g = self.game((NOOP, cid), enemy=(N,)); enemy = g.state.players[2].board[0]
                if enabled: self.play(g, NOOP)
                mana = g.state.players[1].mana; source = self.play(g, cid)
                expected = 2 if enabled else 1
                self.assertEqual(g.state.players[1].mana, mana - 6)
                self.assertEqual(len(self.fans(g)), expected)
                self.assertEqual(g.state.entities[enemy].damage, expected)
                self.assertEqual(self.count(g, COIN, 'hand'), expected)
                self.assertEqual(len(g.state.combo_history), int(enabled))
                self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords)
                self.assertTrue(all(cast.completed and cast.caster_id == source for cast in self.fans(g)))

    def test_e_natural_opu_death_casts_once_without_a_fabricated_combo(self):
        for cid in (OPU, recipe(OPU)):
            g = self.game((KILL,), (cid,), (N,)); self.play(g, KILL, self.eid(g, cid))
            self.assertEqual(len(self.fans(g)), 1); self.assertEqual(self.count(g, COIN, 'hand'), 1)
            self.assertFalse(g.state.combo_history)

    def test_f_borrowed_draw_body_keeps_only_combo_gate_and_never_summons_old_bandit(self):
        cid = recipe(DEFIAS, AUCTION)
        for enabled in (False, True):
            g = self.game((NOOP, cid))
            if enabled: self.play(g, NOOP)
            self.play(g, cid)
            self.assertEqual(self.count(g, COIN, 'hand'), int(enabled))
            self.assertEqual(self.count(g, TOKEN), 0)

    def test_g_borrowed_true_triple_prefix_runs_each_family_with_selected_bandit_body(self):
        cid = recipe(DEFIAS, OPU, 'top')
        g = self.game((NOOP, cid, KILL)); self.play(g, NOOP); source = self.play(g, cid)
        self.assertEqual(self.count(g, TOKEN), 2)
        self.assertIn(Keyword.STEALTH, g.state.entities[source].keywords)
        self.assertEqual(len(g.state.combo_history), 1); self.assertFalse(self.fans(g))
        self.play(g, KILL, source); self.assertEqual(self.count(g, TOKEN), 3)
        self.assertEqual(len(g.state.combo_history), 1)
        self.portable(g)

    def test_h_replacing_combo_prefix_clears_old_keyword_and_payload_but_keeps_independent_bandit(self):
        cid = recipe(DEFIAS, AUCTION, 'top')
        g = self.game((cid, NOOP)); held = self.eid(g, cid, 'hand')
        self.assertEqual(g.quote_hand_action(held, 'prepare').amount, 1)
        source = self.play(g, cid)
        self.assertIsNone(g.registry.card(cid).combo)
        self.assertNotIn(Keyword.COMBO, g.state.entities[source].keywords)
        self.play(g, NOOP); self.assertEqual(self.count(g, TOKEN), 1)
        self.assertFalse(g.state.combo_history)

    def test_i_independent_fan_body_as_battlecry_does_not_require_original_combo_or_six_cost(self):
        cid = recipe(BATTLECRY, OPU)
        g = self.game((cid,), enemy=(N,)); mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 1)
        self.assertEqual(len(self.fans(g)), 1); self.assertFalse(g.state.combo_history)

    def test_j_independent_bandit_body_as_natural_death_has_no_combo_guard(self):
        cid = recipe(LOOT, DEFIAS)
        g = self.game((KILL,), (cid,)); self.play(g, KILL, self.eid(g, cid))
        self.assertEqual(self.count(g, TOKEN), 1); self.assertFalse(g.state.combo_history)
        token = g.state.entities[self.eid(g, TOKEN)]
        self.assertEqual((token.attack, token.max_health), (2, 1))

    def test_k_summoning_shared_source_does_not_activate_bc_or_combo_but_retains_death(self):
        g = self.game((SUMMON_OPU, KILL)); self.play(g, SUMMON_OPU)
        self.assertFalse(self.fans(g)); self.assertFalse(g.state.combo_history)
        self.play(g, KILL, self.eid(g, recipe(OPU)))
        self.assertEqual(len(self.fans(g)), 1); self.assertFalse(g.state.combo_history)

    def test_l_existing_real_repeat_representative_keeps_bc_combo_and_death_independent(self):
        # Existing engine representative only; not a new Wild pool or delivery gate.
        cid = recipe(OPU)
        g = self.game((NOOP, cid, KILL), (SHARK,), (N,)); self.play(g, NOOP)
        mana = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 6)
        self.assertEqual(len(self.fans(g)), 4); self.assertEqual(len(g.state.combo_history), 2)
        self.play(g, KILL, source); self.assertEqual(len(self.fans(g)), 5)
        self.portable(g)

    def test_m_real_combo_token_wait_restores_and_bad_resume_rolls_back(self):
        cid = recipe(DEFIAS); g = self.game((NOOP, cid), (WATCH,), mode='token_wait')
        self.play(g, NOOP); self.play(g, cid); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'token_wait'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.count(g, TOKEN), 1); self.assertTrue(g.state.combo_history[-1].completed)

    def test_n_first_bc_fan_wait_retains_owed_combo_cast_and_native_private_records(self):
        cid = recipe(OPU); g = self.game((NOOP, cid), (WATCH,), mode='draw_wait')
        self.play(g, NOOP); self.play(g, cid); self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(self.fans(g)), 1)
        other = self.portable(g, 'draw_wait')
        for game in (g, other): self.drain(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(len(self.fans(g)), 2)
        self.assertTrue(g.state.combo_history[-1].completed)

    def test_o_complete_original_dependency_and_native_stage_drift_are_rejected(self):
        for cid in (DEFIAS, FAN, TOKEN):
            r = fixture.__wrapped__(); old = r.card(cid)
            r._cards[cid] = replace(old, cost=old.cost + 1)
            with self.assertRaises(TargetValidationError): cards.register_assemble_combo_followups(r)

    def test_p_keyword_coherence_and_unreviewed_eligible_combo_body_are_explicit(self):
        with self.assertRaises(ValueError): AssemblePrefix('combo')
        with self.assertRaises(ValueError): AssemblePrefix('battlecry', (Keyword.COMBO,))
        with self.assertRaises(ValueError):
            compatible(fixture().assemble_templates[DEFIAS].prefix, AssembleSuffix('old.body', ('battlecry',)))

    def test_q_real_mismatch_selects_reviewed_draw_and_uses_native_combo_payment(self):
        cid = recipe(DEFIAS, AUCTION)
        g = self.game((MISMATCH,), mode='assemble'); self.play(g, MISMATCH)
        self.pick(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        self.assertEqual(self.count(g, MISMATCH), 1)
        mana = g.state.players[1].mana; self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 2)
        self.assertEqual(self.count(g, COIN, 'hand'), 1); self.assertEqual(self.count(g, TOKEN), 0)
        self.assertTrue(g.state.combo_history[-1].completed)
        self.portable(g, 'assemble')

    def test_r_real_mismatch_triple_prefix_keeps_original_two_cost_primary_and_named_token(self):
        cid = recipe(DEFIAS, OPU, 'top')
        g = self.game((MISMATCH, KILL), mode='assemble'); self.play(g, MISMATCH)
        self.pick(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        source = self.play(g, cid); self.assertEqual(self.count(g, TOKEN), 2)
        self.assertEqual(self.count(g, MISMATCH), 1)
        self.play(g, KILL, source); self.assertEqual(self.count(g, TOKEN), 3)
        self.assertFalse(self.fans(g))


if __name__ == '__main__':
    unittest.main()
