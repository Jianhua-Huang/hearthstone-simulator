"""Actual non-arrow hand buffs, removal and health halves reuse native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CORE_CFM_753','CORE_ICC_214','CORE_WW_329','TIME_603','CATA_304','CORE_UNG_848')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-buffs-removal-health-fragments-v1.json'
BATCH_HASH='0d1ff5fa1338b2401175005f988b48e13de5ad829a713069baaa0d9baa0e6a29'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Native buff/removal/health assembly requires six complete actual sources')
    return data


def register_assemble_native_buffs_removal_health_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        original=registry.card(row['record']['id'])
        if canonical_digest(asdict(original))!=row['definition_sha256']:
            raise TargetValidationError('Native buff/removal/health assembly changed a complete original source: '+original.id)
    for decl in data['reviewed_templates']:
        original=registry.card(decl['card_id']);timing=decl['timing']
        body=original.battlecry if timing=='battlecry'else original.deathrattle
        if body!=decl['behavior_id']:
            raise TargetValidationError('Native buff/removal/health assembly lost its exact original body: '+original.id)
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(timing,tuple(Keyword(k)for k in decl['keywords'])),
            AssembleSuffix(body,tuple(decl['allowed_timings']),original.requires_target,
                original.targeting,original.target_rule)))
