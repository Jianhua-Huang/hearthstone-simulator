"""Reviewed actual draw/armor/heal halves over their original native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('BE_861', 'BAR_310', 'CORE_BAR_310', 'CORE_LOOT_413', 'CS3_024',
    'EDR_485', 'RLK_511', 'TIME_601', 'BAR_551', 'CORE_KAR_061', 'KAR_061')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-draw-armor-heal-fragments-v1.json'
BATCH_HASH = '91063e5875d5d0f11e61ecd0288714aadfd8cb59e07349c201fa9023fc157535'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(r['record']['id'] for r in rows) != SOURCES or
            tuple(t['card_id'] for t in data['reviewed_templates']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(r['record']) != r['record_sha256'] for r in rows)):
        raise TargetValidationError('Assembly draw/armor/heal halves require eleven whole original sources')
    return data


def register_assemble_draw_armor_heal_fragments(registry):
    data = load_batch()
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        original = registry.card(row['record']['id'])
        timing = declaration['timing']
        body = original.battlecry if timing == 'battlecry' else original.deathrattle
        if (canonical_digest(asdict(original)) != row['definition_sha256'] or
                body != declaration['behavior_id']):
            raise TargetValidationError('Assembly fragment changed its complete original body: '+original.id)
        registry.register_assemble_template(AssembleTemplate(original.id,
            AssemblePrefix(timing, tuple(Keyword(k) for k in declaration['keywords'])),
            AssembleSuffix(body, tuple(declaration['allowed_timings']),
                original.requires_target, original.targeting, original.target_rule)))
