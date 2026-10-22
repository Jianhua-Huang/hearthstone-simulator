"""Two real Combo sources reuse native Combo and their complete original bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('CORE_EX1_131', 'TLC_522')
TOKEN, FAN, AUCTION = 'EX1_131t', 'EX1_129', 'JAIL_718'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-combo-followups-v1.json'
BATCH_HASH = '34e973b71a1f8e7b0411408e8a9402bfc01f4794ea72af6fce699b0365343743'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (TOKEN, FAN, AUCTION) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in data['existing_dependencies']) or
            canonical_digest(data['timing_amendment']['original_template']) !=
                data['timing_amendment']['original_template_sha256']):
        raise TargetValidationError('Combo assembly requires two full originals and their exact named dependencies')
    return data


def register_assemble_combo_followups(registry):
    data = load_batch()
    rows = {row['record']['id']: row for row in data['existing_dependencies']}
    for cid, row in rows.items():
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Combo assembly changed a complete original or named dependency')
    names = data['named_dependencies']
    if (names != dict(defias_token=TOKEN, defias_dbf=488, fan=FAN, fan_dbf=667) or
            rows[SOURCES[0]]['record']['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'] != names['defias_dbf'] or
            rows[TOKEN]['record']['dbf_id'] != names['defias_dbf'] or rows[FAN]['record']['dbf_id'] != names['fan_dbf']):
        raise TargetValidationError('Combo assembly changed its original Bandit or Fan identity')
    stages = data['utility_stage']
    if tuple(registry.behavior(stages['body_id']).__defaults__[0]) != tuple(stages['stage_ids']):
        raise TargetValidationError('Defias assembly changed its complete original ordered stage plan')
    for key, spec in stages['stage_specs'].items():
        if canonical_digest(asdict(registry.behavior(key).__defaults__[0])) != canonical_digest(spec):
            raise TargetValidationError('Defias assembly changed its complete original native summon step')
    registry.behavior(registry.card(FAN).on_play)
    amendment = data['timing_amendment']
    if registry.assemble_templates[AUCTION].suffix.behavior_id != amendment['body_id']:
        raise TargetValidationError('Reviewed ordinary Combo draw changed its exact original body')
    registry.extend_assemble_suffix_timings(AUCTION, tuple(amendment['add_timings']),
        expected_template_sha256=amendment['original_template_sha256'])
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'], tuple(Keyword(key) for key in row['keywords'])),
            AssembleSuffix(row['behavior_id'], tuple(row['allowed_timings']))))
