"""Classify the full raw catalog without registering or silently dropping cards."""

from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hs_sim.catalog import CardCatalog
from hs_sim.card_effects import build_inventory
from hs_sim.cards import build_registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("Use a new output file; previous inventories are preserved")
    source = args.data.resolve()
    before = source.read_bytes()
    registry = build_registry()
    data = build_inventory(CardCatalog(json.loads(before.decode("utf-8-sig"))), registry.cards)
    if source.read_bytes() != before:
        raise RuntimeError("Source catalog changed during inventory")
    data["source"] = {"path": str(source), "sha256": hashlib.sha256(before).hexdigest()}
    data["content_version"] = registry.version
    data["registered_definition_count"] = len(registry.cards)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: data[key] for key in (
        "record_count", "collectible_marked_count", "formal_pool_complete",
        "group_counts", "registered_definition_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
