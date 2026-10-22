"""Actual dual Battlecry/Deathrattle text, with both native entry identities."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import (AssemblePrefix,AssembleSuffix,AssembleTemplate,DUAL_TIMING)
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('BE_572','CORE_RLK_657','RLK_657','RLK_708')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-dual-prefix-fragments-v1.json'
BATCH_HASH='3d4d078ba6849fa63d6750e00ad12dfa5f06da2b2ae587a8f344f56211a7c2ff'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Dual assembly prefixes require four complete actual sources')
    return data


def register_assemble_dual_prefix_fragments(registry):
    data=load_batch()
    for row,declaration in zip(data['existing_dependencies'],data['reviewed_templates']):
        original=registry.card(row['record']['id']);raw=row['record']
        if(canonical_digest(asdict(original))!=row['definition_sha256'] or
                raw['tags'].get('BATTLECRY')!=1 or raw['tags'].get('DEATHRATTLE')!=1 or
                raw['text'].count('&')!=1 or raw['text_en'].count('&')!=1 or
                original.battlecry!=declaration['behavior_id'] or
                original.deathrattle!=(declaration['deathrattle_behavior_id']or declaration['behavior_id']) or
                declaration['timing']!=DUAL_TIMING):
            raise TargetValidationError('Dual assembly source lost its complete original native entries: '+original.id)
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(DUAL_TIMING,tuple(Keyword(k)for k in declaration['keywords'])),
            AssembleSuffix(declaration['behavior_id'],tuple(declaration['allowed_timings']),
                original.requires_target,original.targeting,original.target_rule,
                declaration['deathrattle_behavior_id'])))
