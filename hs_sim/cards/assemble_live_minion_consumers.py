"""Existing live-source consumers become reviewed independent text halves."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import HandActionSpec
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('BE_731', 'JAIL_435')
DEPENDENCIES = ('CORE_EX1_096', 'CORE_SW_072', 'CORE_REV_946', 'TIME_100', 'CORE_UNG_848', 'CATA_723')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-live-minion-consumers-v1.json'
BATCH_HASH = '203f62e4be39ce1321b022b66ffc4a95898ecc8093ab7183d3d0e751d0f9c355'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != SOURCES+DEPENDENCIES or
            tuple(x['card_id'] for x in data['reviewed_templates']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] or
                canonical_digest(x['definition']) != x['definition_sha256']
                for x in data['existing_dependencies'])):
        raise TargetValidationError('Live-source assembly changed its complete native bodies or declarations')
    return data


def register_assemble_live_minion_consumers(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Live-source assembly lost a complete original minion')
    for row in data['reviewed_templates']:
        original = registry.card(row['card_id'])
        actions = tuple(HandActionSpec(**s) for s in row['hand_actions'])
        if original.battlecry != row['body_id'] or actions != original.hand_actions:
            raise TargetValidationError('Live-source assembly changed its original Battlecry or hand action')
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('battlecry', hand_actions=actions),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
