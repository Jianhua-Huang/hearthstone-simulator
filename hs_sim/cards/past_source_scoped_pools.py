"""Source-scoped complete known references, without claiming the global past domain."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardClass
from hs_sim.engine.pools import PoolDefinition,PoolMember
from hs_sim.engine.student_teaching import QUERY as TEACHER_QUERY
from hs_sim.targets import TargetValidationError,canonical_digest
from .past_summon_prices import PAST_TEN

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-source-scoped-inventories-v1.json'
BATCH_HASH='2f05e22fb63195d8b4bdd6f72dba9805a54c80c75eadb947307f2ed0df9a0f38'
POLICY='cn37-local-source-scoped-past-inventories-v1'
QUERIES={'current_class_collectible_spell_at_least_seven':TEACHER_QUERY,
         'current_class_collectible_minion_exactly_ten':PAST_TEN}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            tuple(r['record']['id']for r in data['cards'])!=('TIME_704','GDB_857') or
            any(data[k]for k in ('dependencies','evidence_only','skipped')) or len(data['official_faces'])!=4 or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False):
        raise TargetValidationError('Past views require complete pinned source identities and explicit local scope')
    records=data['cards']+data['existing_dependencies']
    if len(records)!=56 or any(canonical_digest(r['record'])!=r['record_sha256']for r in records):
        raise TargetValidationError('Past scope lost a complete existing root or member record')
    references={r['role']:r['reference']for r in data['reviewed_sources']}
    for row in data['inventories']:
        if (row['member_ids']!=references[row['reference_role']]['card_ids'] or row['weight']!=1 or
                row['current_class']!='druid' or row['query_role']not in QUERIES):
            raise TargetValidationError('Past scope changed original reference identities, roles or local weights')
    return data


def local_pools(registry,context):
    data=load_batch();rows={r['record']['id']:r for r in data['cards']+data['existing_dependencies']}
    result=[]
    for row in data['inventories']:
        for cid in row['member_ids']:
            if canonical_digest(asdict(registry.card(cid)))!=rows[cid]['definition_sha256']:
                raise TargetValidationError('A reviewed past member definition changed: '+cid)
        result.append(PoolDefinition(row['id'],POLICY+':'+row['reference_role'],context.target_id,context.mode,
            tuple(PoolMember(cid,row['weight'])for cid in row['member_ids']),complete=True))
    return tuple(result)


def register_scopes(registry,context):
    for row in load_batch()['inventories']:
        pool=registry.pool(row['id'],context)
        registry.register_generation_scope(GenerationScope(POLICY+':'+row['reference_role']+':'+context.target_id,
            pool.id,context.target_id,context.mode,row['source_card_id'],CardClass(row['current_class']),
            QUERIES[row['query_role']],pool_digest(pool)))
