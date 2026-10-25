"""Narrow local exclusions through real Assemble entries and saved choices."""
from dataclasses import asdict, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards import build_registry
from hs_sim.cards.assemble_local_restrictions import load_policy
from hs_sim.cards.native_assemble_entry_cards import POOL_ID, FLESH, SHAPER
from hs_sim.cards.assemble_source_exception_cards import MISMATCH
from hs_sim.cards.rajh_card import CARD as RAJH, POWER, POOL as RAJH_POOL
from hs_sim.engine import Game, Keyword, PlayerSetup, Scenario, SnapshotError
from hs_sim.engine.assemble_faces import (AssemblePrefix, AssembleRecipe, DUAL_TIMING,
    COMBO_TRIPLE_TIMING, recipe_from_id)
from hs_sim.engine.assemble_offers import Assemble, candidates, draw, recipe_options, validate_offer
from hs_sim.engine.assemble_restrictions import (AssembleLocalRestriction,
    suffix_restriction)
from hs_sim.engine.errors import IllegalAction
from hs_sim.engine.pools import GenerationContext, PoolDefinition, PoolMember, PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from card_batch_testkit import CardBatchTestMixin

REDEEMER, OOZE, ILLUSION, ZEO = 'CATA_478', 'BE_734', 'EDR_780', 'BE_790'
GOLEM, CAIRNE, CURATOR = 'BE_861', 'CORE_EX1_110', 'CORE_KAR_061'
CTX = GenerationContext('k538-explicit-local-restriction-fixtures', 'experimental')


def recipe(a, b, half='bottom'):
    return AssembleRecipe(a, b, half).card_id


@lru_cache(maxsize=None)
def fixture(mode='flesh4', role='writer'):
    r = build_registry()
    r._version += '.k538.'+mode
    members = {
        'flesh4': (GOLEM, OOZE, REDEEMER, CURATOR),
        'flesh2': ('JAIL_328', ILLUSION, OOZE, 'CORE_UNG_084'),
        'shaper': (REDEEMER, CAIRNE, CURATOR),
        'zeo': (ILLUSION, 'CORE_EX1_096', 'CORE_GIL_622', CAIRNE, CURATOR, ZEO),
        'zeo_only': (ZEO,),
        'rajh': ('BE_152', 'CORE_ICC_210', 'TIME_428', ZEO),
    }[mode]
    pool = RAJH_POOL if mode == 'rajh' else POOL_ID
    r.register_pool(PoolDefinition(pool, 'k538-local-fixture', CTX.target_id, CTX.mode,
        tuple(PoolMember(cid) for cid in members), complete=True))
    r.validate()
    return r


class AssembleLocalRestrictionTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode='flesh4', card=FLESH):
        self.mode = mode
        hero = 'HERO_09' if mode in ('zeo', 'zeo_only') else 'HERO_04'
        return Game.from_scenario(Scenario((PlayerSetup(hero, hand=(card,),
            deck=('GAME_005',)*8, mana=30, max_mana=30, mana_cap=40),
            PlayerSetup('HERO_08', deck=('GAME_005',)*8)), seed=1,
            generation_context=CTX), fixture(mode))

    def offer(self, game):
        return game._frame.options[0].effects[0].offer

    def assert_safe(self, game):
        for option in game.state.pending_choice.options:
            face = game.registry.card(option.card_id)
            identity = recipe_from_id(option.card_id)
            self.assertNotIn(ZEO, (identity.primary_card_id, identity.secondary_card_id))
            if face.deathrattle is not None:
                suffix_id = identity.secondary_card_id if identity.half == 'bottom' else identity.primary_card_id
                self.assertNotIn(suffix_id, (REDEEMER, OOZE, ILLUSION))

    def test_policy_pins_four_complete_ordinary_cards_without_global_bans(self):
        r = fixture(); data = load_policy()
        self.assertFalse(data['official_ban'])
        self.assertEqual(set(r.assemble_local_restrictions), {REDEEMER, OOZE, ILLUSION, ZEO})
        for row in data['entries']:
            cid = row['profile']['card_id']
            self.assertEqual(canonical_digest(row['record']), row['record_sha256'])
            self.assertEqual(canonical_digest(asdict(r.card(cid))), row['definition_sha256'])
            self.assertEqual(r.pool_cards[cid].card_id, cid)
            self.assertNotIn(cid, r.fabled_generation_exclusions)
        with self.assertRaises(TypeError): r.assemble_local_restrictions[ZEO] = None

    def test_both_half_directions_keep_safe_opposite_and_live_self_faces(self):
        r = fixture()
        for source, death in ((REDEEMER, GOLEM), (OOZE, CAIRNE), (ILLUSION, 'JAIL_328')):
            with self.subTest(source=source):
                self.assertEqual(tuple(h for h,_ in recipe_options(r, death, source)), ('top',))
                self.assertEqual(tuple(h for h,_ in recipe_options(r, source, death)), ('bottom',))
                for a,b,h in ((death,source,'bottom'), (source,death,'top')):
                    with self.assertRaisesRegex(UnsupportedDefinitionError, 'Locally restricted.*deathrattle'):
                        r.card(recipe(a,b,h))
                for h in ('top','bottom'):
                    face = recipe(source,source,h)
                    self.assertEqual(asdict(r.card(face)), asdict(r.card(source)) | {'id':face})
        for timing in (DUAL_TIMING, COMBO_TRIPLE_TIMING):
            prefix = AssemblePrefix(timing, (Keyword.COMBO,) if timing == COMBO_TRIPLE_TIMING else ())
            self.assertIsNotNone(suffix_restriction(r, prefix, OOZE))

    def test_true_flesh_offers_finish_and_resume_with_safe_halves(self):
        for mode in ('flesh4', 'flesh2'):
            with self.subTest(mode=mode):
                g = self.game(mode); self.play(g, FLESH)
                self.assertEqual(g.state.players[1].mana, 27)
                self.assert_safe(g)
                restored = self.portable(g)
                option = g.state.pending_choice.options[0]
                saved = g.snapshot(); rng = saved['rng_state']
                with self.assertRaises(IllegalAction): self.choose(g, 'restricted-no-such-choice')
                self.assertEqual(g.snapshot(), saved)
                for current in (g, restored): self.choose(current, option.id)
                self.assertEqual(g.snapshot(), restored.snapshot())
                self.assertEqual(g.snapshot()['rng_state'], rng)
                result = self.entity(g, option.card_id)
                face = g.registry.card(option.card_id)
                self.assertEqual((result.attack,result.max_health), (face.attack+2,face.health+2))
                self.portable(g)

    def test_shaper_keeps_redeemer_primary_but_omits_death_prefix_option(self):
        g = self.game('shaper', SHAPER); self.play(g, SHAPER)
        offer = self.offer(g)
        self.assertEqual(offer.primary_card_id, REDEEMER)
        self.assertIn(CAIRNE, offer.secondary_candidates)
        self.assert_safe(g)
        self.assertNotIn(recipe(REDEEMER, CAIRNE, 'top'),
            {o.card_id for o in g.state.pending_choice.options})
        self.assertIn(recipe(REDEEMER, CAIRNE),
            {o.card_id for o in g.state.pending_choice.options})
        self.portable(g)

    def test_zeo_excluded_in_both_roles_before_missing_template_but_normal_face_remains(self):
        g = self.game('zeo', MISMATCH); r = g.registry
        spec = Assemble(1, POOL_ID, self.entity(g, MISMATCH).id,
            primary_query=PoolQuery(min_cost=8,max_cost=8))
        self.assertEqual(candidates(r, CTX, g.state, spec), ())
        secondary = candidates(r, CTX, g.state, replace(spec, secondary_min_cost=5), ILLUSION)
        self.assertEqual({c.card_id for c in secondary}, {CAIRNE,CURATOR})
        self.assertEqual(recipe_options(r, ZEO, CURATOR), ())
        self.assertEqual(recipe_options(r, CURATOR, ZEO), ())
        for a,b in ((ZEO,CURATOR),(CURATOR,ZEO)):
            with self.assertRaisesRegex(UnsupportedDefinitionError, 'Locally restricted assembly source'):
                r.card(recipe(a,b))
        self.assertIsNotNone(r.card(ZEO).battlecry)
        self.play(g, MISMATCH); offer = self.offer(g)
        self.assertNotIn(ZEO, offer.primary_candidates+offer.secondary_candidates)
        self.assert_safe(g); restored = self.portable(g)
        option = g.state.pending_choice.options[0].id
        for current in (g,restored): self.choose(current, option)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_passive_rajh_filters_unconfirmed_source_before_power_review(self):
        g = self.game('rajh', RAJH); self.play(g, RAJH)
        offer = self.offer(g)
        self.assertNotIn(ZEO, offer.primary_candidates+offer.secondary_candidates)
        self.assertTrue(all(g.registry.card(o.card_id).passive_hero_power
            for o in g.state.pending_choice.options))
        restored = self.portable(g); key = g.state.pending_choice.options[0].id
        for current in (g,restored): self.choose(current, key)
        self.assertEqual(g.snapshot(), restored.snapshot())
        power = g.state.entities[g.state.players[1].hero_power_id]
        self.assertTrue(g.registry.card(power.card_id).passive_hero_power)
        self.assertNotEqual(power.card_id, POWER)
        self.portable(g)

    def test_saved_receipt_cannot_restore_excluded_candidate_or_old_policy(self):
        g = self.game('zeo', MISMATCH); self.play(g, MISMATCH); offer = self.offer(g)
        saved = g.snapshot()
        for change in ({'primary_candidates':offer.primary_candidates+(ZEO,)},
                {'secondary_candidates':offer.secondary_candidates+(ZEO,)},
                {'secondary_card_ids':(ZEO,offer.secondary_card_ids[1])}):
            with self.assertRaises(ValueError):
                validate_offer(g.registry,CTX,replace(offer,**change))
        self.assertEqual(g.snapshot(), saved)
        r = build_registry(); r._version = g.registry.version
        r.register_pool(g.registry.pool(POOL_ID,CTX))
        r._assemble_local_restrictions.clear()
        self.assertNotEqual(g.registry.fingerprint(), r.fingerprint())
        with self.assertRaises(SnapshotError): Game.from_snapshot(saved, r)
        old = json.loads(json.dumps(saved))
        old['mechanics_version']['version'] = 'core-effects-v732'
        old['state_hash'] = canonical_hash({k:v for k,v in old.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError): Game.from_snapshot(old, fixture('zeo'))

    def test_declared_empty_policy_and_unlisted_pending_errors_still_apply(self):
        from random import Random
        g = self.game('zeo_only', MISMATCH); rng = Random(7); before = rng.getstate()
        spec = Assemble(1, POOL_ID)
        with self.assertRaisesRegex(ValueError, 'primary pool is empty'):
            draw(g.registry,CTX,g.state,spec,rng)
        self.assertEqual(rng.getstate(), before)
        self.assertIsNone(draw(g.registry,CTX,g.state,replace(spec,empty_policy='skip'),rng))
        self.assertEqual(rng.getstate(), before)
        r = build_registry(); del r._assemble_local_restrictions[REDEEMER]
        with self.assertRaisesRegex(ValueError, 'explicitly unimplemented'):
            recipe_options(r,GOLEM,REDEEMER)

    def test_registration_rejects_bad_or_duplicate_scope_and_frozen_changes(self):
        r = build_registry(); before = r.fingerprint()
        for profile in (AssembleLocalRestriction('not-a-card','local-test'),
                AssembleLocalRestriction(ZEO,'local-test',('deathrattle',)),
                AssembleLocalRestriction(REDEEMER,'local-test',('battlecry',)),
                r.assemble_local_restrictions[REDEEMER]):
            with self.assertRaises(ValueError): r.register_assemble_local_restriction(profile)
            self.assertEqual(r.fingerprint(), before)
        r.freeze()
        with self.assertRaises(ValueError):
            r.register_assemble_local_restriction(AssembleLocalRestriction(CURATOR,'local-test'))
