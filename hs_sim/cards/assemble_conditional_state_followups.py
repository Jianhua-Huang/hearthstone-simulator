"""Four native state conditions stay with the prefix, independent of their reward."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.assemble_faces import AssemblePrefix, AssembleSuffix, AssembleTemplate
from hs_sim.engine.board_presence import capture_board_presence
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.dark_gifts import DARK_GIFT_VERSION, public_gifts
from hs_sim.engine.effects import Buff, ChoiceOption, Damage, DamageBatch, GainArmor, RequestChoice
from hs_sim.engine.model import CardType, DamageKind, Keyword
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .attack_followup_cards import living_source
from .native_followup_cards import minions
from .native_forced_attack_cards import PREFIX as NATIVE_ATTACK_PREFIX

RECIPES = (('FIR_901', 'held_gift', 'broodlings'), ('FIR_956', 'held_gift', 'hero_reward'),
    ('TIME_019', 'owned_aura', 'enemy_batch'), ('EDR_014', 'accepted_cost', 'random_attacks'))
SOURCES = tuple(row[0] for row in RECIPES)
BROODLING = 'FIR_901t'
PREFIX = 'cards.assemble_conditional_state.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/assemble-conditional-state-followups-v1.json'
BATCH_HASH = '6f410d7837aef626f31703a3430ed32c5a4cb4bfef06d6376cc8e7264a36ab09'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != SOURCES + (BROODLING,) or
            tuple((row['card_id'], row['condition'], row['body']) for row in data['reviewed_templates']) != RECIPES or
            data['dark_gift_version'] != DARK_GIFT_VERSION or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            any(canonical_digest(row['record']) != row['record_sha256'] or
                canonical_digest(row['definition']) != row['definition_sha256']
                for row in data['existing_dependencies'])):
        raise TargetValidationError('Conditional state assembly requires four complete native sources and broodling')
    return data


def register_assemble_conditional_state_followups(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Conditional state assembly changed a complete original definition')
    for row, declaration in zip(data['existing_dependencies'], data['reviewed_templates']):
        raw = row['record']
        if (raw['tags'].get('BATTLECRY') != 1 or raw['tags'].get('CRAFTABLE_OUTPUT_POWER') != 1 or
                raw['text'].count('&') != 1 or raw['text_en'].count('&') != 1 or
                registry.card(raw['id']).battlecry != declaration['original_battlecry_id']):
            raise TargetValidationError('Conditional state assembly lost its original printed split or entry')
        registry.behavior(declaration['original_battlecry_id'])
    for behavior_id in data['additional_required_native_behaviors']:
        registry.behavior(behavior_id)

    def held_gift(c):
        return any(c.state.entities[eid].kind == CardType.MINION and public_gifts(c.state.entities[eid])
            for eid in c.state.players[c.player_id].hand)

    def owned_aura(c):
        return any(registry.player_effect(effect.spec_id).kind == 'aura'
            for effect in c.state.players[c.player_id].player_effects)

    def accepted_cost(c):
        cost = c.play.cost if c.play is not None else quote_unselected_cost(c.state, registry, c.source).amount
        return cost <= 3

    def broodlings(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(BROODLING),), SummonCause.capture(c))
        return request, request

    def hero_reward(c):
        return (Buff(c.state.players[c.player_id].hero_id, attack=3, source_id=c.source_id,
            expires_turn=c.state.turn), GainArmor(c.player_id, 6))

    def enemy_batch(c):
        other = 3-c.player_id
        targets = (c.state.players[other].hero_id, *minions(c, registry, other))
        return (DamageBatch(tuple(Damage(eid, 3, c.source_id, DamageKind.MINION_ABILITY)
            for eid in targets)),)

    def random_attacks(c):
        if not living_source(c):
            return ()
        source = asdict(capture_board_presence(c.state, c.source_id))
        options = tuple(ChoiceOption(json.dumps(dict(source=source,
            target=asdict(capture_board_presence(c.state, eid))), sort_keys=True), 'Original enemy minion')
            for eid in minions(c, registry, 3-c.source.controller))
        return (RequestChoice(c.player_id, options, c.source_id, min_count=0, max_count=0,
            sample_size=min(2, len(options)), on_select=NATIVE_ATTACK_PREFIX + 'selected'),) if options else ()

    for key, predicate in (('held_gift', held_gift), ('owned_aura', owned_aura), ('accepted_cost', accepted_cost)):
        registry.register_trigger_condition(PREFIX + key, predicate)
    for key, body in (('broodlings', broodlings), ('hero_reward', hero_reward),
            ('enemy_batch', enemy_batch), ('random_attacks', random_attacks)):
        registry.register_behavior(PREFIX + key, body)
    for declaration in data['reviewed_templates']:
        registry.register_assemble_template(AssembleTemplate(declaration['card_id'],
            AssemblePrefix('battlecry', tuple(Keyword(key) for key in declaration['keywords']),
                condition_id=PREFIX + declaration['condition']),
            AssembleSuffix(PREFIX + declaration['body'], tuple(declaration['allowed_timings'])),
            original_battlecry_id=declaration['original_battlecry_id']))
