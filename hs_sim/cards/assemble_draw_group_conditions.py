"""Native draw-two qualifiers and independent Water Elemental/Charge rewards."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_draw_groups import AssembleDrawGroupSource
from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.model import BoardPresenceReference, CardType, Keyword, Zone
from hs_sim.engine.sacrifice import GrantCapturedKeyword
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest

SOURCES = ('BE_270', 'JAIL_462')
WATER, RUST, MAZE, PHOENIX = 'CS2_033', 'CORE_SW_072', 'CORE_REV_308', 'CORE_UNG_084'
DEPENDENCIES = (WATER, RUST, MAZE, PHOENIX)
PREFIX = 'cards.assemble_draw_group_conditions.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-draw-group-conditions-v1.json'
BATCH_HASH = 'a0da3ca8f4841e5bff4b5c7bb4e839a0dfc8a6640c7783fd0745f1ca0684b55d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != SOURCES+DEPENDENCIES or
            tuple(x['card_id'] for x in data['native_profiles']) != SOURCES or
            tuple(x['card_id'] for x in data['reviewed_templates']) != SOURCES or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] or
                canonical_digest(x['definition']) != x['definition_sha256']
                for x in data['existing_dependencies'])):
        raise TargetValidationError('Draw-qualified assembly changed its complete originals or source policies')
    return data


def register_assemble_draw_group_conditions(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Draw-qualified assembly lost a complete native card')

    def water(c):
        return (SummonByCard(c.player_id, (SummonEntryMaterial(WATER),), SummonCause.capture(c)),)

    def charge(c):
        if c.draw_group is not None:
            residence = c.draw_group.reward.source
        else:
            residence = (BoardPresenceReference.capture(c.state, c.source_id)
                if c.source.kind == CardType.MINION and c.source.zone == Zone.BOARD else None)
        return () if residence is None else (GrantCapturedKeyword(residence, Keyword.CHARGE, c.source_id),)

    registry.register_behavior(PREFIX+'water', water)
    registry.register_behavior(PREFIX+'charge', charge)
    for row in data['native_profiles']:
        registry.register_assemble_draw_group_source(AssembleDrawGroupSource(**row))
    for row in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix('battlecry', before_behavior_id=row['original_battlecry_id']),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings'])),
            original_battlecry_id=row['original_battlecry_id']))
