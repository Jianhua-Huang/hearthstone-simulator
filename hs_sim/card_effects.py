"""Conservative planning hints for every catalog record; never executable rules."""

from __future__ import annotations

from collections import Counter
import re


ORDINARY_KEYWORDS = frozenset((
    "Taunt", "Divine Shield", "Charge", "Rush", "Windfury", "Poisonous",
    "Lifesteal", "Stealth", "Reborn", "Elusive",
))
TRADITIONAL_TYPES = frozenset(("MINION", "SPELL", "WEAPON", "HERO", "HERO_POWER", "LOCATION"))
EFFECT_PATTERNS = (
    ("damage", r"\b(?:damage|attack)\b"),
    ("healing", r"\b(?:restore|heal)\b"),
    ("draw", r"\bdraw\b"),
    ("buff", r"\b(?:give|gain)\b|\+\d"),
    ("summon", r"\bsummon\b"),
    ("remove", r"\b(?:destroy|remove|discard)\b"),
    ("silence", r"\bsilence\b"),
    ("resource", r"\b(?:mana|armor|corpse|corpses|overload)\b"),
    ("discovery_generation", r"\b(?:discover|random|add)\b"),
    ("copy_transform", r"\b(?:copy|copies|transform)\b"),
    ("persistent_history", r"\b(?:this game|start of game|each turn|last turn|played|died)\b"),
    ("conditional", r"\b(?:if|while|unless)\b"),
)


def plain_text(value):
    return re.sub(r"<[^>]*>", "", value).strip()


def effect_groups(record):
    """Label candidates only; unknown text/metadata keeps a manual-review entry."""
    text = plain_text(record.get("text_en", ""))
    parts = tuple(part.strip(" .") for part in re.split(r"[,\n]+", text) if part.strip(" ."))
    power_tags = {row.get("tag") for row in record.get("power_keyword_tags", ()) if row.get("value")}
    ordinary_tags = {value.upper().replace(" ", "_") for value in ORDINARY_KEYWORDS}
    body_tags = {"BATTLECRY", "DEATHRATTLE", "SPELLPOWER", "TRIGGER_VISUAL", "START_OF_GAME_KEYWORD"}
    extra_body = bool(power_tags - ordinary_tags) or any(record.get("tags", {}).get(key) for key in body_tags)
    if record.get("type") == "MINION":
        if not text and not plain_text(record.get("text", "")) and not power_tags and not extra_body:
            return ("plain_minion_candidate",)
        if parts and all(part in ORDINARY_KEYWORDS for part in parts) and not extra_body:
            return ("keyword_minion_candidate",)
    groups = tuple(name for name, pattern in EFFECT_PATTERNS if re.search(pattern, text, re.I))
    # This remains explicit even when a familiar word was recognized. No parser
    # can infer ordering, targets, dependencies or complete semantics from it.
    return (*groups, "manual_effect_review")


def trigger_groups(record):
    text = plain_text(record.get("text_en", ""))
    result = []
    for key, pattern in (("battlecry", r"\bbattlecry\b"),
                         ("deathrattle", r"\bdeathrattle\b"),
                         ("turn", r"\b(?:start|end) of .*turn\b"),
                         ("event_trigger", r"\b(?:whenever|after)\b")):
        if re.search(pattern, text, re.I):
            result.append(key)
    if record.get("type") in ("SPELL", "HERO", "WEAPON"):
        result.append("on_play_review")
    return tuple(result)


def build_inventory(catalog, implemented_ids=()):
    """Retain all records and relations; raw collectible counts are not a pool."""
    dbf_ids = {row.get("dbf_id") for row in catalog.cards}
    implemented = set(implemented_ids)
    rows = []
    counts = Counter()
    for raw in sorted(catalog.cards, key=lambda row: row["id"]):
        groups = effect_groups(raw)
        counts.update(groups)
        related = list(raw.get("related_dbf_ids", ()))
        kind = raw.get("type")
        rows.append({
            "id": raw["id"], "dbf_id": raw.get("dbf_id"), "name": raw.get("name", ""),
            "type": kind, "collectible": raw.get("collectible"),
            "series_hint": raw["id"].split("_", 1)[0].upper(),
            "effect_groups": list(groups), "trigger_groups": list(trigger_groups(raw)),
            "scope": "needs_format_review" if kind in TRADITIONAL_TYPES else "other_type",
            "definition_registered": raw["id"] in implemented,
            "review_required": True, "related_dbf_ids": related,
            "missing_related_dbf_ids": [value for value in related if value not in dbf_ids],
        })
    return {
        "schema_version": 1, "formal_pool_complete": False,
        "classification_is_executable": False,
        "record_count": len(rows), "collectible_marked_count": sum(
            row["collectible"] is True for row in rows),
        "group_counts": dict(sorted(counts.items())), "records": rows,
        "limitations": [
            "Every source record is retained, including other modes and retired/preloaded cards.",
            "Series prefixes and collectible flags do not establish formal format legality.",
            "Effect/trigger hints require manual review; registered definitions are not calibration evidence.",
            "RELATED_CARDS is not an exhaustive graph of dynamically generated content.",
        ],
    }
