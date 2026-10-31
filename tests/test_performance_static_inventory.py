"""Static indexing must retain mutable construction and real Shatter behavior."""
import unittest
from unittest.mock import patch

from hs_sim.engine import CardDefinition, CardType, Keyword, Registry, ShatterSpec
from hs_sim.engine.shatter import families


def add_family(registry, prefix):
    for suffix in ('L', 'R'):
        card_id = prefix + suffix
        registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
            keywords=(Keyword.SHATTERED,)))
    registry.register_card(CardDefinition(prefix, prefix, CardType.SPELL,
        keywords=(Keyword.SHATTER,), shatter=ShatterSpec(prefix+'L', prefix+'R')))


class StaticInventoryPerformanceTests(unittest.TestCase):
    def test_mutable_construction_observes_later_families(self):
        r = Registry('static-inventory-test')
        add_family(r, 'first')
        self.assertEqual(set(families(r)), {'firstL', 'firstR'})
        add_family(r, 'second')
        self.assertEqual(set(families(r)), {'firstL', 'firstR', 'secondL', 'secondR'})
        r.freeze()
        self.assertEqual(set(families(r)), {'firstL', 'firstR', 'secondL', 'secondR'})

    def test_frozen_queries_do_not_scan_or_resolve_unrelated_faces(self):
        r = Registry('static-inventory-test')
        add_family(r, 'split')
        for n in range(100):
            r.register_card(CardDefinition('plain'+str(n), 'plain', CardType.SPELL))
        expected = {part: root for root in r.cards.values() if root.shatter is not None
            for part in (root.shatter.left_card_id, root.shatter.right_card_id)}
        r.freeze()
        with patch.object(r, '_build_shatter_families', side_effect=AssertionError('rescan')), \
             patch.object(r, 'card', side_effect=AssertionError('dynamic lookup')):
            self.assertEqual(families(r), expected)
            self.assertEqual(families(r), expected)

    def test_returned_mapping_is_detached_and_registries_are_independent(self):
        left, right = Registry('left'), Registry('right')
        add_family(left, 'a')
        add_family(right, 'b')
        left.freeze()
        right.freeze()
        changed = families(left)
        changed.clear()
        self.assertEqual(set(families(left)), {'aL', 'aR'})
        self.assertEqual(set(families(right)), {'bL', 'bR'})

    def test_cache_does_not_change_complete_registry_fingerprint(self):
        r = Registry('static-inventory-test')
        add_family(r, 'split')
        before = r.fingerprint()
        r.freeze()
        families(r)
        r.freeze()
        self.assertEqual(r.fingerprint(), before)
        with self.assertRaises(ValueError):
            add_family(r, 'late')

    def test_invalid_family_is_still_rejected_at_freeze(self):
        r = Registry('static-inventory-test')
        r.register_card(CardDefinition('broken', 'broken', CardType.SPELL,
            keywords=(Keyword.SHATTER,), shatter=ShatterSpec('missingL', 'missingR')))
        with self.assertRaises(ValueError):
            r.freeze()


if __name__ == '__main__':
    unittest.main()
