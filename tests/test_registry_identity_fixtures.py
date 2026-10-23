"""Frozen complete identities tolerate reviewed migrations, never new rules."""
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine.model import CardDefinition, CardType, CostAuraSpec, CostSpec, IntrinsicCostSpec
from hs_sim.engine.representative import build_registry as representative
from hs_sim.targets import canonical_digest
from registry_identity_fixtures import (
    DEFAULT_REPRESENTATIVE_FINGERPRINT, REVIEWED_DEFINITION_TRANSITIONS,
    historical_definition_digests,
)


ROOT = Path(__file__).resolve().parents[1]
HISTORY_ROOT = ROOT / 'outputs/card-integration-20261014'


@lru_cache(None)
def registry():
    return build_registry()


def one_card(definition):
    def card(cid):
        if cid != definition.id:
            raise KeyError(cid)
        return definition
    return SimpleNamespace(card=card)


class RegistryIdentityFixtureTests(unittest.TestCase):
    def test_all_twelve_original_complete_definition_inventories(self):
        # Independent historical files retain their actual original digests.
        for batch in range(70, 82):
            with self.subTest(batch=batch):
                path = HISTORY_ROOT / f'k{batch}-before/definition-digests.json'
                original_bytes = path.read_bytes()
                historical = json.loads(original_bytes)
                self.assertEqual(historical, historical_definition_digests(registry(), historical))
                self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(representative().fingerprint(), DEFAULT_REPRESENTATIVE_FINGERPRINT)

    def test_two_real_corrections_reconstruct_the_exact_original_by_one_field(self):
        historical = json.loads((HISTORY_ROOT / 'k73-before/definition-digests.json').read_text(encoding='utf-8'))
        corrections = (
            ('EDR_531', 'on_play', 'cards.utility.body.9c1bbc82d8f9cb4c34894e9c'),
            ('JAIL_123', 'battlecry', 'm5.breakout_architect'),
        )
        for cid, field, original_value in corrections:
            with self.subTest(card=cid):
                current = registry().card(cid)
                old, approved = REVIEWED_DEFINITION_TRANSITIONS[cid]
                self.assertEqual(old, historical[cid])
                self.assertEqual(canonical_digest(asdict(current)), approved)
                self.assertEqual(canonical_digest(asdict(replace(current, **{field: original_value}))), old)
                self.assertEqual(historical_definition_digests(registry(), {cid: old}), {cid: old})

    def test_reviewed_successors_reject_a_new_change_in_any_complete_definition(self):
        for cid, (old, _) in REVIEWED_DEFINITION_TRANSITIONS.items():
            with self.subTest(card=cid):
                changed = replace(registry().card(cid), cost=registry().card(cid).cost + 1)
                with self.assertRaisesRegex(AssertionError, cid):
                    historical_definition_digests(one_card(changed), {cid: old})

    def test_current_schema_keeps_its_full_digest_and_inputs_are_not_mutated(self):
        cards = ('FP1_017', 'JAIL_307', 'EDR_531', 'JAIL_123')
        before = {cid: asdict(registry().card(cid)) for cid in cards}
        current = {cid: canonical_digest(value) for cid, value in before.items()}
        historical = deepcopy(current)
        self.assertEqual(historical_definition_digests(registry(), historical), current)
        self.assertEqual(historical, current)
        self.assertEqual({cid: asdict(registry().card(cid)) for cid in cards}, before)

    def test_new_cost_or_metadata_is_not_hidden_by_inert_field_projection(self):
        historical = json.loads((HISTORY_ROOT / 'k73-before/definition-digests.json').read_text(encoding='utf-8'))
        for cid in ('FP1_017', 'JAIL_307'):
            definition = registry().card(cid)
            for changed in (replace(definition, cost=definition.cost + 1),
                    replace(definition, name=definition.name + ' changed')):
                with self.subTest(card=cid, changed=changed.name):
                    self.assertNotEqual(historical_definition_digests(one_card(changed), {cid: historical[cid]}),
                        {cid: historical[cid]})

    def test_nondefault_adjacency_and_exact_card_selectors_are_never_removed(self):
        adjacent = CardDefinition('identity.adjacent', 'Adjacent', CardType.SPELL,
            cost_auras=(CostAuraSpec(CostSpec(delta=1), hand_adjacent=True),))
        selected = CardDefinition('identity.selector', 'Selector', CardType.MINION, health=1,
            intrinsic_costs=(IntrinsicCostSpec(set_to=0, condition='controlled_card',
                history_profile_id='controlled.current-card-v1', card_ids=('CORE_CS2_182',)),))
        for definition, container, field in (
                (adjacent, 'cost_auras', 'hand_adjacent'),
                (selected, 'intrinsic_costs', 'card_ids')):
            with self.subTest(card=definition.id):
                forged = asdict(definition)
                del forged[container][0][field]
                alleged_old = {definition.id: canonical_digest(forged)}
                self.assertNotEqual(historical_definition_digests(one_card(definition), alleged_old), alleged_old)

    def test_mixed_nested_schema_versions_match_only_their_entire_original(self):
        definition = CardDefinition('identity.mixed', 'Mixed', CardType.MINION, health=1,
            cost_auras=(CostAuraSpec(CostSpec(delta=-1)),),
            intrinsic_costs=(IntrinsicCostSpec(delta=-2),))
        for old_aura, old_selector in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(old_aura=old_aura, old_selector=old_selector):
                original = asdict(definition)
                if old_aura:
                    del original['cost_auras'][0]['hand_adjacent']
                if old_selector:
                    del original['intrinsic_costs'][0]['card_ids']
                expected = {definition.id: canonical_digest(original)}
                self.assertEqual(historical_definition_digests(one_card(definition), expected), expected)
                original['health'] += 1
                forged = {definition.id: canonical_digest(original)}
                self.assertNotEqual(historical_definition_digests(one_card(definition), forged), forged)

    def test_unknown_historical_digest_is_not_replaced_by_a_reviewed_card_name(self):
        for cid in ('FP1_017', 'JAIL_307', 'EDR_531', 'JAIL_123'):
            with self.subTest(card=cid):
                unknown = {cid: '0' * 64}
                self.assertNotEqual(historical_definition_digests(registry(), unknown), unknown)


if __name__ == '__main__':
    unittest.main()
