"""Original corpse provider material and a one-corpse paid Battlecry prefix."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_corpse_prefixes import AssembleCorpseGainSource,AssemblePaidBattlecrySource
from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.corpse_gains import CorpseGainProfile
from hs_sim.engine.pools import DiscoverFromPool
from hs_sim.targets import TargetValidationError,canonical_digest
from .simple_followup_p76_cards import QUERIES

SOURCES=('CORE_EDR_003','CORE_RLK_066')
DEPENDENCIES=('CORE_SW_072','CORE_EX1_096','CORE_UNG_848','CORE_REV_946','BE_749',
    'CORE_RLK_712','RLK_024','RLK_067','CORE_UNG_084')
PREFIX='cards.assemble_native_corpse_prefixes.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-corpse-prefixes-v1.json'
BATCH_HASH='7e9ef22c429dd51cae00f6978fbb8bb68e55ddd9262758b069dc13a46cf42fde'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or
            tuple(x['record']['id']for x in data['existing_dependencies'])!=SOURCES+DEPENDENCIES or
            tuple(x['card_id']for x in data['reviewed_templates'])!=SOURCES or
            tuple(x['card_id']for x in data['corpse_gain_sources'])!=(SOURCES[0],)or
            tuple(x['card_id']for x in data['paid_battlecry_sources'])!=(SOURCES[1],)or
            any(data[k]for k in('cards','dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']or canonical_digest(x['definition'])!=x['definition_sha256']for x in data['existing_dependencies'])or
            canonical_digest(asdict(QUERIES['blood']))!=data['native_blood_query_sha256']or
            canonical_digest(data['native_blood_query'])!=data['native_blood_query_sha256']or
            data['paid_battlecry_sources'][0]['query']!=data['native_blood_query']):
        raise TargetValidationError('Native corpse prefixes changed complete originals or Blood discovery query')
    return data


def register_assemble_native_corpse_prefixes(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Native corpse prefixes lost a complete original definition')
    registry.register_behavior(PREFIX+'discover',lambda c:(DiscoverFromPool(c.player_id,'constructed.cards',
        QUERIES['blood'],source_id=c.source_id),))
    for row in data['corpse_gain_sources']:
        registry.register_assemble_corpse_gain_source(AssembleCorpseGainSource(row['card_id'],CorpseGainProfile(**row['native_profile'])))
    for row in data['paid_battlecry_sources']:
        registry.register_assemble_paid_battlecry_source(AssemblePaidBattlecrySource(row['card_id'],row['original_battlecry_id'],row['pool_id'],QUERIES['blood']))
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('battlecry',before_behavior_id=row['before_behavior_id']),
            AssembleSuffix(row['body_id'],tuple(row['allowed_timings'])),
            original_battlecry_id=row['before_behavior_id']))
