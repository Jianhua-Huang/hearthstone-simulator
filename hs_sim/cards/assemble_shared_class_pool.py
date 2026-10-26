"""Published shared-class Assemble inventory, explicitly a local reference."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-shared-classes-v1.json'
BATCH_HASH = '7f5a643bebe7628560e82acb07a9f629318505c1b1358f4935bc8ebfd9edde4a'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            len(value['member_ids']) != 214 or value['member_ids'] != sorted(set(value['member_ids'])) or
            [row['record']['id'] for row in value['cards']] != value['member_ids'] or
            {group['card_class'] for group in value['classes']} != {c.value for c in CardClass if c!=CardClass.DREAM} or
            sum(group['declared_count'] for group in value['classes']) != 218 or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in value['cards'])):
        raise TargetValidationError('Shared Assemble inventory lost its full reviewed source')
    return value


def register_assemble_shared_class_pool(registry):
    value = load_batch(); members = value['member_ids']
    for row in value['cards']:
        cid = row['record']['id']; card = registry.card(cid)
        fragments = registry.assemble_templates if row['fragment_kind']=='template' else registry.assemble_projections
        fragment = fragments.get(cid)
        if (canonical_digest(asdict(card)) != row['reviewed_native_definition_sha256'] or
                fragment is None or canonical_digest(asdict(fragment)) != row['reviewed_fragment_sha256'] or
                registry.pool_card(cid).filter_signature() != PoolCard.from_definition(card).filter_signature()):
            raise TargetValidationError('Shared Assemble member lost its native body, metadata or fragment: '+cid)
    neutral = set(next(g['member_ids'] for g in value['classes'] if g['card_class']=='neutral'))
    for group in value['classes']:
        expected = set(group['member_ids']) | neutral
        actual = {cid for cid in members if any(c.value in (group['card_class'], 'neutral')
            for c in registry.card(cid).metadata.classes)}
        if (len(group['member_ids']) != group['declared_count'] or actual != expected):
            raise TargetValidationError('Shared Assemble class membership differs from printed card classes')
    registry.register_pool(PoolDefinition(value['pool_id'], value['policy_id'], value['source_target'],
        'experimental', tuple(PoolMember(cid, value['member_weight']) for cid in members),
        excluded_card_ids=tuple(value['excluded_card_ids']), complete=False))
