"""Actual constant-damage text halves reuse their complete native health bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CORE_EX1_319','CORE_LOOT_013','FIR_778','JAIL_007','TLC_249','EX1_319')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-damage-fragments-v1.json'
BATCH_HASH='f91c7125f2b000d44783a7f1decb755ec46cf4215e74a2a6bbaa7e4f96191040'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Native damage assembly requires six complete actual source cards')
    return data


def register_assemble_native_damage_fragments(registry):
    data=load_batch()
    for row,decl in zip(data['existing_dependencies'],data['reviewed_templates']):
        original=registry.card(row['record']['id']);timing=decl['timing']
        body=original.battlecry if timing=='battlecry'else original.deathrattle
        if(canonical_digest(asdict(original))!=row['definition_sha256'] or body!=decl['behavior_id']):
            raise TargetValidationError('Native damage assembly changed its whole original body: '+original.id)
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(timing,tuple(Keyword(k)for k in decl['keywords'])),
            AssembleSuffix(body,tuple(decl['allowed_timings']),original.requires_target,
                original.targeting,original.target_rule)))
