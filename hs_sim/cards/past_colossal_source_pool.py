"""Two complete declared past views share one explicit local inventory union."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope, pool_digest
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolCard, PoolMember, matches_metadata, resolve_candidates
from hs_sim.targets import TargetValidationError, canonical_digest
from .past_source_scoped_pools import QUERIES as FRONTIER_QUERIES
from .simple_followup_p89_cards import QUERIES
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
BATCH_PATH = ROOT/'data/cards/past-colossal-source-binding-v1.json'
BATCH_HASH = '7be48c679d9f5f52cc3949c1ef45a9234c2ad462464230b14cefb4ccb3c487d9'
POLICY = 'cn37-local-cata-colossal-source-binding-v1'
SOURCE, POOL = 'CATA_EVENT_000', 'constructed.past.cards'
QUERY = QUERIES[SOURCE]
FRONTIER_QUERY = FRONTIER_QUERIES['current_class_collectible_minion_exactly_ten']


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or data['schema'] != 1 or data['policy_id'] != POLICY or
            data['source_card_id'] != SOURCE or data['pool_id'] != POOL or
            data['weight'] != 1 or data['shared_ids'] != ['TID_712'] or
            data['source_pool_complete_for_both_declared_views'] is not True or
            any(data[k] for k in ('membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated')) or
            canonical_digest(data['query']) != canonical_digest(asdict(QUERY)) or
            canonical_digest(data['frontier_query']) != canonical_digest(asdict(FRONTIER_QUERY))):
        raise TargetValidationError('CATA Colossal requires its complete independent source projections')
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    prior = json.loads((ROOT/data['frontier_document']).read_text(encoding='utf8'))
    frontier = next(v for v in prior['inventories'] if v['source_card_id'] == 'GDB_857')
    if (canonical_digest(reference) != data['reference_canonical_sha256'] or
            canonical_digest(prior) != data['frontier_canonical_sha256'] or
            data['source_producer'] != reference['source_producer'] or
            data['member_ids'] != reference['candidate_ids'] or data['frontier_member_ids'] != frontier['member_ids']):
        raise TargetValidationError('CATA Colossal lost an original full reference or Frontier inventory')
    left, right, union = data['frontier_member_ids'], data['member_ids'], data['merged_member_ids']
    if (len(left) != 34 or len(right) != 13 or len(union) != 46 or len(set(union)) != 46 or
            set(union) != set(left)|set(right) or
            [cid for cid in right if cid in left] != data['shared_ids'] or
            [cid for cid in union if cid in left] != left or [cid for cid in union if cid in right] != right):
        raise TargetValidationError('CATA Colossal union changed either original order, identity or shared weight')
    return data


def validate_native(registry, data):
    for row in data['native_pins']:
        cid = row['card_id']
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('CATA Colossal native dependency changed: '+cid)
        if row['pool_card_sha256'] is not None and (
                cid not in registry.pool_cards or canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('CATA Colossal printed candidate metadata changed: '+cid)


def missing_metadata(registry):
    """Prepare the one printed metadata addition without changing a registry."""
    data = load_batch(); validate_native(registry, data)
    reference = json.loads((ROOT/data['reference_document']).read_text(encoding='utf8'))
    rows = {v['record']['id']: v['record'] for v in reference['candidate_records']}
    prepared = []
    if [v['card_id'] for v in data['metadata_additions']] != ['TSC_639']:
        raise TargetValidationError('CATA Colossal lost its explicit printed metadata addition')
    for item in data['metadata_additions']:
        cid = item['card_id']; card = registry.card(cid)
        printed = PoolCard.from_definition(card)
        if (metadata_from_record(rows[cid]) != card.metadata or
                canonical_digest(asdict(printed)) != item['pool_card_sha256'] or
                cid in registry.pool_cards and registry.pool_card(cid) != printed):
            raise TargetValidationError('CATA Colossal metadata differs from its full original native row: '+cid)
        if cid not in registry.pool_cards: prepared.append(printed)
    return tuple(prepared)


def projection(registry, members, query, current_class=None):
    result = []
    for member in members:
        row = registry.pool_card(member.card_id)
        if matches_metadata(query, card_id=row.card_id, kind=row.kind, cost=row.cost,
                meta=row.metadata, spell_school=row.spell_school, keywords=row.keywords, current_class=current_class,
                printed_battlecry=row.battlecry, current_battlecry=row.battlecry,
                printed_deathrattle=row.deathrattle, printed_choose_one=row.choose_one, printed_attack=row.attack):
            result.append(member.card_id)
    return result


def validate_union(registry, data, pool, *, reviewed_member_ids=None):
    # A later independently pinned source may extend the physical inventory.
    # Its host supplies the full reviewed union, never a capability-filtered
    # subset. Retain the entire original projection as well as both queries.
    expected = tuple(data['merged_member_ids']) if reviewed_member_ids is None else reviewed_member_ids
    if (type(expected) is not tuple or len(expected) != len(set(expected)) or
            [cid for cid in expected if cid in data['merged_member_ids']] != data['merged_member_ids']):
        raise TargetValidationError('Past extension lost its complete original physical inventory')
    if (pool.id != POOL or not pool.complete or pool.excluded_card_ids or
            tuple(v.card_id for v in pool.members) != expected or any(v.weight != 1 for v in pool.members) or
            projection(registry, pool.members, QUERY) != data['member_ids'] or
            projection(registry, pool.members, FRONTIER_QUERY, CardClass.DRUID) != data['frontier_member_ids']):
        raise TargetValidationError('Past union does not preserve both complete original candidate views')


def merge_pools(registry, context, pools):
    data = load_batch(); matches = [v for v in pools if v.id == POOL]
    if len(matches) != 1: raise TargetValidationError('CATA Colossal requires one original Frontier inventory')
    original, = matches
    if (original.target_id != context.target_id or original.mode != context.mode or
            not original.complete or original.excluded_card_ids or
            original.members != tuple(PoolMember(cid) for cid in data['frontier_member_ids'])):
        raise TargetValidationError('CATA Colossal cannot replace an unknown or partial original past inventory')
    # Both inventories were fixed before consulting executable capabilities.
    validate_native(registry, data)
    merged = replace(original, version=POLICY+':'+original.version,
        members=tuple(PoolMember(cid) for cid in data['merged_member_ids']))
    validate_union(registry, data, merged)
    return tuple(merged if v is original else v for v in pools)


def register_scope(registry, context, *, reviewed_member_ids=None):
    data = load_batch(); pool = registry.pool(POOL, context)
    validate_native(registry, data); validate_union(registry, data, pool, reviewed_member_ids=reviewed_member_ids)
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,
        POOL, context.target_id, context.mode, SOURCE, None, QUERY, pool_digest(pool)))
    # The normal resolver owns bans, deduplication and pre-RNG executable checks.
    # A locally complete raw union is insufficient unless both true requests
    # still resolve to their exact full original identities and unit weights.
    for source, query, cl, ids in ((SOURCE, QUERY, None, data['member_ids']),
            ('GDB_857', FRONTIER_QUERY, CardClass.DRUID, data['frontier_member_ids'])):
        members = resolve_candidates(registry, context, POOL, query, current_class=cl, source_card_id=source)
        if [v.card_id for v in members] != ids or any(v.weight != 1 for v in members):
            raise TargetValidationError('Actual past source query differs from its complete independent projection')
