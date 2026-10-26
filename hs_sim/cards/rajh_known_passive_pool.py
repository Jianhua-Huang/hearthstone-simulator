"""All fourteen published Rajh identities and explicit passive carrier policy."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.assembled_powers import profile_signature
from hs_sim.engine.model import Keyword
from hs_sim.engine.pools import PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest


ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT / 'data/cards/rajh-known-passive-pool-v1.json'
BATCH_HASH = '611ffd06a51f3341a0edaaf4a27b71539a20d5506e866dfc8f718a2915bfe56d'
CARD, POWER, POOL = 'BE_004', 'BE_004p', 'constructed.assemble.rajh'
POLICY = 'cn37-local-rajh-known-passive-inventory-v1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or
            (data['policy_id'], data['pool_id'], data['source_card_id'], data['power_template_id']) != (POLICY, POOL, CARD, POWER) or
            len(data['candidate_ids']) != 14 or len(set(data['candidate_ids'])) != 14 or
            data['candidate_ids'] != [r['card_id'] for r in data['candidate_reference']['reference']['observations']] or
            (data['reported_total'], data['reported_missing_member_count']) != (15, 1) or
            data['secondary_projection_ids'] != ['TLC_833'] or
            data['ignored_prefix_keywords'] != ['elusive', 'divine_shield'] or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            data['complete_for_declared_known_inventory'] is not True or data['skipped']):
        raise TargetValidationError('Rajh requires all fourteen original known identities and its recorded missing member')
    rows = data['cards'] + data['existing_dependencies'] + data['evidence_only']
    if (len(rows) != 19 or len({r['record']['id'] for r in rows}) != 19 or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows) or
            canonical_digest(data['base_profile']) != data['base_profile_sha256']):
        raise TargetValidationError('Rajh source, original compatible fragments or base template changed')
    return data


def local_pool(registry, context):
    data = load_batch()
    for row in data['existing_dependencies']:
        cid = row['record']['id']
        card = registry.card(cid)
        fragment = registry.assemble_templates.get(cid) or registry.assemble_projections.get(cid)
        if (canonical_digest(asdict(card)) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256'] or
                fragment is None or canonical_digest(asdict(fragment)) != row['fragment_sha256']):
            raise TargetValidationError('Rajh member lost its complete native face or original text halves: ' + cid)
    original = registry.assembled_power_profiles[POWER]
    if canonical_digest(profile_signature(original)) != data['base_profile_sha256']:
        raise TargetValidationError('Rajh lost the original passive template or its previous approved sources')
    sources = tuple(dict.fromkeys((*original.reviewed_fragment_ids, *data['candidate_ids'])))
    registry.extend_assembled_power_profile(replace(original, reviewed_fragment_ids=sources,
        secondary_projection_ids=tuple(data['secondary_projection_ids']),
        ignored_prefix_keywords=tuple(Keyword(k) for k in data['ignored_prefix_keywords'])))
    return PoolDefinition(POOL, POLICY, context.target_id, context.mode,
        tuple(PoolMember(cid, 1) for cid in data['candidate_ids']), complete=True)
