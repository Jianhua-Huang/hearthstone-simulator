"""Printed native conditions stay in the prefix; only their effects are borrowed."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.damage_history import hero_damage_taken
from hs_sim.engine.effects import Buff, EquipWeapon, GrantKeyword
from hs_sim.engine.healing_history import restored_health
from hs_sim.engine.model import CardType, Keyword, SpellSchool
from hs_sim.engine.pools import DiscoverFromPool
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .conditional_pool_consumer_cards import GORILLA, POOL_ID, QUERIES
from .native_followup_cards import minions
from .simple_choice_p03_cards import SWORD

RECIPES = (
    ('CORE_BAR_313', 'healed_turn', 'buff_three'),
    ('CORE_LOE_039', 'other_mech', 'discover_mech'),
    ('CORE_RLK_814', 'held_shadow', 'buff_one'),
    ('EDR_457', 'held_dragon', 'equip_sword'),
    ('END_019', 'hero_damaged_turn', 'buff_three'),
    ('TIME_062', 'held_dragon', 'taunt_shield'),
    ('FIR_961', 'held_big_spell', 'shield_lifesteal'),
)
SOURCES = tuple(row[0] for row in RECIPES)
PREFIX = 'cards.assemble_conditional_native.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-conditional-native-followups-v1.json'
BATCH_HASH = '4a220faa4b256d3004c04926f6c0010cc4f203fd4636b55cb7863dd6cab50065'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (SWORD,) or
            tuple((row['card_id'], row['condition'], row['body'])
                for row in data['reviewed_templates']) != RECIPES or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Conditional native assembly requires seven full sources and the actual sword')
    return data


def register_assemble_conditional_native_followups(registry):
    data = load_batch()
    # Validate every original and fixed dependency before registering any part.
    for row in data['existing_dependencies']:
        if (canonical_digest(row['definition']) != row['definition_sha256'] or
                canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']):
            raise TargetValidationError('Conditional native assembly changed a complete original definition')
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        raw = row['record']
        if (raw['tags'].get('BATTLECRY') != 1 or raw['tags'].get('CRAFTABLE_OUTPUT_POWER') != 1 or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                registry.card(raw['id']).battlecry != declaration['original_battlecry_id']):
            raise TargetValidationError('Conditional native assembly lost its actual printed split or native entry')
        registry.behavior(declaration['original_battlecry_id'])
    for behavior_id in data['additional_required_native_behaviors']:
        registry.behavior(behavior_id)
    if (canonical_digest(data['mech_discovery_query']) != data['mech_discovery_query_sha256'] or
            canonical_digest(asdict(QUERIES[GORILLA])) != data['mech_discovery_query_sha256']):
        raise TargetValidationError('Conditional native assembly changed the full original mech discovery query')

    def held_dragon(c):
        return any(has_any_tribe(registry, c.state.entities[eid], ('dragon',))
                   for eid in c.state.players[c.player_id].hand)

    def held_shadow(c):
        return any(entity.kind == CardType.SPELL and
                   registry.card(entity.card_id).spell_school == SpellSchool.SHADOW
                   for eid in c.state.players[c.player_id].hand for entity in (c.state.entities[eid],))

    def held_big_spell(c):
        return any(entity.kind == CardType.SPELL and
                   quote_unselected_cost(c.state, registry, entity).amount >= 5
                   for eid in c.state.players[c.player_id].hand for entity in (c.state.entities[eid],))

    def other_mech(c):
        return any(eid != c.source_id and has_any_tribe(registry, c.state.entities[eid], ('mech',))
                   for eid in minions(c, registry, c.player_id))

    def taunt_shield(c):
        if not living_source(c):
            return ()
        original = MinionReference.capture(c.source)
        return tuple(GrantCapturedKeyword(original, key, c.source_id)
                     for key in (Keyword.TAUNT, Keyword.DIVINE_SHIELD))

    conditions = {
        'healed_turn': lambda c: restored_health(c.state, c.player_id, turn=c.state.turn) > 0,
        'hero_damaged_turn': lambda c: hero_damage_taken(c.state, c.player_id, turn=c.state.turn) > 0,
        'other_mech': other_mech,
        'held_shadow': held_shadow,
        'held_dragon': held_dragon,
        'held_big_spell': held_big_spell,
    }
    bodies = {
        'buff_three': lambda c: (Buff(c.source_id, 3, 3, c.source_id),),
        'buff_one': lambda c: (Buff(c.source_id, 1, 1, c.source_id),),
        'discover_mech': lambda c: (DiscoverFromPool(c.player_id, POOL_ID,
            QUERIES[GORILLA], source_id=c.source_id),),
        'equip_sword': lambda c: (EquipWeapon(c.player_id, SWORD),),
        'taunt_shield': taunt_shield,
        'shield_lifesteal': lambda c: tuple(GrantKeyword(c.source_id, key, c.source_id)
            for key in (Keyword.DIVINE_SHIELD, Keyword.LIFESTEAL)),
    }
    for key, predicate in conditions.items():
        registry.register_trigger_condition(PREFIX + key, predicate)
    for key in data['inner_call_conditions']:
        registry.register_assemble_inner_condition(PREFIX + key)
    for key, body in bodies.items():
        registry.register_behavior(PREFIX + key, body)
    for declaration in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix('battlecry', tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=PREFIX + declaration['condition']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings'])),
            original_battlecry_id=declaration['original_battlecry_id']))
