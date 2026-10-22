"""Mythical Terror text halves reuse its original ordered forced-combat body."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix,AssembleSuffix,AssembleTemplate
from hs_sim.engine.model import EndTurnSpec,Keyword
from hs_sim.targets import TargetValidationError,canonical_digest

CARD='CORE_TTN_866'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/assemble-native-forced-attack-fragments-v1.json'
BATCH_HASH='11924427230c7b9d3c23587972b66df28d0cee17ab08ba05bb13c4d1ae410776'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'));rows=data['existing_dependencies']
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in rows)!=(CARD,) or
            any(data[k]for k in ('cards','dependencies','evidence_only','choice_only','skipped')) or
            canonical_digest(rows[0]['record'])!=rows[0]['record_sha256']):
        raise TargetValidationError('Forced-attack assembly requires its complete original Terror')
    return data


def register_assemble_native_forced_attack_fragments(registry):
    data=load_batch();row=data['existing_dependencies'][0];decl=data['reviewed_template'];original=registry.card(CARD)
    if(canonical_digest(asdict(original))!=row['definition_sha256'] or
            row['record']['text'].count('&')!=1 or row['record']['text_en'].count('&')!=1):
        raise TargetValidationError('Forced-attack assembly changed its complete original Terror')
    registry.register_assemble_template(AssembleTemplate(CARD,
        AssemblePrefix('end_turn',tuple(Keyword(k)for k in decl['keywords']),EndTurnSpec(**decl['end_turn'])),
        AssembleSuffix(decl['behavior_id'],tuple(decl['allowed_timings']))))
