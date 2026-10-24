"""Six whole native weapons lend their existing Battlecry/Deathrattle bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleProjection, AssembleSuffix
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest

STAFF, BLADE, SHOVEL, GLAIVE, CHAIN, COGHAMMER = SOURCES = (
    'TLC_EVENT_402', 'MEND_803', 'JAIL_380', 'TIME_444', 'JAIL_376', 'CORE_GVG_059')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-native-weapon-fragments-v1.json'
BATCH_HASH = '99f37be87faf7d9bc86b3cb8e5b95cf96b7b92cc2eb2d3ad4b3009a5d822bf3b'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_projections']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Native weapon fragments require six complete original sources')
    return data


def register_assemble_native_weapon_fragments(registry):
    data = load_batch()
    rows = {row['record']['id']: row for row in data['existing_dependencies']}
    # Validate every full original before installing any projection. The body
    # stays the original callable, including its public queries and programs.
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']
        original = registry.card(cid)
        row = rows[cid]
        raw = row['record']
        timing = declaration['timing']
        if (canonical_digest(asdict(original)) != row['definition_sha256'] or
                original.kind != CardType.WEAPON or raw['type'] != 'WEAPON' or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                timing not in ('battlecry', 'deathrattle') or
                getattr(original, timing) != declaration['behavior_id']):
            raise TargetValidationError('Native weapon fragment changed its complete original body: '+cid)
        registry.behavior(declaration['behavior_id'])
    program = data['original_player_effects'][BLADE]
    if canonical_digest(asdict(registry.player_effect(program['id']))) != canonical_digest(program):
        raise TargetValidationError('Recruit blade lost its complete original persistent program')
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']
        row = rows[cid]
        registry.register_assemble_projection(AssembleProjection(cid, CardType.WEAPON,
            row['definition_sha256'], row['record_sha256'], AssemblePrefix(declaration['timing']),
            AssembleSuffix(declaration['behavior_id'], tuple(declaration['allowed_timings']))))
