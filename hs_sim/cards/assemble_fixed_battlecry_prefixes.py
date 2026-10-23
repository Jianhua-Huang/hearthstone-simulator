"""Two original fixed Battlecries travel with their actual death prefixes."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_fixed_battlecry import AssembleFixedBattlecrySource
from hs_sim.engine.model import Keyword
from hs_sim.targets import TargetValidationError, canonical_digest
from .simple_followup_p27_cards import QUERIES, NURSE

SOURCES = ('BE_550', 'DINO_434')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-fixed-battlecry-prefixes-v1.json'
BATCH_HASH = '7590e9da6605755d165622aa417de2b4a8fa7c5a3c1627c1b3a6a75c2d22fb7b'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            set(data['native_queries']) != {NURSE+'.bc', NURSE+'.dr'} or
            any(canonical_digest(asdict(QUERIES[key])) != data['native_query_sha256'][key] or
                canonical_digest(query) != data['native_query_sha256'][key]
                for key, query in data['native_queries'].items())):
        raise TargetValidationError('Fixed Battlecry assembly lost complete original sources or generation queries')
    return data


def register_assemble_fixed_battlecry_prefixes(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Fixed Battlecry assembly changed a complete original minion')
    if any(cid in registry.assemble_templates or cid in registry.assemble_fixed_battlecry_sources for cid in SOURCES):
        raise TargetValidationError('Fixed Battlecry assembly cannot duplicate its actual sources')
    for row in data['reviewed_templates']:
        registry.register_assemble_fixed_battlecry_source(AssembleFixedBattlecrySource(
            row['card_id'], row['fixed_battlecry_id']))
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('deathrattle', tuple(Keyword(key) for key in row['keywords'])),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
