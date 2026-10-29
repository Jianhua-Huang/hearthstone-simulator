"""The complete fixed local Mage/neutral view for the original Toki program."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope, pool_digest
from hs_sim.engine.issued_spell_sets import QUERY
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolMember, resolve_candidates
from hs_sim.engine.student_teaching import QUERY as TEACHER_QUERY
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'TIME_861'
POOL = 'constructed.past.spells'
POLICY = 'cn37-local-complete-toki-mage-source-v1'
BATCH_PATH = ROOT / 'data/cards/toki-mage-past-source-v1.json'
BATCH_HASH = '8591baeaed5fe9e818eec8f82388f2cfb622204bdd910470b5177dc88c3f5551'


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d) != BATCH_HASH or d['schema'] != 1 or d['policy_id'] != POLICY or
            (d['source_card_id'], d['pool_id'], d['current_class']) != (SOURCE, POOL, 'mage') or
            [len(d[k]) for k in ('prior_member_ids', 'mage_member_ids', 'merged_member_ids', 'actual_members')] != [44, 181, 201, 178] or
            d['member_weight'] != 1 or canonical_digest(d['query']) != canonical_digest(asdict(QUERY)) or
            not d['complete_for_declared_source_view'] or
            any(d[k] for k in ('new_standard_roots', 'membership_uses_executable_coverage', 'formal_pool_complete', 'cn_calibrated'))):
        raise TargetValidationError('Toki requires its complete original current-Mage view and explicit local scope')
    docs = {}
    for key, pin in (('source_document', 'source_document_canonical_sha256'),
            ('prior_teacher_document', 'prior_teacher_canonical_sha256'),
            ('mage_reference_document', 'mage_reference_canonical_sha256')):
        value = json.loads((ROOT / d[key]).read_text(encoding='utf8'))
        if canonical_digest(value) != d[pin]:
            raise TargetValidationError('Toki lost an unchanged complete original source document')
        docs[key] = value
    teacher = docs['prior_teacher_document']; ref = docs['mage_reference_document']
    if (d['original_source_record'] != docs['source_document']['cards'][0] or
            d['prior_member_ids'] != teacher['merged_member_ids'] or
            d['merged_member_ids'] != list(dict.fromkeys(d['prior_member_ids'] + d['mage_member_ids'])) or
            len(set(d['mage_member_ids'])) != 181 or
            set(d['mage_member_ids']) != set(ref['candidate_ids']) | {'RLK_590', 'WON_113'} or
            d['past_set_policy'] != ref['past_set_policy'] or
            [v['record']['id'] for v in d['mage_complete_raw_records']] != d['mage_member_ids'] or
            [v['card_id'] for v in d['native_pins']] != d['merged_member_ids'] or
            d['original_teacher_views'] != {'druid': teacher['druid_actual'], 'mage': teacher['mage_actual']}):
        raise TargetValidationError('Toki changed original raw membership, union order or teacher roles')
    for row in d['mage_complete_raw_records']:
        raw = row['record']; classes = metadata_from_record(raw).classes
        if (canonical_digest(raw) != row['record_sha256'] or raw['type'] != 'SPELL' or not raw['collectible'] or
                raw['card_set_id'] not in d['past_set_policy']['set_ids'] or
                not ({CardClass.MAGE, CardClass.NEUTRAL} & set(classes))):
            raise TargetValidationError('Toki lost a complete qualified original Mage or neutral spell')
    return d


def validate_native(registry, d):
    if canonical_digest(asdict(registry.card(SOURCE))) != d['source_definition_sha256']:
        raise TargetValidationError('Toki binding changed its original native source definition')
    for row in d['native_pins']:
        cid = row['card_id']
        if (canonical_digest(asdict(registry.card(cid))) != row['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid))) != row['pool_card_sha256']):
            raise TargetValidationError('Toki lost complete executable or metadata material: ' + cid)


def merge_pools(registry, context, pools):
    d = load_batch(); validate_native(registry, d); matches = [p for p in pools if p.id == POOL]
    if len(matches) != 1:
        raise TargetValidationError('Toki requires its one original shared past-spell inventory')
    original, = matches
    if (original.target_id != context.target_id or original.mode != context.mode or not original.complete or
            original.excluded_card_ids or original.members != tuple(PoolMember(cid) for cid in d['prior_member_ids'])):
        raise TargetValidationError('Toki cannot replace a cropped, reordered or unknown prior inventory')
    merged = replace(original, version=POLICY + ':' + original.version,
        members=tuple(PoolMember(cid) for cid in d['merged_member_ids']))
    return tuple(merged if p is original else p for p in pools)


def register_scope(registry, context):
    d = load_batch(); validate_native(registry, d); pool = registry.pool(POOL, context)
    if not pool.complete or pool.excluded_card_ids or pool.members != tuple(PoolMember(cid) for cid in d['merged_member_ids']):
        raise TargetValidationError('Toki lost the complete independently reviewed shared union')
    registry.register_generation_scope(GenerationScope(POLICY + ':' + context.target_id,
        POOL, context.target_id, context.mode, SOURCE, CardClass.MAGE, QUERY, pool_digest(pool)))
    actual = resolve_candidates(registry, context, POOL, QUERY, current_class=CardClass.MAGE,
        source_card_id=SOURCE, exclude_source_by_rule=True)
    if [asdict(v) for v in actual] != d['actual_members']:
        raise TargetValidationError('Toki changed the full actual candidate order, weights or existing eligibility policy')
    for hero in (CardClass.DRUID, CardClass.MAGE):
        rows = resolve_candidates(registry, context, POOL, TEACHER_QUERY, current_class=hero,
            source_card_id='TIME_704', exclude_source_by_rule=True)
        if [asdict(v) for v in rows] != d['original_teacher_views'][hero.value]:
            raise TargetValidationError('Toki source changed an original complete teacher view')
