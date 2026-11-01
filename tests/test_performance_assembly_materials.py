"""Static assembly reuse preserves live filtering, errors, isolation and RNG."""
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from random import Random
import unittest
from unittest.mock import patch

from hs_sim.engine import CardClass, PlayCard
from hs_sim.engine import assemble_faces, assembly_materials as cache
from hs_sim.engine.assemble_offers import Assemble, candidates, draw
from hs_sim.engine.pools import PoolQuery
import test_assemble_offers as fixtures
from test_assemble_offers import registry


class AssemblyMaterialTests(unittest.TestCase):
    def test_release_static_scope_reuses_frozen_materials_without_rescanning_graphs(self):
        cid = assemble_faces.AssembleRecipe('a', 'b', 'top').card_id
        with cache.candidate_materials(self.registry):
            expected = assemble_faces.resolve_face(self.registry, cid)
        with patch.object(cache.RegistryInventoryGuard, 'matches', side_effect=AssertionError('repeated scan')):
            with cache.candidate_materials(self.registry, audit=False):
                actual = assemble_faces.resolve_face(self.registry, cid)
                self.assertIs(actual, expected)
        self.assertIsNone(cache._current.get())

    def setUp(self):
        with cache._lock: cache._owners.clear()
        self.game = fixtures.AssembleOfferTests().game()
        self.registry = self.game.registry
        self.spec = Assemble(1, 'pool', primary_query=PoolQuery(max_cost=2))

    def query(self, primary=None, state=None, spec=None):
        return candidates(self.registry, self.game._generation_context,
                          state or self.game._state, spec or self.spec, primary)

    def test_warm_static_materials_remove_reconstruction_but_keep_same_inventory(self):
        with patch.object(assemble_faces, 'validate_template', wraps=assemble_faces.validate_template) as checked:
            expected = self.query('a'); cold = checked.call_count
            actual = self.query('a'); warm = checked.call_count - cold
        self.assertEqual(actual, expected)
        self.assertGreater(cold, 0); self.assertEqual(warm, 0)
        with patch.object(cache, 'candidate_materials', lambda registry, **kwargs: nullcontext()):
            self.assertEqual(self.query('a'), expected)

    def test_live_class_and_query_are_not_cached_and_rng_is_identical(self):
        self.query('a')
        foreign = deepcopy(self.game._state); foreign.players[1].hero_class = CardClass.WARRIOR
        for state in (self.game._state, foreign):
            for spec in (self.spec, replace(self.spec, primary_query=PoolQuery(max_cost=4))):
                actual = self.query(state=state, spec=spec)
                with patch.object(cache, 'candidate_materials', lambda registry, **kwargs: nullcontext()):
                    expected = self.query(state=state, spec=spec)
                self.assertEqual(actual, expected)
        for seed in (1, 31, 166):
            fast, slow = Random(seed), Random(seed)
            actual = draw(self.registry, self.game._generation_context, self.game._state, self.spec, fast)
            with patch.object(cache, 'candidate_materials', lambda registry, **kwargs: nullcontext()):
                expected = draw(self.registry, self.game._generation_context, self.game._state, self.spec, slow)
            self.assertEqual(actual, expected); self.assertEqual(fast.getstate(), slow.getstate())

    def test_missing_and_nested_changed_templates_are_not_hidden(self):
        self.query('a')
        original = self.registry._assemble_templates.pop('c')
        with self.assertRaisesRegex(ValueError, 'lacks reviewed'): self.query('a')
        self.registry._assemble_templates['c'] = original
        object.__setattr__(original.suffix, 'behavior_id', 'missing-body')
        with self.assertRaises(ValueError): self.query('a')

    def test_changed_native_schema_is_revalidated(self):
        self.query('a')
        with patch.object(assemble_faces.AssembleTemplate, '__post_init__', side_effect=ValueError('changed schema')):
            with self.assertRaisesRegex(ValueError, 'changed schema'): self.query('a')

    def test_mutable_and_unknown_extension_registries_use_original_path(self):
        mutable, extended = registry(), registry()
        extended._extension_payload = object()
        extended.freeze()
        for r in (mutable, extended):
            with cache.candidate_materials(r):
                with patch.object(assemble_faces, 'validate_template', wraps=assemble_faces.validate_template) as checked:
                    assemble_faces.text_source(r, 'a'); assemble_faces.text_source(r, 'a')
                    self.assertEqual(checked.call_count, 2)
            self.assertIsNone(cache._current.get())

    def test_cached_derived_output_mutation_forces_reconstruction(self):
        cid = assemble_faces.AssembleRecipe('a', 'b', 'top').card_id
        with cache.candidate_materials(self.registry):
            original = assemble_faces.resolve_face(self.registry, cid)
            attack = original.attack
            object.__setattr__(original, 'attack', 999)
            rebuilt = assemble_faces.resolve_face(self.registry, cid)
        self.assertEqual(rebuilt.attack, attack); self.assertIsNot(original, rebuilt)

    def test_capacity_limits_and_failures_do_not_leak_active_context(self):
        with patch.object(cache, 'MAX_MATERIALS', 3):
            with cache.candidate_materials(self.registry):
                for n in range(8): cache.material(self.registry, ('probe', n), lambda n=n: str(n))
                self.assertEqual(len(cache._current.get()[1]), 3)
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, 'not supported'):
                        cache.material(self.registry, ('fail',), lambda: (_ for _ in ()).throw(ValueError('not supported')))
                self.assertNotIn(('fail',), cache._current.get()[1])
        self.assertIsNone(cache._current.get())
        with patch.object(cache, 'MAX_REGISTRIES', 2):
            for _ in range(3):
                r = registry(); r.freeze()
                with cache.candidate_materials(r): pass
            self.assertLessEqual(len(cache._owners), 2)

    def test_mid_enumeration_inventory_mutation_rejects_and_clears_cache(self):
        with self.assertRaisesRegex(ValueError, 'Registry changed'):
            with cache.candidate_materials(self.registry):
                assemble_faces.text_source(self.registry, 'a')
                self.registry._assemble_templates.pop('c')
        self.assertIsNone(cache._current.get())
        self.assertFalse(cache._owners[id(self.registry)][2])

    def test_registry_identity_static_catalog_and_full_action_remain_equal(self):
        fast, slow = self.game.clone(), self.game.clone()
        identity = self.registry.fingerprint(); count = len(self.registry.cards)
        action = PlayCard(1, fast._state.players[1].hand[0])
        actual = fast.apply(action)
        with patch.object(cache, 'candidate_materials', lambda registry, **kwargs: nullcontext()):
            expected = slow.apply(action)
        self.assertEqual(actual, expected)
        self.assertEqual(fast.snapshot(), slow.snapshot())
        self.assertEqual([fast.observe(p) for p in (1, 2)], [slow.observe(p) for p in (1, 2)])
        self.assertEqual(self.registry.fingerprint(), identity)
        self.assertEqual(len(self.registry.cards), count)


if __name__ == '__main__': unittest.main()
