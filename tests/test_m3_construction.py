from copy import deepcopy
from dataclasses import replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, DeckPolicy, DeckValidationError,
                           Game, MatchSetup, Rarity, Runes, validate_deck)
from opening_fixtures import deck, metadata, policy, registry, setup


class ConstructionTests(unittest.TestCase):
    def setUp(self):
        self.registry = registry()

    def report(self, cards=None, card_class=CardClass.MAGE, **kwargs):
        return validate_deck(deck(card_class, cards=cards, **kwargs), self.registry, policy(self.registry))

    def assert_issue(self, report, code):
        self.assertFalse(report.valid)
        self.assertIn(code, [i.code for i in report.issues])
        with self.assertRaises(DeckValidationError):
            report.require_valid()

    def test_valid_neutral_deck_has_explicit_experimental_scope(self):
        report = self.report()
        self.assertTrue(report.valid)
        self.assertEqual(report.mode, 'experimental')

    def test_deck_size_is_checked_without_truncation(self):
        self.assert_issue(self.report(deck().cards[:-1]), 'deck_size')
        self.assert_issue(self.report(deck().cards + ('card.31',)), 'deck_size')

    def test_normal_copy_limit(self):
        self.assertTrue(self.report(('card.1',) * 2 + deck().cards[2:]).valid)
        self.assert_issue(self.report(('card.1',) * 3 + deck().cards[3:]), 'copy_limit')

    def test_legendary_copy_limit(self):
        self.registry.register_card(CardDefinition('legend', 'Legend', CardType.MINION, health=1,
                                                   metadata=metadata(rarity=Rarity.LEGENDARY)))
        self.assertTrue(self.report(('legend',) + deck().cards[1:]).valid)
        self.assert_issue(self.report(('legend',) * 2 + deck().cards[2:]), 'copy_limit')

    def test_aliases_share_copy_count(self):
        for i in range(3):
            self.registry.register_card(CardDefinition(f'alias.{i}', 'Alias', CardType.MINION, health=1,
                                                       metadata=metadata(deck_identity='same-card')))
        self.assert_issue(self.report(('alias.0', 'alias.1', 'alias.2') + deck().cards[3:]), 'copy_limit')

    def test_explicit_copy_exception_is_data_driven(self):
        self.registry.register_card(CardDefinition('unlimited', 'Extra copies', CardType.MINION, health=1,
                                                   metadata=metadata(max_copies=30)))
        self.assertTrue(self.report(('unlimited',) * 30).valid)

    def test_dual_class_card_belongs_to_either_named_class(self):
        self.registry.register_card(CardDefinition('dual', 'Dual', CardType.MINION, health=1,
            metadata=CardMetadata(True, (CardClass.MAGE, CardClass.WARRIOR), Rarity.COMMON)))
        cards = ('dual',) + deck().cards[1:]
        self.assertTrue(self.report(cards).valid)
        self.assertTrue(self.report(cards, CardClass.WARRIOR).valid)
        self.assert_issue(self.report(cards, CardClass.DEATH_KNIGHT, runes=Runes(3)), 'class')

    def test_uncollectible_coin_cannot_be_added_to_deck(self):
        self.assert_issue(self.report(('coin',) + deck().cards[1:]), 'uncollectible')

    def test_unknown_metadata_is_not_assumed_neutral_or_common(self):
        self.registry.register_card(CardDefinition('unknown', 'Unknown', CardType.MINION, health=1))
        self.assert_issue(self.report(('unknown',) + deck().cards[1:]), 'unknown_metadata')

    def test_unknown_definition_is_distinct_from_format_illegality(self):
        p = replace(policy(self.registry), allowed_card_ids=policy(self.registry).allowed_card_ids + ('missing',))
        report = validate_deck(replace(deck(), cards=('missing',) + deck().cards[1:]), self.registry, p)
        self.assertEqual([i.code for i in report.issues], ['unsupported_definition'])

    def test_rotation_and_bans_are_explicit_policy_inputs(self):
        p = replace(policy(self.registry), allowed_card_ids=tuple(i for i in self.registry.cards if i != 'card.1'))
        self.assert_issue(validate_deck(deck(), self.registry, p), 'format_legality')
        p = replace(policy(self.registry), banned_card_ids=('card.1',))
        self.assert_issue(validate_deck(deck(), self.registry, p), 'format_legality')

    def test_standard_and_wild_require_complete_pools(self):
        for mode in ('standard', 'wild'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'complete'):
                replace(policy(self.registry), mode=mode)
            # The caller supplies legality metadata, never inferred from execution coverage.
            p = replace(policy(self.registry), mode=mode, pool_complete=True)
            self.assertTrue(validate_deck(deck(), self.registry, p).valid)

    def test_runes_are_maximum_requirements_not_added_across_copies(self):
        self.registry.register_card(CardDefinition('blood', 'Blood', CardType.MINION, health=1,
            metadata=metadata(CardClass.DEATH_KNIGHT, runes=Runes(blood=2))))
        cards = ('blood',) * 2 + deck().cards[2:]
        self.assertTrue(self.report(cards, CardClass.DEATH_KNIGHT, runes=Runes(2, 1)).valid)
        self.assert_issue(self.report(cards, CardClass.DEATH_KNIGHT, runes=Runes(1, 2)), 'rune_requirements')

    def test_combined_runes_must_fit_loadout(self):
        self.registry.register_card(CardDefinition('mixed', 'Mixed', CardType.MINION, health=1,
            metadata=metadata(CardClass.DEATH_KNIGHT, runes=Runes(1, 1, 1))))
        cards = ('mixed',) + deck().cards[1:]
        self.assertTrue(self.report(cards, CardClass.DEATH_KNIGHT, runes=Runes(1, 1, 1)).valid)
        self.assert_issue(self.report(cards, CardClass.DEATH_KNIGHT, runes=Runes(3)), 'rune_requirements')

    def test_runes_unknown_and_invalid_loadout_are_rejected(self):
        self.registry.register_card(CardDefinition('dk', 'DK', CardType.MINION, health=1,
            metadata=metadata(CardClass.DEATH_KNIGHT)))
        self.assert_issue(self.report(('dk',) + deck().cards[1:], CardClass.DEATH_KNIGHT, runes=Runes(3)), 'unknown_runes')
        for runes in (None, Runes(2), Runes(4)):
            self.assert_issue(self.report(card_class=CardClass.DEATH_KNIGHT, runes=runes), 'rune_loadout')
        self.assert_issue(self.report(runes=Runes(3)), 'rune_loadout')

    def test_wrong_hero_and_nondefault_power_are_rejected(self):
        p = policy(self.registry)
        self.assert_issue(validate_deck(replace(deck(), hero_card_id='warrior.hero'), self.registry, p), 'hero_identity')
        self.registry.register_card(CardDefinition('alternate', 'Alternate', CardType.HERO_POWER, on_use='power',
            metadata=metadata(CardClass.MAGE, collectible=False)))
        self.assert_issue(validate_deck(replace(deck(), hero_power_card_id='alternate'), self.registry, p), 'hero_power')

    def test_card_and_hero_type_constraints(self):
        self.assert_issue(self.report(('mage.hero',) + deck().cards[1:]), 'unsupported_deck_type')
        self.assert_issue(self.report(('mage.power',) + deck().cards[1:]), 'unsupported_deck_type')

    def test_invalid_deck_rejected_before_registry_freeze(self):
        config = setup(self.registry, decks=(replace(deck(), cards=()), deck(CardClass.WARRIOR)))
        with self.assertRaises(DeckValidationError):
            Game.from_decks(config, self.registry)
        self.registry.register_card(CardDefinition('still_mutable', 'Still mutable', CardType.MINION, health=1))

    def test_match_setup_json_strict_roundtrip(self):
        config = setup(self.registry)
        self.assertEqual(MatchSetup.from_dict(json.loads(json.dumps(config.to_dict()))), config)
        for key, value in (('first_player', True), ('seed', False), ('extra', 1)):
            raw = config.to_dict()
            raw[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                MatchSetup.from_dict(raw)
        raw = config.to_dict()
        raw['policy']['deck_size'] = True
        with self.assertRaises(ValueError):
            MatchSetup.from_dict(raw)


if __name__ == '__main__':
    unittest.main()
