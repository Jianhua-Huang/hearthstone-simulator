"""Actual shared and independent death clauses retain separate native windows."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_dual_minion_play_followups as cards
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.native_assemble_entry_cards import POOL_ID
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe, prefix_timings, printed_face
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior, RequestChoice, ReturnToHand, Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_history import from_event
from hs_sim.engine.model import Rarity
from hs_sim.engine.pools import GenerationContext, PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.registry import RuleContext, UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, KILL, LOOT

DEVOURER, REX, BOOK = cards.SOURCES
RUNNER, PREPPER, QUEEN = 'CORE_BT_480', 'TIME_021', 'TLC_903'
CHALLENGER, BATTLECRY = 'TLC_251', 'CORE_UNG_809'
P = 'k433.'
BEAST, ELEMENTAL, NOOP, WATCH, FAIL, UNKNOWN, SUMMON_BOOK = (
    P + name for name in ('beast', 'elemental', 'noop', 'watch', 'fail', 'unknown', 'summon_book'))
CTX = GenerationContext('k433-explicit-complete-play-death-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k433.' + mode
    for cid, tribe in ((BEAST, 'beast'), (ELEMENTAL, 'elemental')):
        r.register_card(CardDefinition(cid, cid, CardType.MINION, health=20, metadata=replace(META, tribes=(tribe,))))
    r.register_behavior(NOOP, lambda c: ())
    r.register_card(CardDefinition(NOOP, NOOP, CardType.SPELL, on_play=NOOP, metadata=META))
    def fail(c): raise ResolutionError('K433 deliberate actual shared-body continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        if mode == 'hand_wait' and c.event.kind == 'hand_card_entered':
            row = from_event(c.state, c.event)
            if row.player_id != c.player_id or row.card_id not in (RUNNER, LOOT): return ()
            options = (ChoiceOption('go', 'Continue'), ChoiceOption('bad', 'Fail',
                (GainArmor(c.player_id, 1), InvokeBehavior(FAIL, c.source_id, c.player_id))))
        elif mode == 'entry_wait' and c.event.kind == 'minion_summoned':
            target = c.event.target_id
            if not any(p.source_id == target and p.card_id == recipe(BOOK) and not p.completed
                    for p in c.state.play_history): return ()
            options = (ChoiceOption('go', 'Stay'), ChoiceOption('bounce', 'Return original source', (ReturnToHand(target),)))
        else: return ()
        return (RequestChoice(c.player_id, options, c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('hand_card_entered', WATCH), TriggerSpec('minion_summoned', WATCH))))
    r.register_behavior(SUMMON_BOOK, lambda c: (Summon(c.player_id, recipe(BOOK)),))
    r.register_card(CardDefinition(SUMMON_BOOK, SUMMON_BOOK, CardType.SPELL, on_play=SUMMON_BOOK, metadata=META))
    members = (RUNNER, LOOT)
    if mode == 'unknown':
        missing = CardDefinition(UNKNOWN, UNKNOWN, CardType.MINION, cost=1, health=1,
            deathrattle=NOOP, keywords=(Keyword.OUTCAST,),
            metadata=replace(META, collectible=True, rarity=Rarity.COMMON, deck_identity=UNKNOWN))
        r.register_pool_card(PoolCard.from_definition(missing)); members += (UNKNOWN,)
    if mode != 'no_pool':
        r.register_pool(PoolDefinition(cards.load_batch()['pool_id'], 'k433-complete-outcast-and-deathrattle-domains',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode == 'assemble':
        r.register_pool(PoolDefinition(POOL_ID, 'k433-three-cost-primary-two-current-five-cost-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in (DEVOURER, PREPPER, QUEEN)), complete=True))
    r.validate(); return r


class AssembleDualMinionPlayTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='normal'):
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_10', hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=433, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='board'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def count(self, g, cid, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def play(self, g, cid, target=None):
        source = self.eid(g, cid, 'hand'); g.apply(PlayCard(1, source, target)); return source

    def cycle(self, g):
        g.apply(EndTurn(1)); g.apply(EndTurn(2))

    def prime(self, cid, primer=BEAST, rest=(), board=(), mode='normal'):
        g = self.game((primer, cid, *rest), board, mode)
        self.play(g, primer); self.cycle(g); return g

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.player_events(p))
            for key in ('rng_state', 'resolution_frame', 'condition_id', 'assemble_on_play_death_sources'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_three_full_rows_six_faces_complete_sources_and_canonical_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 3); self.assertEqual(len(d['official_observations']), 6)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'])
        from hs_sim.engine.assemble_offers import recipe_options
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((new.cost, new.attack, new.health, new.metadata, new.keywords),
                (old.cost, old.attack, old.health, old.metadata, old.keywords))
            self.assertEqual(recipe_options(r, cid, cid), ())
            self.assertIsNone(new.battlecry)
        self.assertEqual(prefix_timings(r.assemble_templates[DEVOURER].prefix), ('on_play', 'deathrattle'))
        self.assertEqual(prefix_timings(r.assemble_templates[BOOK].prefix), ('on_play',))

    def test_b_devourer_original_and_self_outcast_positions_and_unconditional_death(self):
        for cid in (DEVOURER, recipe(DEVOURER)):
            for hand, expected in (((cid, KILL, NOOP), 1), ((KILL, NOOP, cid), 1), ((NOOP, cid, KILL), 0)):
                with self.subTest(cid=cid, hand=hand):
                    g = self.game(hand); source = self.play(g, cid)
                    self.assertEqual(self.count(g, RUNNER), expected)
                    self.assertFalse(g.state.kindred_history)
                    self.play(g, KILL, source)
                    self.assertEqual(self.count(g, RUNNER), expected + 1)

    def test_c_rex_original_and_self_match_previous_beast_and_keep_discount_on_each_real_card(self):
        for cid in (REX, recipe(REX)):
            g = self.prime(cid, rest=(KILL,)); source = self.play(g, cid)
            self.assertEqual(self.count(g, LOOT), 1)
            self.assertTrue(g.state.kindred_history[-1].condition.matched)
            self.play(g, KILL, source)
            self.assertEqual(self.count(g, LOOT), 2)
            for eid in g.state.players[1].hand:
                if g.state.entities[eid].card_id == LOOT: self.assertEqual(g.quote_cost(eid).amount, 0)
            self.assertEqual(len(g.state.kindred_history), 1)

    def test_d_unqualified_kindred_does_not_gate_death_or_consume_later_next_kindred_source(self):
        cid = recipe(REX); g = self.game((cid, CHALLENGER, KILL)); source = self.play(g, cid)
        self.assertFalse(g.state.kindred_history[-1].condition.matched); self.assertEqual(self.count(g, LOOT), 0)
        self.play(g, CHALLENGER); pending = tuple(g.state.players[1].player_effects)
        self.play(g, KILL, source)
        self.assertEqual(self.count(g, LOOT), 1)
        self.assertEqual(tuple(g.state.players[1].player_effects), pending)
        self.assertEqual(len(g.state.kindred_history), 1)

    def test_e_next_kindred_doubles_only_play_component_and_death_still_runs_once(self):
        cid = recipe(REX); g = self.prime(cid, rest=(CHALLENGER, KILL))
        self.play(g, CHALLENGER); source = self.play(g, cid)
        self.assertEqual(self.count(g, LOOT), 2)
        self.assertEqual(g.state.kindred_history[-1].repetitions, 2)
        self.play(g, KILL, source); self.assertEqual(self.count(g, LOOT), 3)
        self.assertFalse(g.state.players[1].player_effects)
        self.portable(g)

    def test_f_librarian_original_and_self_copy_once_and_keep_separate_spell_draw_death(self):
        for cid in (BOOK, recipe(BOOK)):
            g = self.prime(cid, ELEMENTAL, rest=(KILL,)); source = self.play(g, cid)
            self.assertEqual(self.count(g, cid, 'board'), 2)
            self.assertEqual(len(g.state.kindred_history), 1)
            before = self.count(g, COIN); self.play(g, KILL, source)
            self.assertEqual(self.count(g, COIN), before + 1)
            self.assertEqual(self.count(g, cid, 'board'), 1)

    def test_g_replacing_librarian_suffix_keeps_prefix_death_spell_draw_and_kindred(self):
        cid = recipe(BOOK, PREPPER)
        g = self.prime(cid, ELEMENTAL, rest=(KILL,)); source = self.play(g, cid)
        hero = g.state.players[1].hero_id
        self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.assertEqual(g.registry.card(cid).deathrattle, g.registry.card(BOOK).deathrattle)
        before = self.count(g, COIN); self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN), before + 1)
        self.cycle(g); self.assertNotIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.portable(g)

    def test_h_borrowed_librarian_prefix_uses_primary_beast_and_replaces_old_shared_death(self):
        cid = recipe(DEVOURER, BOOK, 'top')
        for primer, expected in ((BEAST, 1), (ELEMENTAL, 0)):
            g = self.prime(cid, primer, rest=(KILL,)); source = self.play(g, cid)
            self.assertEqual(self.count(g, RUNNER), expected)
            before = self.count(g, COIN); self.play(g, KILL, source)
            self.assertEqual(self.count(g, RUNNER), expected)
            self.assertEqual(self.count(g, COIN), before + 1)

    def test_i_copy_suffix_as_battlecry_is_guard_free_and_summoned_copy_does_not_reactivate(self):
        cid = recipe(BATTLECRY, BOOK)
        g = self.game((cid,)); self.play(g, cid)
        self.assertEqual(self.count(g, cid, 'board'), 2)
        self.assertFalse(g.state.kindred_history)
        self.assertEqual(len(g.state.battlecry_history), 1)
        self.portable(g)

    def test_j_copy_suffix_death_context_has_a_real_body_and_no_pending_timing(self):
        r = fixture()
        self.assertIsNotNone(r.card(recipe(LOOT, BOOK)).deathrattle)
        self.assertEqual(r.assemble_templates[BOOK].suffix.pending_timings, ())

    def test_k_direct_summon_does_not_copy_but_retains_original_prefix_deathrattle(self):
        g = self.game((SUMMON_BOOK, KILL)); self.play(g, SUMMON_BOOK)
        cid = recipe(BOOK); source = self.eid(g, cid)
        self.assertEqual(self.count(g, cid, 'board'), 1); self.assertFalse(g.state.kindred_history)
        before = self.count(g, COIN); self.play(g, KILL, source)
        self.assertEqual(self.count(g, COIN), before + 1)

    def test_l_shared_kindred_generation_wait_is_portable_and_bad_resume_is_atomic(self):
        cid = recipe(REX); g = self.prime(cid, board=(WATCH,), mode='hand_wait'); self.play(g, cid)
        self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'hand_wait'); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.count(g, LOOT), 1)

    def test_m_natural_death_generation_wait_retains_death_and_does_not_start_kindred(self):
        cid = recipe(REX); g = self.game((KILL,), (WATCH, cid), 'hand_wait')
        self.play(g, KILL, self.eid(g, cid)); self.assertIsNotNone(g.state.pending_choice)
        self.assertFalse(g.state.kindred_history)
        other = self.portable(g, 'hand_wait')
        for game in (g, other): self.pick(game)
        self.assertEqual(g.snapshot(), other.snapshot()); self.assertEqual(self.count(g, LOOT), 1)

    def test_n_original_entry_wait_bounce_does_not_copy_a_departed_librarian(self):
        cid = recipe(BOOK); g = self.prime(cid, ELEMENTAL, board=(WATCH,), mode='entry_wait')
        self.play(g, cid); self.assertIsNotNone(g.state.pending_choice)
        other = self.portable(g, 'entry_wait')
        for game in (g, other): self.pick(game, 'bounce')
        self.assertEqual(g.snapshot(), other.snapshot())
        self.assertEqual(self.count(g, cid, 'board'), 0); self.assertEqual(self.count(g, cid), 1)

    def test_o_missing_or_eligible_unknown_generation_pool_rolls_back_play_and_death_roots(self):
        for mode in ('no_pool', 'unknown'):
            g = self.game((recipe(DEVOURER),), mode=mode); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, recipe(DEVOURER))
            self.assertEqual(g.snapshot(), saved)
            g = self.game((KILL,), (recipe(REX),), mode); saved = g.snapshot()
            with self.assertRaises(ResolutionError): self.play(g, KILL, self.eid(g, recipe(REX)))
            self.assertEqual(g.snapshot(), saved)

    def test_p_complete_originals_profiles_and_independent_prefix_material_are_strict(self):
        r = fixture(); t = r.assemble_templates[BOOK]
        with self.assertRaises(ValueError): printed_face(r.card(BOOK), t.prefix, t.suffix, BOOK)
        with self.assertRaises(TypeError): r.assemble_on_play_death_sources['x'] = r.assemble_on_play_death_sources[BOOK]
        for cid in (DEVOURER, REX, BOOK):
            r = fixture.__wrapped__(); r._cards[cid] = replace(r.card(cid), health=r.card(cid).health + 1)
            with self.assertRaises(TargetValidationError): cards.register_assemble_dual_minion_play_followups(r)
        r = fixture.__wrapped__(); p = r.assemble_on_play_death_sources[BOOK]
        with self.assertRaises(ValueError): r.register_assemble_on_play_death_source(p)
        with self.assertRaises(ValueError):
            r.register_assemble_on_play_death_source(replace(p, prefix_deathrattle_id=cards.COPY))

    def test_q_shared_unconditional_bodies_keep_full_original_query_and_discount(self):
        d = cards.load_batch(); r = fixture(); g = self.game(board=(recipe(DEVOURER), recipe(REX)))
        for cid in (DEVOURER, REX):
            source = self.eid(g, recipe(cid)); effects = r.behavior(r.assemble_templates[cid].suffix.behavior_id)(
                RuleContext(g.state, source, 1))
            self.assertEqual(len(effects), 1); effect = effects[0]
            self.assertEqual(effect.pool_id, d['pool_id'])
            self.assertEqual(canonical_digest(asdict(effect.query)), d['generation_query_sha256'][cid])
            if cid == REX: self.assertEqual(effect.cost.delta, -2)
            else: self.assertIsNone(effect.cost)

    def test_r_real_mismatch_uses_shared_outcast_death_prefix_with_original_hero_deadline(self):
        cid = recipe(DEVOURER, PREPPER)
        g = self.game((MISMATCH, KILL), mode='assemble'); self.play(g, MISMATCH)
        self.pick(g, next(o.id for o in g.state.pending_choice.options if o.card_id == cid))
        self.assertEqual(self.count(g, MISMATCH, 'board'), 1)
        mana = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, mana - 3)
        hero = g.state.players[1].hero_id; self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.play(g, KILL, source); self.assertIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.cycle(g); self.assertNotIn(Keyword.IMMUNE, g.state.entities[hero].keywords)
        self.portable(g, 'assemble')


if __name__ == '__main__':
    unittest.main()
