"""Actual Neutral/Combo play guards and independent public-effect bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.effects import AddCostModifier, RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardType, CostSpec, DamageKind, Keyword
from hs_sim.engine.play_history import play_record
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .native_followup_cards import characters

GENERAL, PATROL = SOURCES = ('BE_008', 'BE_723')
PREFIX = 'cards.assemble_card_play.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-card-play-followups-v1.json'
BATCH_HASH = '32e2fe193493fe3352e915847350acf9ff7c08f67388db85c43cea6afb99dd98'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Card-play assembly requires both complete reviewed original sources')
    return data


def register_assemble_card_play_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Card-play assembly changed a complete original source')
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != declaration['event'] or
                original.triggers[0].behavior_id != declaration['original_behavior_id']):
            raise TargetValidationError('Card-play assembly lost its actual native ordinary trigger')
        registry.behavior(declaration['original_behavior_id'])

    def completed_play(c):
        if c.event is None or c.event.kind != 'card_played':
            raise ResolutionError('Card-play reaction requires its actual completed event')
        try:
            row = play_record(c.state, dict(c.event.data)['play_id'])
        except KeyError as exc:
            raise ResolutionError('Card-play reaction lost its original physical play') from exc
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Card-play reaction changed its actual completed physical play')
        return row

    def neutral_card_play(c):
        row = completed_play(c)
        if row.player_id != c.player_id or not living_source(c):
            return False
        classes = row.played_face.metadata.classes if row.played_face.metadata is not None else None
        if classes is None:
            raise ResolutionError('Neutral play requires known original printed classes')
        return classes == (CardClass.NEUTRAL,)

    def combo_card_play(c):
        row = completed_play(c)
        if row.player_id != c.player_id or not living_source(c):
            return False
        face = registry.card(row.card_id)
        return face.combo is not None or Keyword.COMBO in face.keywords

    registry.register_trigger_condition(PREFIX + 'neutral_card_play', neutral_card_play)
    registry.register_trigger_condition(PREFIX + 'combo_card_play', combo_card_play)
    registry.register_behavior(PREFIX + 'next_spell_discount', lambda c: (
        AddCostModifier(c.player_id, CostSpec(delta=-1, card_types=(CardType.SPELL,)),
            uses_remaining=1, source_id=c.source_id, expires_turn=c.state.turn),))
    registry.register_behavior(PREFIX + 'random_enemy_damage', lambda c: (
        RandomDamage(characters(c, registry, 3-c.player_id), 3, c.source_id, DamageKind.MINION_ABILITY),))
    for declaration in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(declaration['card_id'],
            declaration['event'], declaration['original_behavior_id'], declaration['condition_id']))
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix(declaration['event'], tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=declaration['condition_id']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings']))))
