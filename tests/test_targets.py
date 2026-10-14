"""Small in-memory target fixtures; no local client/extracted database required."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from hs_sim.targets import (TargetBaseline, TargetValidationError, canonical_digest,
                            load_baseline, summarize_baseline, validate_baseline)


def fixture():
    evidence = [
        {"id": "local", "kind": "local_file", "locator": "cards.json", "sha256": "a" * 64,
         "checked_on": "2026-09-23", "claims": "Raw fixture only"},
        {"id": "test", "kind": "internal_tests", "locator": "tests/fixture.py", "sha256": None,
         "checked_on": "2026-09-23", "claims": "Prototype case"},
        {"id": "rule", "kind": "official_rule", "locator": "https://example.test/rule", "sha256": None,
         "checked_on": "2026-09-23", "claims": "Rule description, not a calibration case"},
    ]
    target = {
        "schema_version": 1, "target_id": "fixture", "checked_on": "2026-09-23",
        "scope": {"product": "traditional_constructed", "modes": ["standard", "wild"], "support_level": "prototype_subset"},
        "rules": {"candidate_patch": None, "region": None, "effective_at": None,
                  "hotfix_set_complete": False, "hotfixes": [], "evidence_refs": ["rule"]},
        "data": {"client_version": "1.2.3.456", "build": 456, "locale": "zhCN", "extracted_at": "2026-09-23",
                 "files": {key: {"path": f"{key}.json", "sha256": "a" * 64}
                           for key in ("cards", "manifest", "dbf", "assembly", "product_db")}, "evidence_refs": ["local"]},
        "runtime": {"baseline_ruleset": "prototype-v1", "baseline_content": "fixture-v1", "snapshot_schema": 1,
                    "replay_schema": 1, "rng": "fixture RNG", "python": "3.12"},
        "support_file": "support.json", "evidence": evidence,
        "gaps": [{"id": "unknown-region", "description": "Region unknown", "blocks_complete": True}], "extensions": {},
    }
    mechanism = {"id": "summon", "name": "Summon", "stage": "M1", "dependencies": [],
                 "implementation": "partial", "verification": "internally_tested", "evidence_refs": ["test"], "notes": "Prototype"}
    data = {"id": "fixture.minion", "attack": 1, "health": 1, "cost": None}
    card = {"id": data["id"], "data": data, "data_sha256": canonical_digest(data), "dependencies": ["summon"],
            "reachable_cards": [], "stage": "M1", "implementation": "not_started", "verification": "unverified",
            "evidence_refs": ["local"], "mode_legality": {"standard": None, "wild": None}, "notes": "Data only"}
    support = {"schema_version": 1, "target_id": "fixture", "coverage_kind": "representative_sample",
               "full_pool_count": None, "mechanisms": [mechanism], "cards": [card], "extensions": {}}
    return target, support


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.target, self.support = fixture()

    def rejected(self):
        with self.assertRaises(TargetValidationError):
            validate_baseline(self.target, self.support)

    def test_summary_does_not_invent_a_full_pool_denominator(self):
        result = summarize_baseline(TargetBaseline(self.target, self.support))
        self.assertEqual(result["sample_cards"], 1)
        self.assertEqual(result["card_implementation"], {"not_started": 1})
        self.assertIsNone(result["full_pool_count"])
        self.assertIsNone(result["full_pool_coverage_percent"])
        self.assertIsNone(result["candidate_patch"])
        self.assertIsNone(result["region"])

    def test_unknown_annotations_preserved_but_not_used_for_support(self):
        self.target["extensions"]["future_annotation"] = {"region_guess": "EU", "complete": True}
        before = deepcopy(self.target)
        result = summarize_baseline(TargetBaseline(self.target, self.support))
        self.assertIsNone(result["region"])
        self.assertEqual(self.target, before)
        self.assertEqual(result["support_level"], "prototype_subset")

    def test_unknown_schema_field_rejected(self):
        self.target["complete"] = True
        self.rejected()

    def test_no_complete_support_claim_in_sample_schema(self):
        self.target["scope"]["support_level"] = "complete"
        self.rejected()

    def test_no_full_pool_denominator_from_sample(self):
        self.support["full_pool_count"] = 1
        self.rejected()

    def test_sample_cannot_be_renamed_to_full_inventory(self):
        self.support["coverage_kind"] = "complete"
        self.rejected()

    def test_target_id_must_match(self):
        self.support["target_id"] = "different"
        self.rejected()

    def test_missing_evidence_rejected(self):
        self.support["cards"][0]["evidence_refs"] = ["missing"]
        self.rejected()

    def test_duplicate_evidence_rejected(self):
        self.target["evidence"].append(deepcopy(self.target["evidence"][0]))
        self.rejected()

    def test_missing_mechanism_dependency_rejected(self):
        self.support["cards"][0]["dependencies"] = ["not-tracked"]
        self.rejected()

    def test_dependency_cycle_rejected(self):
        self.support["mechanisms"][0]["dependencies"] = ["summon"]
        self.rejected()

    def test_missing_reachable_content_rejected(self):
        self.support["cards"][0]["reachable_cards"] = ["missing.token"]
        self.rejected()

    def test_data_hash_detects_changed_snapshot(self):
        self.support["cards"][0]["data"]["attack"] = 100
        self.rejected()

    def test_data_presence_does_not_imply_tested_execution(self):
        self.support["cards"][0]["verification"] = "internally_tested"
        self.rejected()

    def test_tested_execution_requires_test_evidence(self):
        self.support["cards"][0].update(implementation="partial", verification="internally_tested")
        self.rejected()

    def test_official_rule_is_not_official_calibration(self):
        self.support["cards"][0].update(implementation="partial", verification="officially_calibrated", evidence_refs=["test", "rule"])
        self.rejected()

    def test_implemented_card_cannot_depend_on_missing_mechanism(self):
        self.support["mechanisms"][0].update(implementation="not_started", verification="unverified")
        self.support["cards"][0]["implementation"] = "implemented"
        self.rejected()

    def test_implemented_root_requires_implemented_reachable_content(self):
        token = deepcopy(self.support["cards"][0])
        token["id"] = token["data"]["id"] = "fixture.token"
        token["data_sha256"] = canonical_digest(token["data"])
        self.support["cards"].append(token)
        self.support["cards"][0].update(implementation="implemented", reachable_cards=["fixture.token"])
        self.rejected()

    def test_unknown_region_cannot_claim_complete_hotfix_set(self):
        self.target["rules"]["hotfix_set_complete"] = True
        self.rejected()

    def test_unknown_region_needs_explicit_gap(self):
        self.target["gaps"] = []
        self.rejected()

    def test_build_must_match_client_version(self):
        self.target["data"]["build"] = 457
        self.rejected()

    def test_unknown_legality_is_not_boolean_false(self):
        self.support["cards"][0]["mode_legality"]["standard"] = False
        self.rejected()

    def test_non_finite_annotations_rejected(self):
        self.support["extensions"]["bad"] = float("nan")
        self.rejected()

    def test_round_trip_loading_uses_only_small_fixture_files(self):
        self.target["extensions"]["future"] = [1, None, "opaque"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "target.json"
            path.write_text(json.dumps(self.target), encoding="utf-8")
            (path.parent / "support.json").write_text(json.dumps(self.support), encoding="utf-8")
            result = load_baseline(path)
        self.assertEqual(result.target, self.target)
        self.assertEqual(result.support, self.support)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "target.json"
            path.write_text('{"support_file":"support.json","support_file":"other.json"}', encoding="utf-8")
            with self.assertRaises(TargetValidationError):
                load_baseline(path)


if __name__ == "__main__":
    unittest.main()
