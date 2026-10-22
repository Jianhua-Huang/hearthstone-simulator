"""Reviewed player modifiers reuse native budgets, quotes and logical programs."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CATA_458','BE_337','CORE_BT_416','CORE_SCH_713','EDR_464','EDR_890','EDR_861','TLC_257','TLC_450','MEND_800')
RECRUIT='CS2_101t'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-player-modifier-fragments-v1.json'
BATCH_HASH='04963845f491b8add5a25a6c18ea97ad6303b40c10d7d39407f0d876b1748e2d'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+(RECRUIT,) or
            tuple(d['card_id']for d in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Player-modifier assembly requires ten complete sources and their existing Recruit')
    return data


def register_assemble_player_modifier_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Player-modifier assembly changed a complete original source or Recruit')
    for key,pin in data['player_program_pins'].items():
        if canonical_digest(asdict(registry.player_effect(key)))!=canonical_digest(pin):
            raise TargetValidationError('Player-modifier assembly changed a complete original logical program')
    for decl in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(decl['card_id'],
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),spell_damage=decl['spell_damage']),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']))))
