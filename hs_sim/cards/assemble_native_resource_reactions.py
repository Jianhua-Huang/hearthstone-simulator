"""Actual last-mana events and native once-per-turn spell-damage subjects."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate, validate_template
from hs_sim.engine.assemble_reactions import AssembleNativeReactionSource
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .simple_followup_p30_cards import QUERIES, MAZE

SOURCES = ('CATA_130', 'CATA_487')
DONORS = ('CORE_SW_072', 'CORE_REV_308', 'CORE_KAR_061', 'CORE_REV_946')
PREFIX = 'cards.assemble_native_resource_reactions.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-native-resource-reactions-v1.json'
BATCH_HASH = 'cf49608feb1a93c08f08eb776c6cca0090a98666d765dea34d706d8056a4206a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != SOURCES+DONORS or
            tuple(x['card_id'] for x in data['native_profiles']) != SOURCES or
            tuple(x['card_id'] for x in data['reviewed_templates']) != SOURCES or
            tuple(x['card_id'] for x in data['amendments']) != DONORS or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(x['record']) != x['record_sha256'] or
                canonical_digest(x['definition']) != x['definition_sha256'] for x in data['existing_dependencies']) or
            canonical_digest(data['maze_query']) != data['maze_query_sha256'] or
            canonical_digest(asdict(QUERIES[MAZE])) != data['maze_query_sha256']):
        raise TargetValidationError('Native resource assembly changed its complete sources or reviewed contexts')
    return data


def register_assemble_native_resource_reactions(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Native resource assembly changed a complete original')
    for row in data['amendments']:
        old = registry.assemble_templates.get(row['card_id'])
        if (old is None or canonical_digest(asdict(old)) != row['old_template_sha256'] or
                canonical_digest(row['old_template']) != row['old_template_sha256'] or
                canonical_digest(row['new_template']) != row['new_template_sha256']):
            raise TargetValidationError('New resource reaction lost the exact original donor scope')

    def last_mana(c):
        if c.event is None or c.event.kind not in ('mana_spent', 'mana_consumed'):
            raise ResolutionError('Mana prefix requires its actual positive debit event')
        return (c.event.player_id == c.player_id and c.event.amount > 0 and
            c.state.players[c.player_id].mana == 0 and living_source(c))
    registry.register_trigger_condition(PREFIX+'last_mana', last_mana)
    registry.register_behavior(PREFIX+'grow', lambda c: (
        BuffCapturedMinion(MinionReference.capture(c.source), 1, 1, c.source_id),))
    for row in data['amendments']:
        old = registry.assemble_templates[row['card_id']]
        new = replace(old, suffix=replace(old.suffix,
            allowed_timings=tuple(row['new_template']['suffix']['allowed_timings'])))
        if canonical_digest(asdict(new)) != row['new_template_sha256']:
            raise TargetValidationError('Reaction compatibility amendment changed more than its declared scope')
        validate_template(registry, new)
        registry._assemble_templates[row['card_id']] = new
    for row in data['native_profiles']:
        limited = LimitedTriggerSpec(**row['limited']) if row['limited'] is not None else None
        registry.register_assemble_reaction_source(AssembleNativeReactionSource(row['card_id'],
            tuple(row['events']), row['original_behavior_id'], row['condition_id'], limited))
    for row in data['reviewed_templates']:
        profile = registry.assemble_reaction_sources[row['card_id']]
        registry.register_assemble_template(AssembleTemplate(row['card_id'],
            AssemblePrefix(row['timing'], condition_id=profile.condition_id),
            AssembleSuffix(row['body_id'], tuple(row['allowed_timings']))))
