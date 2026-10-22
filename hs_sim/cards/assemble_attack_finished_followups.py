"""Eight actual attack subjects and independent source-attributed effect bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.assemble_reactions import (AssembleReactionSource, AssembleReactionContinuation,
    reaction_attack_reference)
from hs_sim.engine.board_presence import resolve_board_presence
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import AddToHand, Buff, Damage, DamageBatch, Draw, GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardType, DamageKind, Keyword
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .native_followup_cards import characters

SUPPLIER, FIEND, WRATH, REHGAR, HOOK, HOUND, RIDER, TUNNELER = SOURCES = (
    'CAP_003', 'CORE_BT_351', 'CORE_BT_510', 'CORE_CATA_004', 'CORE_NX2_028',
    'FIR_953', 'JAIL_872', 'TLC_840')
BOLT, WAR = 'CORE_EX1_238', 'BE_701'
PREFIX = 'cards.assemble_attack_finished.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-attack-finished-followups-v1.json'
BATCH_HASH = 'aea6c343648b619539a3f76089dcea0ddb202e030451a082355bd429b1f8ab40'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (BOLT, WAR) or
            tuple(row['card_id'] for row in data['reviewed_templates']) != SOURCES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Attack assembly requires eight complete native sources and two dependencies')
    return data


def register_assemble_attack_finished_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Attack assembly changed a complete original source')
    for declaration in data['reviewed_templates']:
        original = registry.card(declaration['card_id'])
        if (len(original.triggers) != 1 or original.triggers[0].event != declaration['event'] or
                original.triggers[0].behavior_id != declaration['original_behavior_id']):
            raise TargetValidationError('Attack assembly lost its real native ordinary trigger')
        registry.behavior(declaration['original_behavior_id'])
    for amendment in data['amendments']:
        current = registry.assemble_templates.get(amendment['card_id'])
        if (current is None or canonical_hash(asdict(current)) != amendment['old_template_sha256'] or
                canonical_hash(amendment['old_template']) != amendment['old_template_sha256']):
            raise TargetValidationError('Attack assembly changed its exact reviewed original draw template')
        registry.behavior(current.suffix.behavior_id)

    def attack(c):
        if c.event is None or c.event.kind != 'attack_finished':
            raise ResolutionError('Attack reaction requires its actual completed attack event')
        row = completed_attack(c)
        if row is None:
            raise ResolutionError('Attack reaction lost its actual completed physical attack')
        return row

    def self_attack(c):
        row = attack(c)
        return (row.declaration.source_id == c.source_id and living_source(c) and
            row.combat.player_id == c.player_id)

    def own_hero_attack(c):
        row = attack(c)
        return row.source_kind == CardType.HERO and row.declaration.player_id == c.player_id

    def own_attacker(c):
        row = attack(c)
        return row.declaration.source_id == c.source_id and living_source(c)

    def self_attacked(c):
        attack(c)
        return c.event.target_id == c.source_id

    def self_or_neighbor_attack(c):
        row = attack(c)
        if not living_source(c) or row.source_kind != CardType.MINION:
            return False
        board = c.state.players[c.player_id].board
        attacker = row.declaration.source_id
        return attacker in board and abs(board.index(attacker)-board.index(c.source_id)) <= 1

    def self_attacks_minion(c):
        row = attack(c)
        return (row.declaration.source_id == c.source_id and row.source_kind == CardType.MINION and
            row.delivery.attack_target_presence is not None)

    def original_attacker_survived(c):
        actor = resolve_board_presence(c.state, reaction_attack_reference(c))
        return (actor is not None and actor.controller == c.player_id and actor.active and
            actor.health > 0 and not actor.doomed)

    def split_attack(c):
        amount = c.death.attack if c.death is not None else c.source.attack
        return (RandomSplitDamage(c.player_id, None, c.source_id, amount,
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)

    for name, predicate in (('self_attack', self_attack), ('own_attacker', own_attacker), ('own_hero_attack', own_hero_attack),
            ('self_attacked', self_attacked), ('self_or_neighbor_attack', self_or_neighbor_attack),
            ('self_attacks_minion', self_attacks_minion), ('original_attacker_survived', original_attacker_survived)):
        registry.register_trigger_condition(PREFIX + name, predicate)
    bodies = {
        'draw': lambda c: (Draw(c.player_id, source_id=c.source_id),),
        'self_attack_gain': lambda c: (Buff(c.source_id, attack=1, source_id=c.source_id),),
        'all_enemies_damage': lambda c: (DamageBatch(tuple(Damage(eid, 1, c.source_id, DamageKind.MINION_ABILITY)
            for eid in characters(c, registry, 3-c.player_id))),),
        'lightning_bolt': lambda c: (AddToHand(c.player_id, BOLT, c.source_id),),
        'armor_draw': lambda c: (GainArmor(c.player_id, 4), Draw(c.player_id, source_id=c.source_id)),
        'split_attack': split_attack,
        'enemy_hero_damage': lambda c: (Damage(c.state.players[3-c.player_id].hero_id, 2,
            c.source_id, DamageKind.MINION_ABILITY),),
    }
    for name, body in bodies.items():
        registry.register_behavior(PREFIX + name, body)
    for declaration in data['reviewed_templates']:
        registry.register_assemble_reaction_source(AssembleReactionSource(declaration['card_id'],
            declaration['event'], declaration['original_behavior_id'], declaration['condition_id']))
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix(declaration['event'], tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=declaration['condition_id']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings']))))
    registry.register_assemble_reaction_continuation(AssembleReactionContinuation(**data['continuation']))
    for amendment in data['amendments']:
        registry.extend_assemble_suffix_timings(amendment['card_id'], tuple(amendment['add_timings']),
            expected_template_sha256=amendment['old_template_sha256'])
