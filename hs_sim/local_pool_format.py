"""An opt-in CN37 host with reviewed, source-bound special pool inventories.

The original launch factory remains reproducible. This factory retains its
ordinary inventories and deck policy, but gives all installed local pools one
new target. Inventory completeness is local; formal CN certification is false.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from .engine.pools import GenerationContext
from .launch_candidate_format import build_cn37_launch_candidate_format
from .targets import TargetValidationError, canonical_digest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'data/cards/local-special-pool-bindings-v2.json'
MANIFEST_HASH = '2db88a6c2d13156b41bbfa9e09e145497c42a05ed644b6128f4b71d255f2e8f2'
FORMAT_VERSION = 'cn37-local-special-pools-v2'
ORDINARY_POOLS = ('constructed.cards', 'constructed.minions')


def load_bindings():
    value = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != MANIFEST_HASH or value['schema'] != 1 or
            value['formal_pool_complete'] is not False or not value['bindings']):
        raise TargetValidationError('Local special pools require their reviewed complete manifest')
    names = [item['pool_id'] for item in value['bindings']]
    if (len(names) != len(set(names)) or set(names) & set(ORDINARY_POOLS) or
            set(names) & set(value['unresolved_pool_ids'])):
        raise TargetValidationError('Local special pool bindings overlap or replace an unresolved inventory')
    return value


def _reviewed_sources(registry, manifest):
    result = []
    for item in manifest['bindings']:
        document = (ROOT / item['source_document']).resolve()
        if (not document.is_relative_to(ROOT) or
                hashlib.sha256(document.read_bytes()).hexdigest() != item['source_document_sha256']):
            raise TargetValidationError('Local special pool source document changed')
        source = registry.pool(item['pool_id'],
            GenerationContext(item['source_target_id'], item['source_mode']))
        if (canonical_digest(asdict(source)) != item['source_pool_sha256'] or
                [member.card_id for member in source.members] != item['member_ids'] or
                item['complete_for_declared_inventory'] is not True):
            raise TargetValidationError('Local special pool lost its original full inventory or weights')
        # The manifest never becomes a filter for executable coverage.
        for member in source.members:
            registry.card(member.card_id)
        result.append(replace(source, complete=True))
    return tuple(result)


def build_cn37_local_pool_format():
    """Build the fixed local format without a client, outputs, or network.

    New manifests add independently reviewed inventories through this shared
    binding step. Unresolved pool IDs are deliberately not installed.
    """
    manifest = load_bindings()
    original = build_cn37_launch_candidate_format()
    registry = original.registry
    ordinary = tuple(registry.pool(pool_id, original.context) for pool_id in ORDINARY_POOLS)
    pools = ordinary + _reviewed_sources(registry, manifest)
    binding = canonical_digest(dict(format=FORMAT_VERSION,
        original_binding=original.binding_digest, manifest=canonical_digest(manifest),
        inventories=[asdict(pool) for pool in pools]))
    target_id = FORMAT_VERSION + '-' + binding[:16]
    context = GenerationContext(target_id, original.context.mode)
    for pool in pools:
        registry.register_pool(replace(pool, target_id=target_id, mode=context.mode,
            version=manifest['policy_id'] + '-' + binding[:16] + ':' + pool.version))
    policy = replace(original.policy, id=target_id + '.deck', target_id=target_id)
    registry.validate()
    return replace(original, target_id=target_id, binding_digest=binding,
        policy=policy, context=context)
