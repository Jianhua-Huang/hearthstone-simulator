"""Native top-deck play and an original summon-before-buff Deathrattle."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_death_programs import AssembleDeferredDeathSource
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import CardType, EndTurnSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES=('EDR_031','BE_749')
DEPENDENCIES=('CORE_CS2_189','CORE_EX1_011','CORE_UNG_809','CORE_UNG_848','TIME_052',
    'CORE_SW_072','CORE_REV_946','RLK_061','RLK_061t')
SUMMON_QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-programs-v1.json'
BATCH_HASH='375c3e7dc346320f207c6b8a1b1a07e89aed66fd04c21a66bb04ba2859d8a265'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=SOURCES+DEPENDENCIES or
            tuple(x['card_id']for x in data['reviewed_templates'])!=SOURCES or
            tuple(x['card_id']for x in data['deferred_death_sources'])!=(SOURCES[1],) or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] or
                canonical_digest(x['definition'])!=x['definition_sha256']for x in data['existing_dependencies']) or
            canonical_digest(asdict(SUMMON_QUERY))!=data['native_summon_query_sha256'] or
            canonical_digest(data['native_summon_query'])!=data['native_summon_query_sha256'] or
            data['deferred_death_sources'][0]['query']!=data['native_summon_query']):
        raise TargetValidationError('Native programs changed complete originals or the actual summon query')
    return data


def register_assemble_native_programs(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Native program assembly lost a complete original definition')
    for row in data['deferred_death_sources']:
        registry.register_assemble_deferred_death_source(AssembleDeferredDeathSource(row['card_id'],
            row['original_deathrattle_id'],row['original_suffix_id'],row['pool_id'],SUMMON_QUERY))
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'],end_turn=None if row['end_turn']is None else EndTurnSpec(**row['end_turn']),
                before_behavior_id=row['before_behavior_id']),
            AssembleSuffix(row['body_id'],tuple(row['allowed_timings'])),
            original_end_turn_id=row['body_id']if row['timing']=='end_turn'else None,
            original_deathrattle_id=row['before_behavior_id']))
