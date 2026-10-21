"""Recursive live/dead source proofs reuse the native fixture without repeats."""
import unittest
import test_adjacent_deathrattle_copy_card as native


class LiveDeathrattleCopyProofTests(unittest.TestCase):
    def test_complete_live_copy_can_be_copied_again_after_original_donor_dies(self):
        d = native.AdjacentDeathrattleCopyTests()
        g = d.game((native.CARD, native.CARD, native.KILL, native.KILL), (native.LEFT,))
        first = d.play(g, native.CARD)
        second = d.play(g, native.CARD)
        row = d.abilities(g, second)[0]
        self.assertIsNotNone(row.deathrattle_copied_from.original.deathrattle_copied_from)
        self.assertLess(row.deathrattle_copied_from.original.id, row.id)
        d.portable(g)
        d.play(g, native.KILL, first)
        d.portable(g)
        d.play(g, native.KILL, second)
        self.assertEqual(d.count(g, native.COIN), 2)
        d.portable(g)

    def test_complete_dead_inheritance_can_be_copied_as_live_material(self):
        d = native.AdjacentDeathrattleCopyTests()
        g = d.game((native.CARD, native.THORNS, native.CARD, native.KILL, native.KILL), (native.LEFT,))
        original = d.play(g, native.CARD)
        d.play(g, native.KILL, original)
        thorns = d.play(g, native.THORNS)
        inherited = d.abilities(g, thorns)[0]
        self.assertIsNotNone(inherited.deathrattle_inherited_from)
        copied = d.play(g, native.CARD)
        row = d.abilities(g, copied)[0]
        self.assertEqual(row.deathrattle_copied_from.original.deathrattle_inherited_from,
            inherited.deathrattle_inherited_from)
        self.assertIsNone(row.deathrattle_inherited_from)
        d.portable(g)
        d.play(g, native.KILL, copied)
        self.assertEqual(d.count(g, native.COIN), 2)
        d.portable(g)
