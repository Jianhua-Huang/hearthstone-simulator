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
MANIFEST_PATH = ROOT / 'data/cards/local-special-pool-bindings-v9.json'
MANIFEST_HASH = '94957f4a59242ad7eec3a8d9c5b52c8a9bfa792a735bc920f6532f795abcba4e'
FORMAT_VERSION = 'cn37-local-special-pools-v9'
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
    scoped=[p for item in value['scoped_bindings']for p in item['pool_ids']]
    if (len(scoped)!=len(set(scoped)) or set(scoped)!=set(value['scoped_pool_ids']) or
            not set(value['partially_scoped_pool_ids'])<=set(scoped) or
            set(scoped)&(set(names)|set(ORDINARY_POOLS)|set(value['unresolved_pool_ids']))):
        raise TargetValidationError('Scoped past views overlap an existing or unresolved pool domain')
    pack = value['pack_binding']
    if (pack['pool_id'] != 'constructed.standard_pack' or
            pack['pool_id'] in set(names) | set(scoped) | set(ORDINARY_POOLS) | set(value['unresolved_pool_ids']) or
            pack['complete_for_declared_inventory'] is not True or pack['formal_pool_complete'] is not False):
        raise TargetValidationError('Local pack inventory overlaps another domain or claims official completeness')
    rajh = value['rajh_binding']
    if (rajh['pool_id'] != 'constructed.assemble.rajh' or
            rajh['pool_id'] in set(names) | set(scoped) | set(ORDINARY_POOLS) | set(value['unresolved_pool_ids']) | {pack['pool_id']} or
            value['partial_inventory_pool_ids'] != [rajh['pool_id']] or
            (rajh['reported_total'], rajh['known_member_count'], rajh['missing_member_count']) != (15, 14, 1) or
            rajh['complete_for_declared_inventory'] is not True or rajh['formal_pool_complete'] is not False):
        raise TargetValidationError('Rajh known inventory lost its separate domain or explicitly missing member')
    zombeast = value['zombeast_binding']
    if (zombeast['pool_ids'] != ['crafted.zombeast.first', 'crafted.zombeast.second'] or
            set(zombeast['pool_ids']) & (set(names) | set(scoped) | set(ORDINARY_POOLS) |
                set(value['unresolved_pool_ids']) | {pack['pool_id'], rajh['pool_id']}) or
            zombeast['member_counts'] != [34, 38] or zombeast['eligible_counts'] != [34, 37] or
            zombeast['complete_for_declared_inventory'] is not True or zombeast['formal_pool_complete'] is not False):
        raise TargetValidationError('Zombeast local roles lost their independent inventories or explicit exclusion')
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
    from .cards.past_source_scoped_pools import local_pools,register_scopes,BATCH_PATH
    from .cards.one_cost_past_pool import local_pool,register_scope,BATCH_PATH as ONE_COST_PATH
    from .cards.standard_pack_inventory import local_pool as standard_pack_pool,BATCH_PATH as PACK_PATH
    from .cards.rajh_known_passive_pool import local_pool as rajh_pool,BATCH_PATH as RAJH_PATH
    from .cards.zombeast_reference_pools import local_pools as zombeast_pools,BATCH_PATH as ZOMBEAST_PATH
    paths=(BATCH_PATH,ONE_COST_PATH)
    if len(manifest['scoped_bindings'])!=len(paths):raise TargetValidationError('Scoped past source documents missing or duplicated')
    for item,path in zip(manifest['scoped_bindings'],paths):
        if (item['source_document']!=path.relative_to(ROOT).as_posix() or
                item['source_document_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise TargetValidationError('Scoped past source document changed')
    pack = manifest['pack_binding']
    if (pack['source_document'] != PACK_PATH.relative_to(ROOT).as_posix() or
            pack['source_document_sha256'] != hashlib.sha256(PACK_PATH.read_bytes()).hexdigest()):
        raise TargetValidationError('Local pack source document changed')
    rajh = manifest['rajh_binding']
    if (rajh['source_document'] != RAJH_PATH.relative_to(ROOT).as_posix() or
            rajh['source_document_sha256'] != hashlib.sha256(RAJH_PATH.read_bytes()).hexdigest()):
        raise TargetValidationError('Local Rajh source document changed')
    zombeast = manifest['zombeast_binding']
    if (zombeast['source_document'] != ZOMBEAST_PATH.relative_to(ROOT).as_posix() or
            zombeast['source_document_canonical_sha256'] != canonical_digest(
                json.loads(ZOMBEAST_PATH.read_text(encoding='utf8')))):
        raise TargetValidationError('Local Zombeast source document changed')
    pools = ordinary + _reviewed_sources(registry, manifest) + local_pools(registry,original.context) + (
        local_pool(registry,original.context),standard_pack_pool(registry,original.context),rajh_pool(registry,original.context)) + zombeast_pools(registry,original.context)
    binding = canonical_digest(dict(format=FORMAT_VERSION,
        original_binding=original.binding_digest, manifest=canonical_digest(manifest),
        inventories=[asdict(pool) for pool in pools]))
    target_id = FORMAT_VERSION + '-' + binding[:16]
    context = GenerationContext(target_id, original.context.mode)
    for pool in pools:
        registry.register_pool(replace(pool, target_id=target_id, mode=context.mode,
            version=manifest['policy_id'] + '-' + binding[:16] + ':' + pool.version))
    register_scopes(registry,context)
    register_scope(registry,context)
    policy = replace(original.policy, id=target_id + '.deck', target_id=target_id)
    registry.validate()
    return replace(original, target_id=target_id, binding_digest=binding,
        policy=policy, context=context)
