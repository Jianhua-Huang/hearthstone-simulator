"""Auditable target inventory; data presence is never execution coverage.

Schema 1 deliberately supports representative inventories only. A future complete
release needs a new schema with an audited legal/reachable pool denominator.
Unknown schema fields are rejected; opaque annotations belong in ``extensions``.
Null version/legality fields mean unknown, never zero, false, or supported.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

DEFAULT_TARGET_PATH = Path(__file__).resolve().parents[1] / "data/targets/local-2026-09-23.json"
IMPLEMENTATION_STATES = {"not_started", "partial", "implemented"}
VERIFICATION_STATES = {"unverified", "internally_tested", "officially_calibrated"}


class TargetValidationError(ValueError):
    """A target manifest makes an invalid or unsupported coverage declaration."""


@dataclass(frozen=True)
class TargetBaseline:
    target: dict[str, Any]
    support: dict[str, Any]


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _object(value: Any, fields: str, where: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        raise TargetValidationError(f"{where}: expected fields {fields}")
    return value


def _string(value: Any, where: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise TargetValidationError(f"{where}: expected nonempty string")


def _integer(value: Any, where: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not int or value < 0:
        raise TargetValidationError(f"{where}: expected nonnegative integer")


def _array(value: Any, where: str) -> list:
    if not isinstance(value, list):
        raise TargetValidationError(f"{where}: expected array")
    return value


def _strings(value: Any, where: str) -> list[str]:
    values = _array(value, where)
    for item in values:
        _string(item, where)
    if len(values) != len(set(values)):
        raise TargetValidationError(f"{where}: duplicate value")
    return values


def _digest(value: Any, where: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise TargetValidationError(f"{where}: expected lowercase SHA256")


def _extensions(value: Any, where: str) -> None:
    if not isinstance(value, dict):
        raise TargetValidationError(f"{where}: expected opaque annotation object")


def validate_baseline(target: dict, support: dict) -> None:
    """Validate all references and claims, without reading the original game files."""
    # This also prevents NaN/non-JSON objects in opaque metadata from being hidden.
    try:
        canonical_digest([target, support])
    except (TypeError, ValueError) as exc:
        raise TargetValidationError("manifest must contain finite JSON values") from exc
    _object(target, "schema_version target_id checked_on scope rules data runtime support_file evidence gaps extensions", "target")
    _object(support, "schema_version target_id coverage_kind full_pool_count mechanisms cards extensions", "support")
    if type(target["schema_version"]) is not int or target["schema_version"] != 1 or type(support["schema_version"]) is not int or support["schema_version"] != 1:
        raise TargetValidationError("unsupported target/support schema")
    for key in ("target_id", "checked_on", "support_file"):
        _string(target[key], f"target.{key}")
    if support["target_id"] != target["target_id"]:
        raise TargetValidationError("support.target_id does not match target")
    if support["coverage_kind"] != "representative_sample" or support["full_pool_count"] is not None:
        raise TargetValidationError("schema 1 cannot claim full-pool coverage or a full-pool denominator")
    _extensions(target["extensions"], "target.extensions")
    _extensions(support["extensions"], "support.extensions")
    scope = _object(target["scope"], "product modes support_level", "scope")
    if scope["product"] != "traditional_constructed" or scope["support_level"] not in {"none", "prototype_subset"}:
        raise TargetValidationError("schema 1 cannot declare complete support")
    if not _strings(scope["modes"], "scope.modes") or set(scope["modes"]) - {"standard", "wild"}:
        raise TargetValidationError("scope.modes: only standard/wild are supported targets")

    evidence = {}
    for row in _array(target["evidence"], "evidence"):
        _object(row, "id kind locator sha256 checked_on claims", "evidence row")
        for key in ("id", "kind", "locator", "checked_on", "claims"):
            _string(row[key], f"evidence.{key}")
        if row["id"] in evidence:
            raise TargetValidationError("duplicate evidence id")
        if row["kind"] not in {"local_file", "official_patch", "official_rule", "internal_tests", "calibration_record"}:
            raise TargetValidationError("unknown evidence kind")
        if row["kind"] == "local_file" or row["sha256"] is not None:
            _digest(row["sha256"], "evidence.sha256")
        evidence[row["id"]] = row

    def refs(values: Any, where: str) -> list[str]:
        values = _strings(values, where)
        if not values or set(values) - evidence.keys():
            raise TargetValidationError(f"{where}: missing evidence reference")
        return values

    rules = _object(target["rules"], "candidate_patch region effective_at hotfix_set_complete hotfixes evidence_refs", "rules")
    for key in ("candidate_patch", "region", "effective_at"):
        _string(rules[key], f"rules.{key}", nullable=True)
    if type(rules["hotfix_set_complete"]) is not bool:
        raise TargetValidationError("rules.hotfix_set_complete: expected boolean")
    refs(rules["evidence_refs"], "rules.evidence_refs")
    for hotfix in _array(rules["hotfixes"], "rules.hotfixes"):
        _object(hotfix, "patch announced_rollout_date region_applied_at deployment evidence_refs", "hotfix")
        for key in ("patch", "announced_rollout_date", "deployment"):
            _string(hotfix[key], f"hotfix.{key}")
        _string(hotfix["region_applied_at"], "hotfix.region_applied_at", nullable=True)
        refs(hotfix["evidence_refs"], "hotfix.evidence_refs")
    if rules["hotfix_set_complete"] and any(rules[k] is None for k in ("candidate_patch", "region", "effective_at")):
        raise TargetValidationError("complete hotfix set requires confirmed patch, region and effective time")

    data = _object(target["data"], "client_version build locale extracted_at files evidence_refs", "data")
    _string(data["client_version"], "data.client_version", nullable=True)
    _integer(data["build"], "data.build", nullable=True)
    for key in ("locale", "extracted_at"):
        _string(data[key], f"data.{key}")
    refs(data["evidence_refs"], "data.evidence_refs")
    files = _object(data["files"], "cards manifest dbf assembly product_db", "data.files")
    for name, descriptor in files.items():
        _object(descriptor, "path sha256", f"data.files.{name}")
        _string(descriptor["path"], f"data.files.{name}.path")
        _digest(descriptor["sha256"], f"data.files.{name}.sha256")
    if data["client_version"] is not None and data["build"] is not None and not data["client_version"].endswith(f".{data['build']}"):
        raise TargetValidationError("data client version/build disagree")
    runtime = _object(target["runtime"], "baseline_ruleset baseline_content snapshot_schema replay_schema rng python", "runtime")
    for key in ("baseline_ruleset", "baseline_content", "rng", "python"):
        _string(runtime[key], f"runtime.{key}")
    for key in ("snapshot_schema", "replay_schema"):
        _integer(runtime[key], f"runtime.{key}")
    gap_ids = set()
    for gap in _array(target["gaps"], "gaps"):
        _object(gap, "id description blocks_complete", "gap")
        for key in ("id", "description"):
            _string(gap[key], f"gap.{key}")
        if type(gap["blocks_complete"]) is not bool or gap["id"] in gap_ids:
            raise TargetValidationError("invalid or duplicate gap")
        gap_ids.add(gap["id"])
    if (rules["region"] is None or not rules["hotfix_set_complete"]) and not any(g["blocks_complete"] for g in target["gaps"]):
        raise TargetValidationError("unknown region/hotfix scope requires explicit blocking gap")

    def status(row: dict, where: str) -> None:
        if row["implementation"] not in IMPLEMENTATION_STATES or row["verification"] not in VERIFICATION_STATES:
            raise TargetValidationError(f"{where}: unknown implementation/verification status")
        found = refs(row["evidence_refs"], f"{where}.evidence_refs")
        kinds = {evidence[key]["kind"] for key in found}
        if row["verification"] != "unverified" and (row["implementation"] == "not_started" or "internal_tests" not in kinds):
            raise TargetValidationError(f"{where}: verified execution requires implementation and test evidence")
        if row["verification"] == "officially_calibrated" and "calibration_record" not in kinds:
            raise TargetValidationError(f"{where}: official description is not a calibration record")
        for key in ("notes", "stage"):
            _string(row[key], f"{where}.{key}")

    mechanisms = {}
    for row in _array(support["mechanisms"], "mechanisms"):
        _object(row, "id name stage dependencies implementation verification evidence_refs notes", "mechanism")
        for key in ("id", "name"):
            _string(row[key], f"mechanism.{key}")
        if row["id"] in mechanisms:
            raise TargetValidationError("duplicate mechanism id")
        _strings(row["dependencies"], "mechanism.dependencies")
        status(row, row["id"])
        mechanisms[row["id"]] = row
    visiting, visited = set(), set()

    def visit(key: str) -> None:
        if key not in mechanisms:
            raise TargetValidationError(f"unknown mechanism dependency: {key}")
        if key in visiting:
            raise TargetValidationError(f"mechanism dependency cycle: {key}")
        if key in visited:
            return
        visiting.add(key)
        for dep in mechanisms[key]["dependencies"]:
            visit(dep)
        visiting.remove(key)
        visited.add(key)

    for key in mechanisms:
        visit(key)
    cards = {}
    for row in _array(support["cards"], "cards"):
        _object(row, "id data data_sha256 dependencies reachable_cards stage implementation verification evidence_refs mode_legality notes", "card")
        _string(row["id"], "card.id")
        if row["id"] in cards:
            raise TargetValidationError("duplicate card id")
        if not isinstance(row["data"], dict) or row["data"].get("id") != row["id"]:
            raise TargetValidationError("card data id mismatch")
        _digest(row["data_sha256"], "card.data_sha256")
        if canonical_digest(row["data"]) != row["data_sha256"]:
            raise TargetValidationError(f"card snapshot hash mismatch: {row['id']}")
        for key in ("dependencies", "reachable_cards"):
            _strings(row[key], f"card.{key}")
        if set(row["dependencies"]) - mechanisms.keys():
            raise TargetValidationError("unknown card mechanism dependency")
        legality = _object(row["mode_legality"], "standard wild", "card.mode_legality")
        if any(value not in (None, "legal", "illegal") for value in legality.values()):
            raise TargetValidationError("mode legality must be legal, illegal or null (unknown)")
        status(row, row["id"])
        if row["implementation"] == "implemented" and any(mechanisms[key]["implementation"] == "not_started" for key in row["dependencies"]):
            raise TargetValidationError("implemented card depends on unimplemented mechanism")
        cards[row["id"]] = row
    for row in cards.values():
        if set(row["reachable_cards"]) - cards.keys():
            raise TargetValidationError("missing reachable-card reference")
        if row["implementation"] == "implemented" and any(cards[key]["implementation"] != "implemented" for key in row["reachable_cards"]):
            raise TargetValidationError("implemented card has unimplemented reachable content")


def _load_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise TargetValidationError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise TargetValidationError(f"non-finite JSON value: {value}")

    try:
        return json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    except json.JSONDecodeError as exc:
        raise TargetValidationError(f"invalid JSON in {path}: {exc}") from exc


def load_baseline(target_path: str | Path = DEFAULT_TARGET_PATH,
                  support_path: str | Path | None = None) -> TargetBaseline:
    """Load checked-in metadata only; does not require Hearthstone or extracted data."""
    target_path = Path(target_path)
    target = _load_json(target_path)
    if support_path is None:
        if not isinstance(target, dict) or not isinstance(target.get("support_file"), str):
            raise TargetValidationError("target.support_file is required")
        support_path = target_path.parent / target["support_file"]
    support = _load_json(Path(support_path))
    validate_baseline(target, support)
    return TargetBaseline(deepcopy(target), deepcopy(support))


def summarize_baseline(baseline: TargetBaseline) -> dict[str, Any]:
    """Return sample counts separately from unknown full-mode denominators."""
    validate_baseline(baseline.target, baseline.support)
    target, support = baseline.target, baseline.support
    return {
        "target_id": target["target_id"], "candidate_patch": target["rules"]["candidate_patch"],
        "data_client_version": target["data"]["client_version"], "region": target["rules"]["region"],
        "support_level": target["scope"]["support_level"], "coverage_kind": support["coverage_kind"],
        "full_pool_count": None, "full_pool_coverage_percent": None,
        "sample_cards": len(support["cards"]), "tracked_mechanisms": len(support["mechanisms"]),
        "card_implementation": dict(sorted(Counter(r["implementation"] for r in support["cards"]).items())),
        "card_verification": dict(sorted(Counter(r["verification"] for r in support["cards"]).items())),
        "mechanism_implementation": dict(sorted(Counter(r["implementation"] for r in support["mechanisms"]).items())),
        "mechanism_verification": dict(sorted(Counter(r["verification"] for r in support["mechanisms"]).items())),
        "blocking_gaps": [g["id"] for g in target["gaps"] if g["blocks_complete"]],
    }
