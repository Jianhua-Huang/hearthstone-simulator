"""Exact death-price and hero keyword aura declarations belong to text prefixes."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_static_materials import AssembleStaticMaterialSource
from hs_sim.engine.model import Keyword, KeywordAuraSpec, MinionDeathCostSpec
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('END_004', 'CORE_CATA_001')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-static-prefix-materials-v1.json'
BATCH_HASH = '35449e02a1318c0f4167274d5ed29e153115756590e8f211dc6d74c0e7d75e23'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies'])):
        raise TargetValidationError('Assembly static prefix material lost two complete originals')
    return data


def register_assemble_static_prefix_materials(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Assembly static material changed a complete original source')
    for row in data['reviewed_templates']:
        auras = tuple(KeywordAuraSpec(**{**spec, 'keyword': Keyword(spec['keyword']),
            'tribes_any': tuple(spec['tribes_any']), 'card_ids': tuple(spec['card_ids'])})
            for spec in row['keyword_auras'])
        death_cost = None if row['minion_death_cost'] is None else MinionDeathCostSpec(**row['minion_death_cost'])
        registry.register_assemble_static_material_source(AssembleStaticMaterialSource(row['card_id'], auras, death_cost))
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'], tuple(Keyword(key) for key in row['keywords'])),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
