"""The complete declared Paladin Mech reference shares its original past domain."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope, pool_digest
from hs_sim.engine.pools import PoolCard, PoolMember, resolve_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from . import past_colossal_source_pool as prior_union
from .metadata import metadata_from_record
from .simple_followup_p89_cards import QUERIES

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-paladin-mech-source-binding-v1.json'
BATCH_HASH = 'bbc758af709fae67208c1d19ca11147f565aa6060af278f5b07d7c31e55c555e'
POLICY = 'cn37-local-past-paladin-mech-source-binding-v1'
SOURCE, POOL = 'TIME_016', 'constructed.past.cards'
QUERY = QUERIES[SOURCE]
METADATA_IDS = ('BOT_911','DEEP_015','SC_405')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or data['policy_id'] != POLICY or
            (data['source_card_id'],data['pool_id'],data['weight']) != (SOURCE,POOL,1) or
            canonical_digest(data['query']) != canonical_digest(asdict(QUERY)) or
            data['complete_for_declared_three_views'] is not True or
            any(data[k] for k in ('membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Past Paladin Mechs require their complete independently declared source')
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    previous = prior_union.load_batch()
    if (data['prior_union_document'] != prior_union.BATCH_PATH.relative_to(ROOT).as_posix() or
            canonical_digest(previous) != data['prior_union_canonical_sha256'] or
            canonical_digest(reference) != data['reference_canonical_sha256'] or
            data['source_producer'] != reference['source_producer'] or
            data['member_ids'] != reference['candidate_ids'] or
            data['prior_member_ids'] != previous['merged_member_ids'] or
            tuple(v['card_id'] for v in data['native_pins']) != tuple(data['member_ids']) or
            tuple(v['card_id'] for v in data['metadata_additions']) != METADATA_IDS):
        raise TargetValidationError('Past Paladin Mechs lost a full original reference, producer or native pin')
    left,right,union = data['prior_member_ids'],data['member_ids'],data['merged_member_ids']
    if (len(left) != 46 or len(right) != 27 or len(union) != len(set(union)) or len(union) != 72 or
            set(union) != set(left)|set(right) or data['shared_ids'] != ['TSC_030'] or
            [cid for cid in right if cid in left] != data['shared_ids'] or
            [cid for cid in union if cid in left] != left or [cid for cid in union if cid in right] != right):
        raise TargetValidationError('Past Paladin Mechs changed an original identity, order or shared weight')
    faction = data['faction_qualification']
    if (faction['candidate_ids'] != ['SC_401','SC_405','SC_412'] or
            faction['local_mode'] != 'allow_full_reference_without_faction_gate' or
            faction['hidden_gate_implemented'] is not False or faction['officially_certified'] is not False):
        raise TargetValidationError('Past Paladin Mechs lost the explicit unresolved faction eligibility policy')
    return data


def validate_native(registry, data):
    if canonical_digest(asdict(registry.card(SOURCE))) != data['source_producer']['definition_sha256']:
        raise TargetValidationError('Past Paladin Mechs changed their original native producer')
    for row in data['native_pins']:
        cid = row['card_id']
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Past Paladin Mech native dependency changed: '+cid)
        if row['pool_card_sha256'] is not None and (
                cid not in registry.pool_cards or canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Past Paladin Mech original printed metadata changed: '+cid)


def missing_metadata(registry):
    """Prepare every reviewed metadata addition before mutating the input."""
    data = load_batch(); validate_native(registry,data)
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    raw = {v['record']['id']:v['record'] for v in reference['candidate_records']}
    prepared = []
    for row in data['metadata_additions']:
        cid = row['card_id']; card = registry.card(cid); printed = PoolCard.from_definition(card)
        if (metadata_from_record(raw[cid]) != card.metadata or
                canonical_digest(asdict(printed)) != row['pool_card_sha256'] or
                cid in registry.pool_cards and registry.pool_card(cid) != printed):
            raise TargetValidationError('Past Paladin Mech metadata differs from its complete native row: '+cid)
        if cid not in registry.pool_cards: prepared.append(printed)
    return tuple(prepared)


def validate_union(registry, data, pool):
    prior_union.validate_union(registry,prior_union.load_batch(),pool,
        reviewed_member_ids=tuple(data['merged_member_ids']))
    if prior_union.projection(registry,pool.members,QUERY) != data['member_ids']:
        raise TargetValidationError('Past union changed the complete original Paladin Mech query projection')


def merge_pools(registry, context, pools):
    data = load_batch(); validate_native(registry,data)
    matches = [pool for pool in pools if pool.id == POOL]
    if len(matches) != 1: raise TargetValidationError('Past Paladin Mechs require their one original past inventory')
    original, = matches
    if original.target_id != context.target_id or original.mode != context.mode:
        raise TargetValidationError('Past Paladin Mechs borrowed another target or mode')
    prior_union.validate_union(registry,prior_union.load_batch(),original)
    merged = replace(original,version=POLICY+':'+original.version,
        members=tuple(PoolMember(cid) for cid in data['merged_member_ids']))
    validate_union(registry,data,merged)
    return tuple(merged if pool is original else pool for pool in pools)


def register_scope(registry, context):
    data = load_batch(); pool = registry.pool(POOL,context)
    validate_native(registry,data); validate_union(registry,data,pool)
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,
        POOL,context.target_id,context.mode,SOURCE,None,QUERY,pool_digest(pool)))
    members = resolve_candidates(registry,context,POOL,QUERY,source_card_id=SOURCE,exclude_source_by_rule=True)
    if [v.card_id for v in members] != data['member_ids'] or any(v.weight != 1 for v in members):
        raise TargetValidationError('Actual Paladin Mech request changed its original full identities or weights')
