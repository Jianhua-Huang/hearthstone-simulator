"""Actual other-minion-play subjects reuse ordinary captured event calls."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.effects import Draw
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardType, Keyword
from hs_sim.engine.play_history import play_record
from hs_sim.engine.sacrifice import BuffCapturedMinion, MinionReference
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source

SOURCES = ('BE_255', 'BE_701')
TAELAN = 'CS3_024'
PREFIX = 'cards.assemble_play_reaction.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-play-reaction-prefix-v1.json'
BATCH_HASH = 'd01172c147edc9b97c45b2c4a6fa4e28b3af43c68c86e32a0d074fa2ad59b49a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (TAELAN,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Play-reaction assembly requires both complete sources and reviewed Taelan context')
    return data


def register_assemble_play_reaction_prefix(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Play-reaction assembly changed a complete original source')
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != declaration['event'] or
                original.triggers[0].behavior_id != declaration['original_behavior_id']):
            raise TargetValidationError('Play-reaction assembly lost its complete native ordinary trigger')
        registry.behavior(declaration['original_behavior_id'])
    for amendment in data['amendments']:
        current = registry.assemble_templates.get(amendment['card_id'])
        if (current is None or canonical_hash(asdict(current)) != amendment['old_template_sha256'] or
                canonical_hash(amendment['old_template']) != amendment['old_template_sha256']):
            raise TargetValidationError('Play-reaction source changed the exact reviewed original draw declaration')
        registry.behavior(current.suffix.behavior_id)

    def other_minion_play(c):
        if c.event is None or c.event.kind != 'card_played':
            raise ResolutionError('Play reaction requires its actual original completed play event')
        try:
            row = play_record(c.state, dict(c.event.data)['play_id'])
        except KeyError as exc:
            raise ResolutionError('Play reaction lost its actual original physical play') from exc
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Play reaction changed its actual completed physical play')
        return (row.player_id == c.player_id and row.kind == CardType.MINION and
            row.source_id != c.source_id and living_source(c))

    def self_health(c):
        if not living_source(c):
            return ()
        return (BuffCapturedMinion(MinionReference.capture(c.source), health=1, source_id=c.source_id),)

    registry.register_trigger_condition(PREFIX + 'other_minion_play', other_minion_play)
    registry.register_behavior(PREFIX + 'self_health', self_health)
    registry.register_behavior(PREFIX + 'draw', lambda c: (Draw(c.player_id, source_id=c.source_id),))
    for declaration in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(declaration['card_id'],
            declaration['event'], declaration['original_behavior_id'], declaration['condition_id']))
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix(declaration['event'], tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=declaration['condition_id']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings']))))
    for amendment in data['amendments']:
        registry.extend_assemble_suffix_timings(amendment['card_id'], tuple(amendment['add_timings']),
            expected_template_sha256=amendment['old_template_sha256'])
