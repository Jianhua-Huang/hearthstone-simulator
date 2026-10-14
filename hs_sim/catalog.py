"""Read and search extracted card data without executing card effects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "extracted" / "cards.json"


class CatalogError(ValueError):
    """The extracted catalog is missing or invalid."""


class CardCatalog:
    """An in-memory index of extracted records, preserving their original values."""

    def __init__(self, cards: list[dict[str, Any]]) -> None:
        if not isinstance(cards, list):
            raise CatalogError("卡牌数据的顶层必须是 JSON 数组。")
        self.cards: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        for index, card in enumerate(cards):
            if not isinstance(card, dict) or not isinstance(card.get("id"), str) or not card["id"]:
                raise CatalogError(f"第 {index + 1} 条卡牌记录缺少有效的 id。")
            for field in ("name", "name_en", "text", "text_en"):
                if field in card and not isinstance(card[field], str):
                    raise CatalogError(f"卡牌 {card['id']} 的 {field} 必须是字符串。")
            if "tags" in card and not isinstance(card["tags"], dict):
                raise CatalogError(f"卡牌 {card['id']} 的 tags 必须是 JSON 对象。")
            key = card["id"].casefold()
            if key in self._by_id:
                raise CatalogError(f"卡牌数据包含重复 id：{card['id']}。")
            self.cards.append(card)
            self._by_id[key] = card

    @classmethod
    def from_file(cls, path: str | Path = DEFAULT_DATA_PATH) -> CardCatalog:
        source = Path(path)
        try:
            # utf-8-sig also accepts ordinary UTF-8, and handles Windows BOM files.
            with source.open("r", encoding="utf-8-sig") as handle:
                cards = json.load(handle)
        except FileNotFoundError as exc:
            raise CatalogError(f"找不到卡牌数据：{source}。请先运行客户端数据抽取，或用 --data 指定 cards.json。") from exc
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogError(f"无法读取卡牌数据 {source}：{exc}") from exc
        return cls(cards)

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Match Chinese/English names or card IDs, in source order."""
        if limit < 1:
            raise ValueError("limit 必须大于 0。")
        needle = query.strip().casefold()
        if not needle:
            raise ValueError("搜索词不能为空。")
        matches = []
        for card in self.cards:
            if any(needle in card.get(field, "").casefold() for field in ("id", "name", "name_en")):
                matches.append(card)
                if len(matches) >= limit:
                    break
        return matches

    def get(self, card_id: str) -> dict[str, Any] | None:
        """Look up one complete card ID (case insensitive)."""
        return self._by_id.get(card_id.strip().casefold())


def format_card(card: dict[str, Any]) -> str:
    """Display raw text and tags, without interpreting them as effect code."""
    def shown(value: Any) -> str:
        return "未知" if value is None else str(value)

    collectible = card.get("collectible")
    collectible_label = "是" if collectible is True else "否" if collectible is False else "未知"
    lines = [
        f"{card.get('name') or '(无中文名称)'} [{card['id']}]",
        f"英文名：{card.get('name_en') or '(无)'}",
        f"DBF ID：{shown(card.get('dbf_id'))} | 类型：{shown(card.get('type'))} | 可收藏：{collectible_label}",
        f"费用：{shown(card.get('cost'))} | 攻击：{shown(card.get('attack'))} | 生命：{shown(card.get('health'))}",
        "中文原始文本：",
        card.get("text") or "(无)",
        "英文原始文本：",
        card.get("text_en") or "(无)",
        "普通标签：",
        json.dumps(card.get("tags", {}), ensure_ascii=False, indent=2, sort_keys=True),
    ]
    for field, label in (("reference_tags", "引用标签"), ("power_keyword_tags", "关键词标签")):
        if card.get(field):
            lines.extend([
                f"{label}：",
                json.dumps(card[field], ensure_ascii=False, indent=2, sort_keys=True),
            ])
    return "\n".join(lines)
