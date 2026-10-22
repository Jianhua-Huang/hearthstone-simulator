"""Four native spell reactions retain their original direct or late body windows."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardType, Keyword, SpellSchool
from hs_sim.engine.play_history import play_record
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source

VETERAN, PYRO, COLD, THRESHER = SOURCES = ('CORE_BAR_878', 'CORE_NEW1_020', 'CORE_RLK_083', 'TLC_256')
MEDIC = 'BAR_878t'
PREFIX = 'cards.assemble_spell_play.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-spell-play-followups-v1.json'
BATCH_HASH = 'a775cc8463a140a61918d2b95a528c5148518d62a1a8f1efa7fe4aee6d51e279'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (MEDIC,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Spell-play assembly requires four complete sources and the original Medic')
    return data


def register_assemble_spell_play_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Spell-play assembly changed a complete original source or Medic')
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != declaration['event'] or
                original.triggers[0].behavior_id != declaration['original_behavior_id']):
            raise TargetValidationError('Spell-play assembly lost its original ordinary trigger')
        registry.behavior(declaration['original_behavior_id'])
    for behavior in data['original_inner_bodies'].values():
        registry.behavior(behavior)

    def spell_play(c):
        if c.event is None or c.event.kind != 'card_played':
            raise ResolutionError('Spell-play reaction requires its actual completed event')
        try:
            row = play_record(c.state, dict(c.event.data)['play_id'])
        except KeyError as exc:
            raise ResolutionError('Spell-play reaction lost its original physical play') from exc
        if not row.completed or (row.source_id, row.player_id) != (c.event.source_id, c.event.player_id):
            raise ResolutionError('Spell-play reaction changed its completed original physical play')
        return row.player_id == c.player_id and row.kind == CardType.SPELL and not row.countered

    def holy_spell_play(c):
        if not spell_play(c):
            return False
        row = play_record(c.state, dict(c.event.data)['play_id'])
        return registry.card(row.card_id).spell_school == SpellSchool.HOLY

    def living_spell_play(c):
        return spell_play(c) and living_source(c)

    def self_shield(c):
        if not living_source(c):
            return ()
        return (GrantCapturedKeyword(MinionReference.capture(c.source), Keyword.DIVINE_SHIELD, c.source_id),)

    registry.register_trigger_condition(PREFIX + 'spell_play', spell_play)
    registry.register_trigger_condition(PREFIX + 'holy_spell_play', holy_spell_play)
    registry.register_trigger_condition(PREFIX + 'living_spell_play', living_spell_play)
    registry.register_behavior(PREFIX + 'summon_medic', lambda c: (
        SummonByCard(c.player_id, (SummonEntryMaterial(MEDIC),), SummonCause.capture(c)),))
    registry.register_behavior(PREFIX + 'self_shield', self_shield)
    # These two real native bodies already introduce a later InvokeBehavior view.
    # Retain that instruction when borrowing the body into another timing.
    for cid, name in ((PYRO, 'all_minions_damage'), (COLD, 'two_enemies_damage')):
        inner = data['original_inner_bodies'][cid]
        registry.register_behavior(PREFIX + name,
            lambda c, inner=inner: (InvokeBehavior(inner, c.source_id, c.player_id),))
    for declaration in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(declaration['card_id'],
            declaration['event'], declaration['original_behavior_id'], declaration['condition_id']))
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix(declaration['event'], tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=declaration['condition_id']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings']))))
