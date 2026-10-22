"""Reviewed fixed summons keep their original child IDs and native stage order."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CORE_AV_337','CORE_LOOT_368','DINO_130','EDR_492','TIME_059','TLC_225','TLC_237','TLC_443')
EXISTING_CHILDREN=('AV_337t','CS2_065','DINO_130t','EDR_492t','TLC_237t','TLC_249','TLC_443t')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-summon-fragments-v1.json'
BATCH_HASH='4de6383e3423efeb48596dbff4b2b5b1184b4cd2f7e0cfc1f1a0c823b1313dd5'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES+EXISTING_CHILDREN or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Native summon assembly requires its complete original sources and children')
    return data


def register_assemble_native_summon_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        original=registry.card(row['record']['id'])
        if canonical_digest(asdict(original))!=row['definition_sha256']:
            raise TargetValidationError('Native summon assembly changed its complete original source or child: '+original.id)
    for decl in data['reviewed_templates']:
        original=registry.card(decl['card_id']);timing=decl['timing']
        body=original.battlecry if timing=='battlecry'else original.deathrattle
        if body!=decl['behavior_id']:
            raise TargetValidationError('Native summon assembly lost its exact original staged body: '+original.id)
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(timing,tuple(Keyword(k)for k in decl['keywords'])),
            AssembleSuffix(body,tuple(decl['allowed_timings']),original.requires_target,
                original.targeting,original.target_rule)))
