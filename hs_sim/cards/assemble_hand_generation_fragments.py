"""Reviewed hand-generation/discovery halves reuse their complete native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CATA_556','CORE_DRG_024','CORE_UNG_912','CORE_EDR_001','CORE_KAR_069',
    'CATA_484','CORE_BT_321','CORE_ONY_022','CORE_WON_096','JAIL_720')
CHILD='GAME_005'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-hand-generation-fragments-v1.json'
BATCH_HASH='b9283ac31bfd42ac412e7774778f7b31326581f255a30c543484ac9b21415ea5'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+(CHILD,) or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Hand-generation assembly requires ten complete sources and their fixed Coin')
    return data


def register_assemble_hand_generation_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Hand-generation assembly changed a complete original source or Coin')
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),spell_damage=decl['spell_damage']),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']))))
