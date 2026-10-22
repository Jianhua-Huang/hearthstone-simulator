"""Matriarch's authored full-health gate belongs to its late end prefix."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.effects import Buff
from hs_sim.engine.model import EndTurnSpec
from hs_sim.targets import TargetValidationError,canonical_digest

CARD='CATA_305'
CONDITION='cards.assemble_conditional.self_full_health'
BODY='cards.assemble_conditional.self_health_growth'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-conditional-end-fragments-v1.json'
BATCH_HASH='67fc072b4fa298058d8850903a1e49e2588b1a54b14939135d7bbbaec0f4266f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,) or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            canonical_digest(rows[0]['record'])!=rows[0]['record_sha256']):
        raise TargetValidationError('Conditional end assembly requires the complete original Matriarch')
    return data


def register_assemble_conditional_end_fragments(registry):
    data=load_batch();row=data['existing_dependencies'][0];decl=data['reviewed_template']
    original=registry.card(CARD)
    if(canonical_digest(asdict(original))!=row['definition_sha256'] or
            row['record']['text'].count('&')!=1 or row['record']['text_en'].count('&')!=1):
        raise TargetValidationError('Conditional end assembly changed its complete original Matriarch')
    registry.register_trigger_condition(CONDITION,lambda c:c.source.health==c.source.max_health)
    registry.register_behavior(BODY,lambda c:(Buff(c.source_id,health=3,source_id=c.source_id),))
    registry.register_assemble_template(AssembleTemplate(CARD,
        AssemblePrefix('end_turn',end_turn=EndTurnSpec(**decl['end_turn']),condition_id=CONDITION),
        AssembleSuffix(BODY,tuple(decl['allowed_timings'])),
        original_end_turn_id=decl['original_end_turn_id']))
