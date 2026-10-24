"""Seven complete weapons lend their owner-hero attack prefix and pure body."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleProjection, AssembleSuffix
from hs_sim.engine.assemble_reactions import AssembleWeaponReactionSource
from hs_sim.engine.effects import AddToHand, Damage, DamageBatch
from hs_sim.engine.model import CardType, DamageKind
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .native_followup_cards import deathrattle_position

FLAMER, MACE, CLAWS, SCYTHE, CANNON, AXE, HAMMER = SOURCES = (
    'BE_552', 'EDR_253', 'TLC_833', 'JAIL_730', 'JAIL_450', 'TLC_478', 'BE_349')
LOOT, FLY, DRAIN = MATERIALS = ('CORE_EX1_096', 'CORE_UNG_809', 'CORE_GIL_622')
PREFIX = 'cards.assemble_hero_attack_weapon.'
CONDITION = 'cards.assemble_attack_finished.own_hero_attack'
TIMINGS = ('battlecry', 'deathrattle', 'end_turn', 'start_turn', 'attack_finished')
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/assemble-hero-attack-weapon-fragments-v1.json'
BATCH_HASH = 'c1632c905b0414bd800bf924fdac244dd86502cb3a906881e389d7991d2158bb'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    children = data['fixed_children']
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in rows) != SOURCES+MATERIALS+tuple(children.values()) or
            tuple(row['card_id'] for row in data['reviewed_projections']) != SOURCES or
            tuple(children) != ('overdrive', 'soul', 'grub', 'ghoul', 'elemental') or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256'] for row in rows)):
        raise TargetValidationError('Hero-attack weapon fragments require all complete original sources and children')
    return data


def register_assemble_hero_attack_weapon_fragments(registry):
    data = load_batch()
    rows = {row['record']['id']: row for row in data['existing_dependencies']}
    for cid, row in rows.items():
        if canonical_digest(asdict(registry.card(cid))) != row['definition_sha256']:
            raise TargetValidationError('Hero-attack projection changed a complete original dependency: '+cid)
    amendments = (data['draw_amendment'], *data['body_amendments'])
    if tuple(a['card_id'] for a in amendments) != MATERIALS:
        raise TargetValidationError('Hero-attack projection changed its actual original body contexts')
    for amendment in amendments:
        original_template = registry.assemble_templates.get(amendment['card_id'])
        if (original_template is None or
                canonical_hash(asdict(original_template)) != amendment['old_full_template_sha256'] or
                canonical_hash(amendment['old_full_template']) != amendment['old_full_template_sha256'] or
                tuple(amendment['add_timings']) != ('attack_finished',)):
            raise TargetValidationError('Hero-attack projection lost its complete original body template')
    current = registry.assemble_templates[LOOT]
    registry.trigger_condition(CONDITION)
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']
        original, raw = registry.card(cid), rows[cid]['record']
        if (original.kind != CardType.WEAPON or len(original.triggers) != 1 or
                original.triggers[0].event != 'attack_finished' or
                original.triggers[0].behavior_id != declaration['original_behavior_id'] or
                declaration['condition_id'] != CONDITION or declaration['event'] != 'attack_finished' or
                tuple(declaration['allowed_timings']) != TIMINGS or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1):
            raise TargetValidationError('Hero-attack weapon lost its complete original reaction: '+cid)
        registry.behavior(declaration['original_behavior_id'])
    # Reuse the original unguarded Draw and get-Soul programs. Guarded native
    # weapon callbacks remain on their originals, with their old slot policy.
    if data['reviewed_projections'][1]['body_id'] != current.suffix.behavior_id:
        raise TargetValidationError('Mace must borrow the exact reviewed Draw body')
    registry.behavior(data['reviewed_projections'][1]['body_id'])
    registry.behavior(data['reviewed_projections'][3]['body_id'])
    children = data['fixed_children']

    def summon(c, card_id, count):
        cause = SummonCause.capture(c)
        position = deathrattle_position(c) if c.deathrattle is not None else None
        request = SummonByCard(c.player_id, (SummonEntryMaterial(card_id),), cause, position=position)
        return (request,)*count

    def axe(c):
        targets = tuple(i for player in c.state.players.values() for i in player.board
            if c.state.entities[i].kind == CardType.MINION and c.state.entities[i].active
            and c.state.entities[i].health > 0 and not c.state.entities[i].doomed)
        return (DamageBatch(tuple(Damage(i, 1, c.source_id, DamageKind.MINION_ABILITY) for i in targets)),)

    registry.register_behavior(PREFIX+'overdrive', lambda c: (AddToHand(c.player_id, children['overdrive'], c.source_id),))
    for name, child, count in (('grub', 'grub', 1), ('ghoul', 'ghoul', 1), ('elementals', 'elemental', 2)):
        registry.register_behavior(PREFIX+name, lambda c, child=child, count=count: summon(c, children[child], count))
    registry.register_behavior(PREFIX+'axe', axe)
    for declaration in data['reviewed_projections']:
        cid = declaration['card_id']
        row = rows[cid]
        registry.register_assemble_reaction_source(AssembleWeaponReactionSource(cid,
            declaration['original_behavior_id'], CONDITION, row['definition_sha256']))
        registry.register_assemble_projection(AssembleProjection(cid, CardType.WEAPON,
            row['definition_sha256'], row['record_sha256'], AssemblePrefix('attack_finished', condition_id=CONDITION),
            AssembleSuffix(declaration['body_id'], TIMINGS)))
    for amendment in amendments:
        registry.extend_assemble_suffix_timings(amendment['card_id'], ('attack_finished',),
            expected_template_sha256=amendment['old_full_template_sha256'])
