"""The complete known Mage teacher view beside the original Druid view."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolMember,resolve_candidates
from hs_sim.engine.student_teaching import QUERY
from hs_sim.targets import TargetValidationError,canonical_digest

ROOT=Path(__file__).resolve().parents[2]
SOURCE='TIME_704'
POOL='constructed.past.spells'
POLICY='cn37-local-teacher-mage-complete-view-v1'
BATCH_PATH=ROOT/'data/cards/past-teacher-mage-source-v1.json'
BATCH_HASH='dc8dac562e47d63586c364229790118432a780859a7e7c5acca52c34cae2eeac'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            (d['source_card_id'],d['pool_id'])!=(SOURCE,POOL)or
            [len(d[k])for k in('original_member_ids','mage_member_ids','merged_member_ids')]!=[21,24,44]or
            d['member_weight']!=1 or canonical_digest(d['query'])!=canonical_digest(asdict(QUERY))or
            any(d[k]for k in('new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Mage teacher requires complete fixed original views and explicit local scope')
    for path_key,hash_key in(('original_source_document','original_source_document_sha256'),('mage_reference_document','mage_reference_sha256')):
        if hashlib.sha256((ROOT/d[path_key]).read_bytes()).hexdigest()!=d[hash_key]:
            raise TargetValidationError('Mage teacher lost an unchanged full original source document')
    prior=json.loads((ROOT/d['original_source_document']).read_text(encoding='utf8'))
    row=next(v for v in prior['inventories']if v['source_card_id']==SOURCE)
    if (row['member_ids']!=d['original_member_ids']or d['merged_member_ids']!=list(dict.fromkeys(d['original_member_ids']+d['mage_member_ids']))or
            [v['card_id']for v in d['native_pins']]!=d['merged_member_ids']or
            [v['record']['id']for v in d['mage_complete_raw_records']]!=d['mage_member_ids']or
            d['original_source_record']!=next(v for v in prior['cards']if v['record']['id']==SOURCE)):
        raise TargetValidationError('Mage teacher changed original membership, order or source identity')
    for row in d['mage_complete_raw_records']:
        raw=row['record']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or not raw['collectible']or raw['cost']<7:
            raise TargetValidationError('Mage teacher lost a complete raw qualified seven-plus spell')
    return d


def validate_native(registry,d):
    if canonical_digest(asdict(registry.card(SOURCE)))!=d['original_source_record']['definition_sha256']:
        raise TargetValidationError('Mage teacher changed its original complete native source')
    for row in d['native_pins']:
        cid=row['card_id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Mage teacher lost complete original native material: '+cid)


def merge_pools(registry,context,pools):
    d=load_batch();validate_native(registry,d)
    matches=[p for p in pools if p.id==POOL]
    if len(matches)!=1:raise TargetValidationError('Mage teacher requires its one original past spell inventory')
    original,=matches
    if (original.target_id!=context.target_id or original.mode!=context.mode or not original.complete or original.excluded_card_ids or
            original.members!=tuple(PoolMember(cid)for cid in d['original_member_ids'])):
        raise TargetValidationError('Mage teacher cannot replace an unknown or cropped original inventory')
    merged=replace(original,version=POLICY+':'+original.version,members=tuple(PoolMember(cid)for cid in d['merged_member_ids']))
    return tuple(merged if p is original else p for p in pools)


def register_scope(registry,context):
    d=load_batch();validate_native(registry,d);pool=registry.pool(POOL,context)
    if not pool.complete or pool.excluded_card_ids or pool.members!=tuple(PoolMember(cid)for cid in d['merged_member_ids']):
        raise TargetValidationError('Mage teacher source lost its full independently reviewed union')
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,POOL,context.target_id,context.mode,
        SOURCE,CardClass.MAGE,QUERY,pool_digest(pool)))
    for hero,key in((CardClass.DRUID,'druid_actual'),(CardClass.MAGE,'mage_actual')):
        actual=resolve_candidates(registry,context,POOL,QUERY,current_class=hero,source_card_id=SOURCE,exclude_source_by_rule=True)
        if [asdict(v)for v in actual]!=d[key]:
            raise TargetValidationError('Mage teacher changed the complete actual original Druid or new Mage query')
