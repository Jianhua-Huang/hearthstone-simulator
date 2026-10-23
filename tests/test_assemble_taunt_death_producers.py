"""Native printed-mana roots, original death slots and actual shared Void Souls."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import assemble_taunt_death_producers as cards
from hs_sim.cards.native_assemble_entry_cards import FLESH, POOL_ID
from hs_sim.engine import (CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Scenario, SelectChoice, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.assemble_faces import AssembleRecipe
from hs_sim.engine.assemble_offers import recipe_options
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, Destroy, GainArmor,
    InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.mana_worth_summons import ManaWorthEntryLink
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember
from hs_sim.engine.replay import build_replay, replay
from hs_sim.targets import TargetValidationError, canonical_digest
from tools.card_batch import check_face, sha
from test_assemble_damage_health_followups import fixture as base_fixture
from test_assemble_card_play_followups import META, COIN, N

MECH, NAGA = cards.SOURCES
SOUL = cards.SOUL
MECHS = ('CORE_GVG_085', 'TIME_015')
DEMONS = ('CORE_YOD_026', 'CORE_LOOT_013')
FIRE, DRAIN, CAIRNE, RUST = 'CORE_UNG_809', 'CORE_GIL_622', 'CORE_EX1_110', 'CORE_SW_072'
P = 'k439.'
KILL, MUTE, COPY, BASE_COPY, WATCH, FAIL, UNKNOWN = (
    P + k for k in ('kill', 'mute', 'copy', 'base_copy', 'watch', 'fail', 'unknown'))
CTX = GenerationContext('k439-complete-explicit-budget-and-soul-domains', 'experimental')


def recipe(primary, secondary=None, half='bottom'):
    return AssembleRecipe(primary, secondary or primary, half).card_id


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    r = base_fixture.__wrapped__('normal', role); r._version += '.k439.' + mode
    for cid, body in {KILL: lambda c: (Destroy(c.target_id, c.source_id),),
                     MUTE: lambda c: (Silence(c.target_id),),
                     COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='current'),),
                     BASE_COPY: lambda c: (CopyMinion(c.target_id, c.player_id, mode='base'),)}.items():
        r.register_behavior(cid, body)
        r.register_card(CardDefinition(cid, cid, CardType.SPELL, on_play=cid, metadata=META,
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,))))
    def fail(c): raise ResolutionError('K439 deliberate budget continuation failure')
    r.register_behavior(FAIL, fail)
    def watch(c):
        target = c.state.entities.get(c.event.target_id)
        if target is None or target.card_id not in MECHS: return ()
        return (RequestChoice(c.player_id, (ChoiceOption('go', 'Continue'),
            ChoiceOption('bad', 'Fail', (GainArmor(c.player_id, 1),
                InvokeBehavior(FAIL, c.source_id, c.player_id)))), c.source_id),)
    r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20, metadata=META,
        triggers=(TriggerSpec('minion_summoned', WATCH),)))
    if mode != 'no_pool':
        members = MECHS+DEMONS+(COIN,)
        if mode == 'unknown':
            r.register_pool_card(replace(r.pool_card(MECHS[0]), card_id=UNKNOWN)); members += (UNKNOWN,)
        r.register_pool(PoolDefinition('constructed.cards', 'k439-two-two-cost-mechs-two-original-demon-tiers',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    if mode in ('mech_offer', 'naga_offer'):
        members = (MECH, DRAIN, CAIRNE) if mode == 'mech_offer' else (NAGA, DRAIN, RUST)
        r.register_pool(PoolDefinition(POOL_ID, 'k439-current-class-real-death-primary-and-two-donors',
            CTX.target_id, CTX.mode, tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate(); return r


class AssembleTauntDeathTests(unittest.TestCase):
    def game(self, hand=(), board=(), mode='normal'):
        hero = 'HERO_10' if mode == 'naga_offer' else 'HERO_05'
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, board=board, deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50),
            PlayerSetup('HERO_08', deck=(COIN,) * 24, mana=50, max_mana=50, mana_cap=50)),
            seed=1, generation_context=CTX), fixture(mode))

    def eid(self, g, cid, zone='hand'):
        return next(i for i in getattr(g.state.players[1], zone) if g.state.entities[i].card_id == cid)

    def play(self, g, cid, target=None):
        source = self.eid(g, cid); g.apply(PlayCard(1, source, target)); return source

    def count(self, g, cid, zone='hand'):
        return sum(g.state.entities[i].card_id == cid for i in getattr(g.state.players[1], zone))

    def mech_ids(self, g):
        return [i for i in g.state.players[1].board if g.state.entities[i].card_id in MECHS]

    def budgets(self, g):
        return [r for r in g.state.card_summon_history if type(r.request.producer_link) is ManaWorthEntryLink]

    def pick(self, g, key='go'):
        q = g.state.pending_choice; g.apply(SelectChoice(q.player_id, q.id, (key,)))

    def portable(self, g, mode='normal'):
        saved = json.loads(json.dumps(g.snapshot())); reader = fixture(mode, 'reader')
        self.assertIsNot(reader, g.registry); other = Game.from_snapshot(saved, reader)
        self.assertEqual(other.snapshot(), saved); self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), reader).snapshot(), saved)
        for player in (1, 2):
            public = json.dumps(g.for_player(player).observe()) + json.dumps(g.player_events(player))
            for key in ('rng_state', 'resolution_frame', 'ManaWorthEntryLink', 'primary_candidates'):
                self.assertNotIn('"' + key + '"', public)
        return other

    def test_a_complete_three_records_six_faces_exact_originals_and_true_self_noops(self):
        d = cards.load_batch(); r = fixture(); rows = {x['record']['id']: x for x in d['existing_dependencies']}
        self.assertEqual(len(rows), 3); self.assertEqual(len(d['official_observations']), 6)
        for o in d['official_observations']:
            self.assertEqual(sha(o['response_file']), o['response_sha256'])
            check_face(rows[o['card_id']]['record'], o['face'], o['locale'],
                display_normalizations=d['display_normalizations'].get(o['card_id']))
        for cid in cards.SOURCES:
            old = r.card(cid); new = r.card(recipe(cid))
            self.assertEqual(canonical_digest(asdict(old)), rows[cid]['definition_sha256'])
            self.assertEqual((new.cost, new.attack, new.health, new.keywords, new.metadata, new.deathrattle),
                (old.cost, old.attack, old.health, old.keywords, old.metadata, old.deathrattle))
            self.assertEqual(recipe_options(r, cid, cid), ())

    def test_b_original_and_self_mech_pay_once_keep_taunt_and_original_middle_death_slots(self):
        for cid in (MECH, recipe(MECH)):
            g = self.game((cid, KILL), (N, N)); left, right = g.state.players[1].board
            source = self.eid(g, cid); g.apply(PlayCard(1, source, position=1))
            self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)
            self.assertEqual(g.state.players[1].mana, 46); self.play(g, KILL, source)
            self.assertEqual(g.state.players[1].board[0], left); self.assertEqual(len(self.mech_ids(g)), 2)
            self.assertEqual(g.state.players[1].board[-1], right)
            self.assertEqual(g.state.players[1].board[1:3], self.mech_ids(g))
            self.assertEqual([r.request.producer_link.remaining for r in self.budgets(g)], [4, 2])
            self.assertEqual(sum(g.registry.card(g.state.entities[i].card_id).cost for i in self.mech_ids(g)), 4)

    def test_c_borrowed_mech_battlecry_uses_native_budget_without_death_position_or_old_taunt(self):
        cid = recipe(DRAIN, MECH); g = self.game((cid,)); source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, 46); self.assertEqual(len(self.mech_ids(g)), 2)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[source].keywords)
        self.assertTrue(all(r.request.position is None for r in self.budgets(g)))
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 30)

    def test_d_mech_prefix_keeps_taunt_but_selected_cairne_death_does_not_run_budget(self):
        cid = recipe(MECH, CAIRNE); g = self.game((cid, KILL), mode='no_pool'); source = self.play(g, cid)
        self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords); self.play(g, KILL, source)
        self.assertFalse(self.budgets(g)); self.assertEqual(len(g.state.players[1].board), 1)

    def test_e_original_and_self_naga_add_complete_actual_soul_without_pool_or_progress(self):
        for cid in (NAGA, recipe(NAGA)):
            g = self.game((cid, KILL), mode='no_pool'); source = self.play(g, cid)
            self.assertEqual(g.state.players[1].mana, 47); self.assertIn(Keyword.TAUNT, g.state.entities[source].keywords)
            self.play(g, KILL, source); self.assertEqual(self.count(g, SOUL), 1)
            self.assertFalse(any(e.spec_id == cards.PREFIX+'soul_progress' for e in g.state.players[1].player_effects))

    def test_f_borrowed_soul_battlecry_has_no_old_taunt_or_death_and_no_native_death_guard(self):
        cid = recipe(FIRE, NAGA); g = self.game((cid,), mode='no_pool'); source = self.play(g, cid)
        self.assertEqual(self.count(g, SOUL), 1); self.assertNotIn(Keyword.TAUNT, g.state.entities[source].keywords)
        self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_g_naga_prefix_runs_only_selected_damage_body_without_soul_or_pool(self):
        cid = recipe(NAGA, DRAIN); g = self.game((cid, KILL), mode='no_pool'); source = self.play(g, cid)
        self.play(g, KILL, source); self.assertEqual(self.count(g, SOUL), 0)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health, 27)

    def test_h_two_souls_from_different_real_sources_cast_at_shared_original_demon_tiers(self):
        cid = recipe(NAGA); second = recipe(FIRE, NAGA)
        g = self.game((cid, second, KILL)); source = self.play(g, cid); self.play(g, KILL, source)
        self.play(g, SOUL); self.assertEqual(self.count(g, DEMONS[0], 'board'), 1)
        self.play(g, second); self.play(g, SOUL)
        self.assertEqual(self.count(g, DEMONS[1], 'board'), 1)
        self.assertEqual(sum(e.spec_id == cards.PREFIX+'soul_progress' for e in g.state.players[1].player_effects), 2)

    def test_i_missing_or_eligible_unknown_mech_rolls_back_whole_play_or_death_and_rng(self):
        for mode in ('no_pool', 'unknown'):
            live = recipe(DRAIN, MECH); g = self.game((live,), mode=mode); saved = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): self.play(g, live)
            self.assertEqual(g.snapshot(), saved)
            cid = recipe(MECH); g = self.game((KILL,), (cid,), mode=mode); saved = g.snapshot()
            with self.assertRaises((ValueError, ResolutionError)): self.play(g, KILL, self.eid(g, cid, 'board'))
            self.assertEqual(g.snapshot(), saved)

    def test_j_silenced_current_copy_has_no_budget_base_copy_keeps_new_printed_death(self):
        cid = recipe(MECH); g = self.game((MUTE, COPY, BASE_COPY, KILL, KILL), (cid,))
        source = self.eid(g, cid, 'board'); self.play(g, MUTE, source)
        before = set(g.state.players[1].board); self.play(g, COPY, source)
        current = (set(g.state.players[1].board)-before).pop()
        before = set(g.state.players[1].board); self.play(g, BASE_COPY, source)
        base = (set(g.state.players[1].board)-before).pop()
        self.play(g, KILL, current); self.assertFalse(self.budgets(g))
        self.play(g, KILL, base); self.assertEqual(len(self.mech_ids(g)), 2)

    def test_k_wait_after_first_budget_pick_restores_and_never_resamples_on_failed_resume(self):
        cid = recipe(MECH); g = self.game((KILL,), (WATCH, cid)); self.play(g, KILL, self.eid(g, cid, 'board'))
        reader = self.portable(g); saved = g.snapshot()
        with self.assertRaises(ResolutionError): self.pick(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        while g.state.pending_choice is not None:self.pick(g)
        while reader.state.pending_choice is not None:self.pick(reader)
        self.assertEqual(g.snapshot(), reader.snapshot()); self.assertEqual(len(self.mech_ids(g)), 2)
        self.assertEqual([r.request.producer_link.remaining for r in self.budgets(g)], [4, 2])

    def test_l_real_flesh_offer_keeps_primary_cost_and_native_budget_with_new_non_taunt_prefix(self):
        cid = recipe(MECH, DRAIN, 'top'); g = self.game((FLESH, KILL), mode='mech_offer')
        entry = self.play(g, FLESH); self.portable(g, 'mech_offer')
        q = g.state.pending_choice
        self.assertIn(cid, [o.card_id for o in q.options])
        self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        before = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, before-4); self.assertNotIn(Keyword.TAUNT, g.state.entities[source].keywords)
        self.assertIsNone(g.registry.card(cid).deathrattle); self.assertEqual(len(self.mech_ids(g)), 2)
        self.assertEqual(g.state.entities[entry].zone, Zone.GRAVEYARD); self.play(g, KILL, source)
        self.assertEqual(len(self.mech_ids(g)), 2)

    def test_m_real_flesh_offer_borrowed_battlecry_runs_soul_body_with_no_death_or_taunt(self):
        cid = recipe(NAGA, RUST, 'top'); g = self.game((FLESH,), mode='naga_offer'); self.play(g, FLESH)
        q = g.state.pending_choice; self.pick(g, next(o.id for o in q.options if o.card_id == cid))
        before = g.state.players[1].mana; source = self.play(g, cid)
        self.assertEqual(g.state.players[1].mana, before-3); self.assertEqual(self.count(g, SOUL), 1)
        self.assertNotIn(Keyword.TAUNT, g.state.entities[source].keywords); self.assertIsNone(g.registry.card(cid).deathrattle)

    def test_n_complete_original_soul_progress_and_native_death_callback_are_strict(self):
        r = fixture(); t = r.assemble_templates[MECH]
        self.assertEqual(t.suffix.deathrattle_behavior_id, r.card(MECH).deathrattle)
        self.assertEqual(t.suffix.behavior_id, cards.MECH_BODY)
        broken = fixture.__wrapped__(); broken._cards[SOUL] = replace(broken.card(SOUL), cost=2)
        with self.assertRaises(TargetValidationError): cards.register_assemble_taunt_death_producers(broken)
        before = r.fingerprint(); self.assertEqual(recipe_options(r, MECH, MECH), ())
        self.assertEqual(r.fingerprint(), before)


if __name__ == '__main__':
    unittest.main()
