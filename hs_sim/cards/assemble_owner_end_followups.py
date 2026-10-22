"""Ten reviewed ending prefixes reuse their unchanged original native bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import EndTurnSpec, Keyword
from hs_sim.targets import TargetValidationError, canonical_digest
from .simple_followup_p26_cards import QUERIES as P26_QUERIES
from .simple_followup_p34_cards import QUERIES as P34_QUERIES

SOURCES = ('CATA_474', 'CORE_BT_493', 'CORE_YOP_034', 'EDR_462', 'EDR_530',
    'RLK_720', 'TIME_100', 'TLC_254', 'TLC_480', 'TLC_623')
QUERIES = {'CATA_474': P26_QUERIES['CATA_474'], 'EDR_530': P26_QUERIES['EDR_530'],
    'EDR_462': P34_QUERIES['EDR_462']}
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-owner-end-followups-v1.json'
BATCH_HASH = '6b476b8e318affd551a20fabae293cfe446f8f165aaa065bd9b036e6c879a86d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            data['numeric_normalizations'] != {'EDR_530': {'attack': 0}} or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Owner-end assembly requires all ten complete reviewed original cards')
    return data


def register_assemble_owner_end_followups(registry):
    data = load_batch()
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        original = registry.card(row['record']['id'])
        if (canonical_digest(asdict(original)) != row['definition_sha256'] or
                len(original.triggers) != 1 or original.triggers[0].event != 'turn_ended' or
                original.triggers[0].behavior_id != declaration['behavior_id'] or
                canonical_digest(asdict(original.triggers[0].end_turn)) !=
                    canonical_digest(declaration['end_turn'])):
            raise TargetValidationError('Owner-end assembly changed a complete original source or clock')
    for cid, query in QUERIES.items():
        if (canonical_digest(asdict(query)) != data['native_queries_sha256'][cid] or
                canonical_digest(data['native_queries'][cid]) != data['native_queries_sha256'][cid]):
            raise TargetValidationError('Owner-end assembly changed an original complete generation query')
    for behavior_id in data['required_original_behaviors']:
        registry.behavior(behavior_id)
    if any(cid in registry.assemble_templates or cid in registry.assemble_projections for cid in SOURCES):
        raise TargetValidationError('Owner-end assembly cannot partially duplicate its reviewed sources')
    for declaration in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix('end_turn', tuple(Keyword(key) for key in declaration['keywords']),
                EndTurnSpec(**declaration['end_turn'])),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']))))
