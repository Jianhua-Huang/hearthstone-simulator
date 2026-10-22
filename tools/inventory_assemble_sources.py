"""Write pinned assembly-source observations without installing any game pool."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hs_sim.catalog import CardCatalog
from hs_sim.assemble_inventory import build_source_inventory, audit_registered_support
from tools.card_batch import save_new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--root-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--support-audit', type=Path)
    args = parser.parse_args(argv)
    targets = [args.output]+([args.support_audit] if args.support_audit is not None else [])
    if len({p.resolve() for p in targets}) != len(targets) or any(p.exists() for p in targets):
        parser.error('Use distinct new output files; previous inventories are preserved')
    raw, basis_raw = args.data.read_bytes(), args.root_manifest.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    basis = json.loads(basis_raw.decode('utf-8-sig'))
    if basis.get('source_sha256') != source_hash:
        parser.error('Root manifest belongs to a different complete source catalog')
    catalog = CardCatalog(json.loads(raw.decode('utf-8-sig')))
    result = build_source_inventory(catalog, basis['proposed_candidate_root_ids'])
    def path_label(path):
        path = path.resolve()
        return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    result['source'] = dict(path=path_label(args.data), sha256=source_hash)
    result['proposed_standard_basis'] = dict(path=path_label(args.root_manifest),
        sha256=hashlib.sha256(basis_raw).hexdigest(), membership_certified=False)
    support = None
    if args.support_audit is not None:
        from hs_sim.cards import build_registry
        registry = build_registry()
        support = audit_registered_support(result, catalog, registry.cards,
            registry.assemble_templates, registry.generation_families)
        support['content_version'] = registry.version
        support['registry_fingerprint'] = registry.fingerprint()
        support['source_sha256'] = source_hash
    if args.data.read_bytes() != raw or args.root_manifest.read_bytes() != basis_raw:
        raise RuntimeError('Complete source or proposed Standard basis changed during inventory')
    save_new(args.output, result)
    if support is not None:
        # Bind the actual saved bytes, including this host's newline encoding.
        support['inventory_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
        save_new(args.support_audit, support)
    print(json.dumps(dict(counts=result['counts'], formal_pool_complete=False,
        runtime_pool_installed=False), ensure_ascii=False))
    return result


if __name__ == '__main__': main()
