"""Three actual pre-combat subjects retain original declaration and body views."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import AssembleReactionSource, REACTION_TIMINGS
from hs_sim.engine.effects import RefreshMana
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import Keyword, Zone
from hs_sim.engine.pools import GenerateFromPool
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest
from .simple_followup_p46_cards import POOL_ID, QUERY
from .zone_cards import stored_buffs

BROODMOTHER, SHAKU, RUNTHAK = SOURCES = ('CATA_469', 'CORE_CFM_781', 'CS3_025')
WAR = 'BE_701'
PREFIX = 'cards.assemble_attack_declared.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-attack-declared-followups-v1.json'
BATCH_HASH = 'a1967b5fd1cdd89ebeb85639dcb72d662e9973078bd4ca38561d5a77393e56df'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (WAR,) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            not set(data['ordinary_event_grammar']) <= REACTION_TIMINGS or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Declaration assembly requires three complete sources and reviewed plain draw')
    return data


def register_assemble_attack_declared_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Declaration assembly changed a complete original source')
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != declaration['event'] or
                original.triggers[0].behavior_id != declaration['original_behavior_id']):
            raise TargetValidationError('Declaration assembly lost its actual ordinary source trigger')
        registry.behavior(declaration['original_behavior_id'])
    reviewed = data['other_class_generation']
    if reviewed['pool_id'] != POOL_ID or canonical_digest(reviewed['query']) != canonical_digest(asdict(QUERY)):
        raise TargetValidationError('Declaration assembly changed the original complete other-class query')
    for amendment in data['amendments']:
        current = registry.assemble_templates.get(amendment['card_id'])
        if (current is None or canonical_hash(asdict(current)) != amendment['old_template_sha256'] or
                canonical_hash(amendment['old_template']) != amendment['old_template_sha256']):
            raise TargetValidationError('Declaration assembly changed its exact reviewed plain draw template')
        registry.behavior(current.suffix.behavior_id)

    def original_declaration(c):
        if c.event is None or c.event.kind != 'attack_declared':
            raise ResolutionError('Attack declaration reaction requires its actual original event')
        try:
            window = dict(c.event.data)['window_id']
        except KeyError as exc:
            raise ResolutionError('Attack declaration reaction lost its physical window') from exc
        rows = [row for row in c.state.character_attack_history if row.declaration.id == window]
        if type(window) is not int or len(rows) != 1:
            raise ResolutionError('Attack declaration reaction lost its unique physical window')
        row = rows[0]; w = row.declaration
        if (w.source_id, w.target_id, w.player_id, row.declaration_event_cursor+1) != (
                c.event.source_id, c.event.target_id, c.event.player_id, c.event.sequence):
            raise ResolutionError('Attack declaration reaction borrowed another original declaration')
        return row

    def own_declared_attack(c):
        row = original_declaration(c)
        return row.declaration.source_id == c.source_id

    def personal_declared_attack(c):
        return own_declared_attack(c) and c.event.player_id == c.player_id

    def refresh_attack_mana(c):
        amount = c.death.attack if c.death is not None and c.death.entity_id == c.source_id else c.source.attack
        return (RefreshMana(c.player_id, max(0, amount)),)

    registry.register_trigger_condition(PREFIX + 'own_declared_attack', own_declared_attack)
    registry.register_trigger_condition(PREFIX + 'personal_declared_attack', personal_declared_attack)
    registry.register_behavior(PREFIX + 'refresh_attack_mana', refresh_attack_mana)
    registry.register_behavior(PREFIX + 'other_class_card', lambda c: (
        GenerateFromPool(c.player_id, POOL_ID, QUERY, source_id=c.source_id),))
    registry.register_behavior(PREFIX + 'hand_minion_stats', lambda c: stored_buffs(c, (Zone.HAND,), 1))
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
