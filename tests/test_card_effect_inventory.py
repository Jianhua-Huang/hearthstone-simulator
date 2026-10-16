"""Planning labels preserve unknowns, modes and dependencies without executing them."""

import unittest

from hs_sim.catalog import CardCatalog
from hs_sim.card_effects import build_inventory, effect_groups, trigger_groups


def record(cid, text="", **extra):
    return {"id": cid, "dbf_id": len(cid), "name": cid, "text": text,
            "text_en": text, "type": "MINION", "collectible": True,
            "tags": {}, "power_keyword_tags": [], **extra}


class CardEffectInventoryTests(unittest.TestCase):
    def test_no_record_or_unknown_related_content_is_silently_dropped(self):
        rows = [record("unknown", "Unrecognized special behavior", related_dbf_ids=[999]),
                record("BG_other", type="BATTLEGROUND_SPELL", collectible=False)]
        data = build_inventory(CardCatalog(rows))
        self.assertEqual({r["id"] for r in data["records"]}, {r["id"] for r in rows})
        unknown = next(r for r in data["records"] if r["id"] == "unknown")
        self.assertEqual(unknown["missing_related_dbf_ids"], [999])
        self.assertEqual(unknown["effect_groups"], ["manual_effect_review"])
        self.assertTrue(all(r["review_required"] for r in data["records"]))
        self.assertFalse(data["formal_pool_complete"])
        self.assertFalse(data["classification_is_executable"])

    def test_shared_draw_effect_and_distinct_trigger_hints_are_separate(self):
        battlecry = record("bc", "<b>Battlecry:</b> Draw a card.")
        deathrattle = record("dr", "<b>Deathrattle:</b> Draw a card.")
        self.assertEqual(effect_groups(battlecry), effect_groups(deathrattle))
        self.assertIn("draw", effect_groups(battlecry))
        self.assertEqual(trigger_groups(battlecry), ("battlecry",))
        self.assertEqual(trigger_groups(deathrattle), ("deathrattle",))

    def test_unknown_or_hidden_body_is_not_a_plain_keyword_candidate(self):
        for row in (record("empty-bc", tags={"BATTLECRY": 1}),
                    record("hidden", "<b>Taunt</b>", power_keyword_tags=[{"tag": "CUSTOM_BODY", "value": 1}]),
                    record("opaque", "<b>Rush</b> and a special effect")):
            with self.subTest(cid=row["id"]):
                self.assertIn("manual_effect_review", effect_groups(row))

    def test_plain_and_multiline_keyword_hints_still_require_review(self):
        rows = [record("plain"), record("keywords", "<b>Taunt</b>\n<b>Lifesteal</b>")]
        data = build_inventory(CardCatalog(rows), implemented_ids=("plain",))
        actual = {r["id"]: r for r in data["records"]}
        self.assertEqual(actual["plain"]["effect_groups"], ["plain_minion_candidate"])
        self.assertEqual(actual["keywords"]["effect_groups"], ["keyword_minion_candidate"])
        self.assertTrue(actual["plain"]["definition_registered"])
        self.assertEqual(actual["plain"]["scope"], "needs_format_review")
        self.assertTrue(actual["plain"]["review_required"])

    def test_series_hint_never_establishes_standard_legality(self):
        data = build_inventory(CardCatalog([record("BE_036"), record("CORE_EX1_008")]))
        self.assertTrue(all(r["scope"] == "needs_format_review" for r in data["records"]))

    def test_relations_to_existing_noncollectible_content_are_preserved(self):
        root = record("root", related_dbf_ids=[20])
        token = record("token", dbf_id=20, collectible=False)
        data = build_inventory(CardCatalog([root, token]))
        row = next(r for r in data["records"] if r["id"] == "root")
        self.assertEqual(row["related_dbf_ids"], [20])
        self.assertEqual(row["missing_related_dbf_ids"], [])
