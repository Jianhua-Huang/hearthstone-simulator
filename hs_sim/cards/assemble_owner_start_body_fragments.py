"""The actual owner-start gate stays on its prefix, not in a borrowed body."""
from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.targets import TargetValidationError,canonical_digest
from .utility_cards import compile_body

CARD='CORE_NEW1_021'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-owner-start-body-fragments-v1.json'
BATCH_HASH='66d7152eb29ac3a377a4f1ad20f8318e52ee5a507cbecadb27b41827f599b520'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,'CORE_EX1_096') or
            tuple(t['card_id']for t in data['reviewed_templates'])!=(CARD,) or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in rows)):
        raise TargetValidationError('Owner-start assembly requires the complete actual native source')
    return data


def register_assemble_owner_start_body_fragments(registry):
    data=load_batch();row=data['existing_dependencies'][0];decl=data['reviewed_templates'][0]
    for source in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(source['record']['id'])))!=source['definition_sha256']:
            raise TargetValidationError('Owner-start assembly changed the complete original minion')
    body=compile_body(registry,decl['raw_steps'],False,set(registry._behaviors))
    if body!=decl['behavior_id']:
        raise TargetValidationError('Owner-start assembly changed its reviewed ungated native recipe')
    registry.register_assemble_template(AssembleTemplate(CARD,AssemblePrefix('start_turn'),
        AssembleSuffix(body,tuple(decl['allowed_timings'])),original_start_turn_id=decl['original_start_turn_id']))
    for amendment in data['profile_amendments']:
        current=asdict(registry.assemble_templates[amendment['card_id']])
        legacy=deepcopy(current)
        # This saved whole-template pin predates the end/death bridges and
        # prefix body. Each new field must be empty; all old fields stay pinned.
        if (legacy.pop('original_end_turn_id') is not None or
                legacy.pop('original_deathrattle_id') is not None or
                legacy['prefix'].pop('before_behavior_id') is not None or
                canonical_digest(legacy)!=amendment['original_template_sha256']):
            raise TargetValidationError('Owner-start assembly changed its complete original timing declaration')
        registry.extend_assemble_suffix_timings(amendment['card_id'],tuple(amendment['additional_allowed_timings']),
            expected_template_sha256=canonical_digest(current))
