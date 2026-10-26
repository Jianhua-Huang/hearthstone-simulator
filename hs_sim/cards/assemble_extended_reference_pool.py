"""An expanded published inventory; older source pools remain reproducible."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_restrictions import source_restriction
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/assemble-extended-reference-v1.json'
BATCH_HASH = '1f1ba58057c62e0441dc1a17ad68ede4440703638afd542413610f540344b12e'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['member_ids']) != 259 or value['member_ids'] != sorted(set(value['member_ids'])) or
            [row['record']['id'] for row in value['cards']] != value['member_ids'] or
            len(value['identity_observations']) != 264 or
            len(value['body_context_amendments']) != 222 or
            len({row['card_id'] for row in value['body_context_amendments']}) != 222 or
            {row['card_id'] for row in value['identity_observations']} != set(value['member_ids']) or
            {g['card_class'] for g in value['classes']} != {c.value for c in CardClass if c!=CardClass.DREAM} or
            sum(g['declared_count'] for g in value['classes']) != 264 or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in value['cards'])):
        raise TargetValidationError('Extended Assemble inventory lost its reviewed identities or full source')
    return value


def register_assemble_extended_reference_pool(registry):
    value = load_batch(); members = value['member_ids']
    for row in value['cards']:
        cid = row['record']['id']; card = registry.card(cid)
        if (canonical_digest(asdict(card)) != row['reviewed_native_definition_sha256'] or
                registry.pool_card(cid).filter_signature() != PoolCard.from_definition(card).filter_signature()):
            raise TargetValidationError('Extended Assemble member lost its full native face or metadata: '+cid)
        restriction = source_restriction(registry, cid)
        if row['fragment_kind']=='local_restricted':
            # Keep the published identity. Its explicit user policy, rather
            # than adapter coverage, prevents it from entering either role.
            if restriction is None or canonical_digest(asdict(restriction)) != canonical_digest(row['local_restriction']):
                raise TargetValidationError('Extended Assemble member lost its explicit local restriction: '+cid)
        else:
            fragments = registry.assemble_templates if row['fragment_kind']=='template' else registry.assemble_projections
            fragment = fragments.get(cid)
            if (restriction is not None or fragment is None or
                    canonical_digest(asdict(fragment)) != row['reviewed_fragment_sha256']):
                raise TargetValidationError('Extended Assemble member lost its original fragment: '+cid)
    neutral = set(next(g['member_ids'] for g in value['classes'] if g['card_class']=='neutral'))
    for group in value['classes']:
        actual = {cid for cid in members if any(c.value in (group['card_class'], 'neutral')
            for c in registry.card(cid).metadata.classes)}
        if (len(group['member_ids']) != group['declared_count'] or
                actual != set(group['member_ids']) | neutral):
            raise TargetValidationError('Extended Assemble membership differs from printed classes')
    registry.register_pool(PoolDefinition(value['pool_id'], value['policy_id'], value['source_target'],
        'experimental', tuple(PoolMember(cid, value['member_weight']) for cid in members),
        excluded_card_ids=tuple(value['excluded_card_ids']), complete=False))
    for row in value['body_context_amendments']:
        fragments = registry.assemble_templates if row['fragment_kind']=='template' else registry.assemble_projections
        fragment = fragments.get(row['card_id'])
        if (fragment is None or fragment.suffix.behavior_id != row['behavior_id'] or
                set(row['add_timings']) & set(fragment.suffix.pending_timings)):
            raise TargetValidationError('Extended Assemble body changed or attempted to enable a deferred timing')
        registry.extend_assemble_suffix_timings(row['card_id'], tuple(row['add_timings']),
            expected_template_sha256=row['expected_fragment_sha256'])
