"""Reuse Thal'ena's native power installation, including its explicit limits."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCE = 'JAIL_446'
DEPENDENCIES = ('JAIL_446hp', 'CORE_SW_072', 'CORE_UNG_848', 'BE_044', 'BE_229',
                'CORE_EX1_110', 'CORE_REV_946')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-secondary-power-followups-v1.json'
BATCH_HASH = '1aa8df567fc31950dbbb86ea00f5de7fe738c123818433205eab45d4c17e8af6'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != (SOURCE, *DEPENDENCIES) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != (SOURCE,) or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Secondary power assembly lost its complete original records or definitions')
    return data


def register_assemble_secondary_power_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Secondary power assembly changed a complete original definition')
    row = data['reviewed_templates'][0]
    registry.register_assemble_template(AssembleTemplate(SOURCE,
        AssemblePrefix(row['timing']), AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
