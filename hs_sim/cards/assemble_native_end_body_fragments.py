"""Nine ordinary native ending bodies retain their original clocks and complete child."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import EndTurnSpec,Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CATA_133','CATA_475','CATA_476','CATA_999','DINO_132','EDR_816','EDR_942','EDR_971','JAIL_883')
CHILD='CATA_476t'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-end-body-fragments-v1.json'
BATCH_HASH='2216bc3478ad82b744d60d516036d6c57115bf0967a499e763dd031e983f1161'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+(CHILD,) or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in rows)):
        raise TargetValidationError('Native end assembly requires nine complete sources and their fixed child')
    return data


def register_assemble_native_end_body_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Native end assembly changed a complete original source or child')
    for decl in data['reviewed_templates']:
        original=registry.card(decl['card_id'])
        if original.triggers[0].behavior_id!=decl['behavior_id']:
            raise TargetValidationError('Native end assembly lost its complete original callback')
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix('end_turn',tuple(Keyword(k)for k in decl['keywords']),EndTurnSpec(**decl['end_turn'])),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']))))
