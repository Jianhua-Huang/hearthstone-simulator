"""Two real death prefixes reuse native damage and sampled friendly stat grants."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('CORE_WC_701', 'CORE_YOD_026')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-native-death-handovers-v1.json'
BATCH_HASH = '85fec725b922cf74da4548d510b7aacd59e9d76dcd52ed220173d31defdf0aed'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Native death assembly requires two complete original sources')
    return data


def register_assemble_native_death_handovers(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Native death assembly changed a complete original minion')
    for behavior in data['required_original_behaviors']:
        registry.behavior(behavior)
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('deathrattle', tuple(Keyword(key) for key in row['keywords'])),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
