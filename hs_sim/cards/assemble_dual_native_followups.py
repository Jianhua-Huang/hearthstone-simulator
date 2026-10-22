"""Five actual dual text sources, composing their original native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate, DUAL_TIMING
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('BE_151', 'BE_256', 'CORE_DMF_067', 'EDR_847', 'RLK_223')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-dual-native-followups-v1.json'
BATCH_HASH = 'd27a366f84592e1805c9f4200e2db6b1687b8db7dcc5096e31fd7cab40a87ef1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Dual native followups require five complete reviewed sources')
    return data


def register_assemble_dual_native_followups(registry):
    data = load_batch()
    # Complete the review before installing any template from this batch.
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        raw = row['record']
        original = registry.card(raw['id'])
        if (canonical_digest(row['definition']) != row['definition_sha256'] or
                canonical_digest(asdict(original)) != row['definition_sha256'] or
                raw['tags'].get('BATTLECRY') != 1 or raw['tags'].get('DEATHRATTLE') != 1 or
                raw['tags'].get('CRAFTABLE_OUTPUT_POWER') != 1 or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                original.battlecry != declaration['behavior_id'] or
                original.deathrattle != declaration['behavior_id'] or
                declaration['deathrattle_behavior_id'] is not None or
                declaration['timing'] != DUAL_TIMING):
            raise TargetValidationError('Dual native source lost its exact full definition: ' + raw['id'])
        registry.behavior(declaration['behavior_id'])
    for behavior_id in data['additional_required_behavior_ids']:
        registry.behavior(behavior_id)
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(DUAL_TIMING, tuple(Keyword(key) for key in declaration['keywords'])),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']),
                original.requires_target, original.targeting, original.target_rule)))
