"""Reviewed native Attack-spell and Dragon source materials for Assemble."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate, TIMINGS
from hs_sim.engine.model import EndTurnSpec, Keyword
from hs_sim.engine.source_attack_spells import SourceAttackSpellProfile, request
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('CATA_464', 'CATA_478')
BREATH, DRAGON = 'CATA_464t', 'CATA_478t'
ATTACK_BODY = 'cards.assemble_source_stat.attack_spell'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-source-stat-materials-v1.json'
BATCH_HASH = 'dd11a766f5a377c70bfcebd3a27acb7521ecce5be504e340b2723dda2b463895'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES+(BREATH, DRAGON) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies']) or
            canonical_digest(data['native_damage_profile']) != data['native_damage_profile_sha256'] or
            data['source_attack_spell_profiles'] != [dict(card_id=BREATH,
                source_card_id=SOURCES[0], behavior_id=ATTACK_BODY)] or
            data['reviewed_templates'][0]['allowed_timings'] != sorted(TIMINGS) or
            data['reviewed_templates'][1]['allowed_timings'] != sorted(TIMINGS-{'deathrattle'}) or
            data['reviewed_templates'][1]['pending_timings'] != ['deathrattle']):
        raise TargetValidationError('Source-stat assembly lost its originals, native materials or pending context')
    return data


def register_assemble_source_stat_materials(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Source-stat assembly changed a complete original or token')
    native = registry.spell_value_profiles.get(BREATH)
    if (native is None or canonical_digest(asdict(native)) !=
            data['native_damage_profile_sha256']):
        raise TargetValidationError('Source-stat assembly changed the original Deathrattle spell profile')
    registry.register_behavior(ATTACK_BODY, lambda c: (request(c, BREATH),))
    for row in data['source_attack_spell_profiles']:
        registry.register_source_attack_spell_profile(SourceAttackSpellProfile(**row))
    for row in data['reviewed_templates']:
        end = EndTurnSpec(**row['end_turn']) if row['end_turn'] is not None else None
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'], tuple(Keyword(k) for k in row['keywords']), end),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']),
                deathrattle_behavior_id=row['deathrattle_body_id'], pending_timings=tuple(row['pending_timings'])),
            original_end_turn_id=row['original_end_turn_id']))
