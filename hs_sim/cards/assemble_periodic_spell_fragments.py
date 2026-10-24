"""Reviewed periodic text from two complete, independently executable spells."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleProjection, AssembleSuffix
from hs_sim.engine.model import CardType, DamageKind
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .native_followup_cards import deathrattle_position

SOURCES = ('FIR_902', 'TLC_232')
HATCHLING = 'TLC_237t'
PREFIX = 'cards.assemble_periodic_spell.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-periodic-spell-fragments-v1.json'
BATCH_HASH = '32a3054fd4874c2a7dd3d3bdf9d6a19a6454ada234aae2b75fdedb2f58de2d8d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != SOURCES+(HATCHLING,) or
            tuple(row['card_id'] for row in data['reviewed_projections']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Periodic projections require complete original spells and the exact Hatchling')
    return data


def register_assemble_periodic_spell_fragments(registry):
    data = load_batch()
    rows = {row['record']['id']: row for row in data['existing_dependencies']}
    for cid, row in rows.items():
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Periodic projection changed a complete original dependency: '+cid)
    for cid in SOURCES:
        raw = rows[cid]['record']
        original = registry.card(cid)
        program = data['original_player_effects'][cid]
        if (original.kind != CardType.SPELL or original.on_play is not None or
                original.ongoing_effect_id != program['id'] or
                canonical_digest(asdict(registry.player_effect(program['id']))) != canonical_digest(program) or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                raw['cost'] != 2 or raw['attack'] is not None or raw['health'] is not None):
            raise TargetValidationError('Periodic projection lost its full original source and owner clock')
    if (rows[SOURCES[0]]['record']['tags'].get('SIGIL') != 1 or
            rows[SOURCES[0]]['record']['tags'].get('349') != 1 or
            rows[SOURCES[1]]['record']['tags'].get('OBJECTIVE') != 1):
        raise TargetValidationError('Cinder immunity and Flock objective identity must stay on their originals')

    def cinder(c):
        return (RandomSplitDamage(c.player_id, None, c.source_id, 6,
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)

    def flock(c):
        cause = SummonCause.capture(c)
        position = deathrattle_position(c) if c.deathrattle is not None else None
        return tuple(SummonByCard(c.player_id, (SummonEntryMaterial(HATCHLING),),
            cause, position=position) for _ in range(3))

    registry.register_behavior(PREFIX+SOURCES[0], cinder)
    registry.register_behavior(PREFIX+SOURCES[1], flock)
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']
        row = rows[cid]
        registry.register_assemble_projection(AssembleProjection(cid, CardType.SPELL,
            row['definition_sha256'], row['record_sha256'],
            AssemblePrefix(declaration['prefix']),
            AssembleSuffix(declaration['body'], tuple(declaration['allowed_timings']))))
