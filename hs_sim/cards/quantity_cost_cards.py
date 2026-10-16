"""Reviewed full consumers of retained damage and physical zone quantities."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Draw
from hs_sim.engine.model import (BoardMinionCostSpec, CardDefinition, CardType, HandCountCostSpec,
    HeroDamageTakenCostSpec, IntrinsicCostSpec, Keyword, PlayerCharacterAttackCostSpec, PlayerSpellDamageCostSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/quantity-cost-effects-v1.json'
BATCH_HASH = 'be298d79fd0f79727474652154da613f8d62dc0d970847dcbf068639a3d24402'
PREFIX = 'cards.quantity_costs.'
SCRIPTS = {
    'dragon': lambda c: (SummonByCard(c.player_id, (SummonEntryMaterial('CATA_452t'),), SummonCause.capture(c)),),
    'draw_two': lambda c: (Draw(c.player_id, 2, source_id=c.source_id),),
    'draw_three': lambda c: (Draw(c.player_id, 3, source_id=c.source_id),),
}
PROFILES = {
    'enemy_hero_damage_count': dict(hero_damage_taken_cost=HeroDamageTakenCostSpec('cost.enemy-hero-current-turn-damage-count-v1')),
    'board_no_minions': dict(intrinsic_costs=(IntrinsicCostSpec(set_to=2, condition='board_no_minions',
                               history_profile_id='board.current-no-minions-v1'),)),
    'spell_damage': dict(player_spell_damage_cost=PlayerSpellDamageCostSpec()),
    'character_attacks': dict(player_character_attack_cost=PlayerCharacterAttackCostSpec()),
    'enemy_board': dict(board_minion_cost=BoardMinionCostSpec('enemy')),
    'own_all_hand': dict(hand_count_cost=HandCountCostSpec('friendly')),
    None: {},
}


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Quantity cost content differs from its reviewed source pin')
    return data


def register_quantity_cost_cards(registry):
    for name, fn in SCRIPTS.items(): registry.register_behavior(PREFIX + name, fn)
    for row in load_batch()['cards']:
        raw, recipe = row['record'], row['recipe']
        if canonical_digest(raw) != row['record_sha256']:
            raise TargetValidationError('Quantity cost record changed')
        if recipe['cost'] != raw['cost'] or type(raw['cost']) is not int:
            raise TargetValidationError('Quantity cost requires an explicit reviewed printed price')
        kind = CardType(raw['type'].lower())
        if recipe['profile'] not in PROFILES:
            raise TargetValidationError('Unreviewed quantity cost profile')
        kwargs = dict(PROFILES[recipe['profile']])
        if recipe.get('body') is not None:
            if recipe['body'] not in SCRIPTS or kind != CardType.SPELL:
                raise TargetValidationError('Unreviewed quantity cost body')
            kwargs['on_play'] = PREFIX + recipe['body']
        definition = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] if kind == CardType.MINION else 0,
            keywords=tuple(Keyword(k) for k in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw), deck_identity=recipe['deck_identity']), **kwargs)
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
