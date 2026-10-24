"""Finite physical spell recipes do not weaken the legacy minion-pair contract."""
from dataclasses import asdict
import unittest
from hs_sim.engine import CardDefinition, CardType, Registry
from hs_sim.engine.hand_combinations import HandCombinationProfile

VERSION='hand-spell-mixture-v1'


def registry(*,left_kind=CardType.SPELL,right_cost=3,playable=True):
    r=Registry('hand-mixture-contract')
    r.register_behavior('empty',lambda c:())
    for cid in ('left','right','result','other'):
        kind=left_kind if cid=='left' else CardType.SPELL
        kwargs=dict(on_play='empty',manual_playable=playable if cid=='result' else True) if kind==CardType.SPELL else dict(health=1)
        r.register_card(CardDefinition(cid,cid,kind,cost=right_cost if cid=='right' else 3,**kwargs))
    return r


class HandSpellMixtureProfileTests(unittest.TestCase):
    def test_two_physical_copies_of_same_single_have_one_valid_declared_result(self):
        r=registry();r.register_hand_combination(HandCombinationProfile('result','left','left',VERSION));r.validate()

    def test_distinct_source_pairs_can_share_one_ingredient(self):
        r=registry();r.register_hand_combination(HandCombinationProfile('result','left','left',VERSION))
        r.register_hand_combination(HandCombinationProfile('other','left','right',VERSION));r.validate()

    def test_same_pair_cannot_choose_two_different_results(self):
        r=registry();r.register_hand_combination(HandCombinationProfile('result','left','right',VERSION))
        r.register_hand_combination(HandCombinationProfile('other','right','left',VERSION))
        with self.assertRaises(ValueError):r.validate()

    def test_result_cannot_be_an_input_to_another_mixture(self):
        r=registry();r.register_hand_combination(HandCombinationProfile('result','left','right',VERSION))
        r.register_hand_combination(HandCombinationProfile('other','result','left',VERSION))
        with self.assertRaises(ValueError):r.validate()

    def test_nonspell_or_different_printed_cost_or_unplayable_face_is_rejected(self):
        for kwargs in (dict(left_kind=CardType.MINION),dict(right_cost=4),dict(playable=False)):
            with self.subTest(kwargs=kwargs):
                r=registry(**kwargs);r.register_hand_combination(HandCombinationProfile('result','left','right',VERSION))
                with self.assertRaises(ValueError):r.validate()

    def test_default_minion_policy_keeps_original_four_fields_and_unique_halves(self):
        p=HandCombinationProfile('whole','left','right')
        self.assertEqual(asdict(p),dict(result_card_id='whole',left_card_id='left',right_card_id='right',version='hand-combination-v1'))
        with self.assertRaises(ValueError):HandCombinationProfile('whole','left','left').__post_init__()

    def test_unknown_policy_and_self_containing_recipe_are_rejected(self):
        for args in (('result','left','right','future-version'), ('left','left','right',VERSION)):
            with self.assertRaises(ValueError):HandCombinationProfile(*args)
