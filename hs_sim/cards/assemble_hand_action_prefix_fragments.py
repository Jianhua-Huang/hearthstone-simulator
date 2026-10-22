"""Two actual ordinary hand-action prefixes keep the native operation and body."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import HandActionSpec,Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

SOURCES=('CORE_SW_072','JAIL_457')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-hand-action-prefix-fragments-v1.json'
BATCH_HASH='16124b289b3baf822f7c00bd085f675787f53decf5fe9b0384573ee43c3c67f2'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=SOURCES or
            tuple(t['card_id']for t in data['reviewed_templates'])!=SOURCES or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in rows)):
        raise TargetValidationError('Assembly hand-action sources require both complete native cards')
    return data


def register_assemble_hand_action_prefix_fragments(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Assembly hand-action prefix changed a complete original source')
    for decl in data['reviewed_templates']:
        original=registry.card(decl['card_id'])
        if original.battlecry!=decl['behavior_id']:
            raise TargetValidationError('Assembly hand-action prefix lost its original native body')
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(decl['timing'],tuple(Keyword(k)for k in decl['keywords']),
                hand_actions=tuple(HandActionSpec(**s)for s in decl['hand_actions'])),
            AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']),original.requires_target,
                original.targeting,original.target_rule)))
