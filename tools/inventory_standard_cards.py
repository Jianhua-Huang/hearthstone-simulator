"""Inventory all source rows against an explicit Standard candidate policy."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hs_sim.catalog import CardCatalog
from hs_sim.cards import build_registry
from hs_sim.standard_inventory import build_standard_inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new output file; old inventories are preserved')
    source_bytes, policy_bytes = args.data.read_bytes(), args.policy.read_bytes()
    policy = json.loads(policy_bytes.decode('utf-8-sig'))
    registry = build_registry()
    result = build_standard_inventory(CardCatalog(json.loads(source_bytes.decode('utf-8-sig'))), policy, registry.cards)
    if args.data.read_bytes() != source_bytes or args.policy.read_bytes() != policy_bytes:
        raise RuntimeError('Source catalog or candidate policy changed during inventory')
    result['source'] = dict(path=str(args.data.resolve()), sha256=hashlib.sha256(source_bytes).hexdigest())
    result['policy_sha256'] = hashlib.sha256(policy_bytes).hexdigest()
    result['content_version'] = registry.version
    result['registered_definition_count'] = len(registry.cards)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('source_record_count', 'candidate_root_count',
        'candidate_counts_by_set', 'registered_candidate_root_count', 'formal_pool_complete',
        'reachability_complete')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
