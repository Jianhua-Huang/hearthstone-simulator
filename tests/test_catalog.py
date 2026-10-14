"""Catalog and CLI checks using synthetic records, never installed game data."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from hs_sim.__main__ import main
from hs_sim.catalog import CardCatalog, CatalogError, format_card


FIXTURE = [
    {
        "id": "TEST_001", "dbf_id": 1, "name": "测试火球", "name_en": "Test Fireball",
        "text": "造成<b>3</b>点伤害。\n测试文本", "text_en": "Deal <b>3</b> damage.",
        "cost": 2, "attack": None, "health": None, "type": "SPELL", "collectible": True,
        "tags": {"COST": 2, "42": 0},
    },
    {
        "id": "TEST_002", "dbf_id": 2, "name": "测试火球副本", "name_en": "Test Fireball Copy",
        "text": "", "text_en": "", "cost": 0, "attack": 0, "health": 1,
        "type": "MINION", "collectible": False, "tags": {},
    },
]


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = CardCatalog(FIXTURE)

    def test_chinese_english_and_id_search(self):
        self.assertEqual(len(self.catalog.search("火球")), 2)
        self.assertEqual(len(self.catalog.search("FIREBALL")), 2)
        self.assertEqual(self.catalog.search("test_002")[0]["dbf_id"], 2)
        self.assertEqual(self.catalog.search("测试", limit=1), [FIXTURE[0]])
        self.assertEqual(self.catalog.search("不存在"), [])

    def test_exact_id_lookup(self):
        self.assertEqual(self.catalog.get("test_001"), FIXTURE[0])
        self.assertIsNone(self.catalog.get("TEST_00"))

    def test_search_rejects_empty_query_and_invalid_limit(self):
        with self.assertRaises(ValueError):
            self.catalog.search(" ")
        with self.assertRaises(ValueError):
            self.catalog.search("火球", 0)

    def test_raw_values_survive_formatting(self):
        output = format_card(FIXTURE[0])
        self.assertIn("造成<b>3</b>点伤害。\n测试文本", output)
        self.assertIn('"COST": 2', output)
        self.assertIn("攻击：未知", output)
        self.assertIn("攻击：0", format_card(FIXTURE[1]))

    def test_reference_and_keyword_channels_are_visible_when_present(self):
        record = dict(FIXTURE[0], reference_tags=[{"tag": "SCRIPT_DATA", "value": 9}],
                      power_keyword_tags=[{"tag": "CHARGE", "value": 1}])
        output = format_card(record)
        self.assertIn("普通标签：", output)
        self.assertIn("引用标签：", output)
        self.assertIn('"tag": "SCRIPT_DATA"', output)
        self.assertIn("关键词标签：", output)
        self.assertIn('"tag": "CHARGE"', output)
        self.assertNotIn("引用标签：", format_card(FIXTURE[0]))

    def test_rejects_bad_catalog_structure(self):
        for records in ({}, [None], [{"id": ""}], [{"id": "X", "name": 5}],
                        [{"id": "X", "tags": []}], [{"id": "X"}, {"id": "x"}]):
            with self.subTest(records=records), self.assertRaises(CatalogError):
                CardCatalog(records)

    def test_file_loading_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "卡牌.json"
            path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8-sig")
            self.assertEqual(CardCatalog.from_file(path).get("TEST_001"), FIXTURE[0])
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(CatalogError):
                CardCatalog.from_file(path)
            with self.assertRaises(CatalogError):
                CardCatalog.from_file(Path(folder) / "missing.json")

    def test_cli_queries_and_missing_results(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cards.json"
            path.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")
            for args, status, expected in (
                (["search", "火球", "--limit", "1"], 0, "显示 1 条"),
                (["card", "TEST_001"], 0, "TEST_001"),
                (["card", "missing"], 1, "未找到匹配卡牌"),
            ):
                with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main([*args, "--data", str(path)]), status)
                    self.assertIn(expected, output.getvalue())
                    self.assertIn("不代表已实现", output.getvalue())

    def test_cli_missing_data_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing.json"
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main(["card", "TEST_001", "--data", str(missing)]), 2)
                self.assertIn("找不到卡牌数据", output.getvalue())


if __name__ == "__main__":
    unittest.main()
