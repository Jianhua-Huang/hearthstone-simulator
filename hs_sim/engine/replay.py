"""Portable action replays with final and optional per-action consistency checks.

A replay stores one origin snapshot and accepted player actions.  It runs the
rules again rather than treating presentation events as executable instructions.
Hashes detect divergence and accidental edits; they are not digital signatures.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING

from .turn_clocks import history_action_from_dict
from .game import Game
from .runtime import RuntimeMode
from .serialization import canonical_hash, event_to_dict

if TYPE_CHECKING:
    from .registry import Registry
    from .resolver import Mechanics


SCHEMA_VERSION = 2
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ReplayError(ValueError):
    """A malformed or divergent replay; step 0 denotes its header/origin."""

    def __init__(self, reason: str, *, step: int = 0) -> None:
        self.step = step
        self.reason = reason
        location = "origin/header" if step == 0 else f"step {step}"
        super().__init__(f"replay {location}: {reason}")


def _fields(value: object, expected: set[str], name: str, step: int = 0) -> dict:
    if not isinstance(value, dict):
        raise ReplayError(f"{name} must be an object", step=step)
    if set(value) != expected:
        missing = sorted(expected - set(value))
        extra = sorted(map(str, set(value) - expected))
        raise ReplayError(f"invalid {name} fields (missing={missing}, extra={extra})", step=step)
    return value


def _validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ReplayError("replay must be an object")
    version = payload.get("schema_version")
    if type(version) is not int or version not in (1, SCHEMA_VERSION):
        raise ReplayError(f"unsupported schema_version: {version!r}")
    fields = {"schema_version", "origin", "actions"}
    if version == 2:
        fields |= {"final_state_hash", "final_events_hash"}
    data = _fields(payload, fields, "replay")
    if version == 2:
        for name in ("final_state_hash", "final_events_hash"):
            value = data[name]
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ReplayError(f"{name} must be a lowercase SHA-256 hex string")
    if not isinstance(data["origin"], dict):
        raise ReplayError("origin must be a snapshot object")
    if not isinstance(data["actions"], list):
        raise ReplayError("actions must be an array")
    for step, item in enumerate(data["actions"], start=1):
        record = _fields(item, {"action", "state_hash", "events_hash"}, "action record", step)
        if not isinstance(record["action"], dict):
            raise ReplayError("action must be an object", step=step)
        if version == 2 and record["state_hash"] is None and record["events_hash"] is None:
            continue
        for name in ("state_hash", "events_hash"):
            value = record[name]
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise ReplayError(f"{name} must be a lowercase SHA-256 hex string", step=step)
    return data


def build_replay(game: Game) -> dict:
    """Export final commitments now; only debug actions carry intermediate audits.

    Release records commands without encoding every intermediate state. Their
    replay checks the complete final state/RNG and event log, but cannot locate
    a state divergence at an unaudited intermediate step. Version 1 remains
    readable with its original mandatory per-action checks.
    """
    game._require_boundary()
    payload = {"schema_version": SCHEMA_VERSION, "origin": game.origin, "actions": game.history,
               "final_state_hash": game.state_hash(),
               "final_events_hash": canonical_hash([event_to_dict(event) for event in game._events])}
    _validate_payload(payload)
    return deepcopy(payload)


def replay(payload: object, registry: Registry, mechanics: Mechanics | None = None,
           *, mode: RuntimeMode | str = RuntimeMode.RELEASE) -> Game:
    """Execute a replay and reject the first invalid action or divergent result.

    Replay schema is validated before any actions run.  The engine validates the
    origin snapshot, ruleset, registry fingerprint, and mechanic implementation
    version.  No intermediate game is returned when validation fails.
    """
    data = _validate_payload(payload)
    try:
        game = Game.from_snapshot(deepcopy(data["origin"]), registry, mechanics=mechanics, mode=mode)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReplayError(f"cannot restore origin: {exc}") from exc
    for step, record in enumerate(data["actions"], start=1):
        try:
            action = history_action_from_dict(record["action"])
            result = game.apply(action)
        except (ValueError, TypeError, KeyError) as exc:
            raise ReplayError(f"invalid action: {exc}", step=step) from exc
        if record["state_hash"] is not None:
            state_hash = result.state_hash if result.state_hash is not None else game.state_hash()
            if state_hash != record["state_hash"]:
                raise ReplayError(
                    f"state_hash mismatch (expected {record['state_hash']}, got {state_hash})",
                    step=step,
                )
            events_hash = canonical_hash([event_to_dict(event) for event in result.events])
            if events_hash != record["events_hash"]:
                raise ReplayError(
                    f"events_hash mismatch (expected {record['events_hash']}, got {events_hash})",
                    step=step,
                )
        # Preserve which steps were actually audited when the source ran,
        # regardless of the host mode chosen to read it.
        game._history[-1] = deepcopy(record)
    if data["schema_version"] == 2:
        for name, actual in (
                ("final_state_hash", game.state_hash()),
                ("final_events_hash", canonical_hash([event_to_dict(e) for e in game._events]))):
            if actual != data[name]:
                raise ReplayError(f"{name} mismatch (expected {data[name]}, got {actual})",
                                  step=len(data["actions"]))
    return game


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def load_replay(path: str | Path, registry: Registry, mechanics: Mechanics | None = None,
                *, mode: RuntimeMode | str = RuntimeMode.RELEASE) -> Game:
    """Read UTF-8 JSON (an optional BOM is accepted), then validate and execute it."""
    try:
        content = Path(path).read_text(encoding="utf-8-sig")
        payload = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ReplayError(f"cannot read replay file: {exc}") from exc
    return replay(payload, registry, mechanics=mechanics, mode=mode)


def save_replay(game: Game, path: str | Path) -> Path:
    """Write a replay to an explicit path, creating its parent directories."""
    destination = Path(path)
    payload = build_replay(game)
    try:
        content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise ReplayError(f"cannot write replay file: {exc}") from exc
    return destination
