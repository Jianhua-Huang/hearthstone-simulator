"""Reviewed physical hand/deck and generated hand halves use native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CORE_CFM_790','CORE_EX1_310','CORE_ICC_407','CORE_TRL_900','CATA_EVENT_000',
    'MEND_045','TIME_035','TIME_040','TIME_613','TLC_427','TLC_469','TLC_814')
LYNX,ROCK='TRL_348t','WW_001t'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-hand-interaction-generation-fragments-v1.json'
BATCH_HASH='30b838b0f121982f5dc66dee00cea1d0473eccd0690478334fa2b1549b285787'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+(LYNX,ROCK) or
            tuple(d['card_id']for d in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Hand-interaction assembly requires twelve complete sources and two fixed children')
    return data


def register_assemble_hand_interaction_generation_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Hand-interaction assembly changed a complete original source or child')
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),spell_damage=decl['spell_damage']),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']))))
