"""Elise's finite native ingredients; execution uses ordinary shared effects."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.composed_locations import (BeginLocationUse, CraftLocation,
    LocationComponent, LocationRecipeProfile, component_context)
from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckCostDiversityCondition
from hs_sim.engine.effects import Buff, CopyMinion, Damage, DamageBatch, GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    CostSpec, PlayerEffectSpec, SummonStats, TargetSpec, Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.ordered_group_batches import SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember, OrderedSummonGroupSpec
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

CARD = 'TLC_100'
RAPTOR = 'TLC_101t'
TEMPLATES = tuple(f'TLC_100t{i}' for i in (1, 2, 3))
PARTS = {tier: tuple(f'TLC_100t{tier}{i}' for i in range(1, 7 if tier == 1 else 8))
    for tier in (1, 2, 3)}
PREFIX = 'cards.elise_location.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/elise-crafted-locations-v1.json'
BATCH_HASH = 'eddb7bad2bce4439d799e51dd3dab3788028d38a41437923ecca43b638cb8332'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = tuple(row for group in ('cards', 'dependencies', 'existing_dependencies', 'choice_only', 'evidence_only')
        for row in data[group])
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            tuple(row['record']['id'] for row in data['dependencies']) != TEMPLATES or
            tuple(row['record']['id'] for row in data['existing_dependencies']) != (RAPTOR,) or
            tuple(row['record']['id'] for row in data['choice_only']) != sum(PARTS.values(), ()) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Elise requires the complete reviewed source and actual eligible ingredients')
    return data


def register_elise_location_cards(registry):
    data = load_batch()
    if canonical_digest(asdict(registry.card(RAPTOR))) != data['existing_dependency_definition_pins'][RAPTOR]:
        raise TargetValidationError('Elise changed her original already implemented Raptor dependency')

    def uninitialized(c):
        raise ResolutionError('An uninitialized Elise location has no selected ingredients')

    def craft(c):
        return (CheckDeckCondition(c.player_id, DeckCostDiversityCondition(10, 'printed'),
            (CraftLocation(c.player_id, c.source_id, CARD),)),)

    def use(c):
        return (BeginLocationUse(SummonCause.capture(c), None if c.target_id is None else
            BoardPresenceReference.capture(c.state, c.target_id)),)

    registry.register_behavior(PREFIX + 'uninitialized', uninitialized)
    registry.register_behavior(PREFIX + 'craft', craft)
    registry.register_behavior(PREFIX + 'use', use)

    def body(tier, suffix):
        amount = {1: (1, 1, 1, 1, 1, 3, 1), 2: (3, 2, 4, 2, 2, 6, 3),
            3: (5, 4, 7, 4, 4, 12, 5)}[tier][suffix - 1]
        template = TEMPLATES[tier - 1]
        if suffix == 1:
            # The Deathrattle follows the original death/trigger context, not an active-use cursor.
            return lambda c: (DamageBatch(tuple(Damage(eid, amount, c.source_id)
                for eid in characters(c, registry, 3 - c.player_id))),)

        def resolve(c):
            cause, target = component_context(c, registry)
            if suffix == 2:
                return (AddPlayerEffect(c.player_id, PREFIX + template + '.moonlight', c.source_id),)
            if suffix == 3:
                return (DiscoverFromPool(c.player_id, 'constructed.cards',
                    PoolQuery(kinds=(CardType.SPELL,), collectible=True, class_mode='current'),
                    source_id=c.source_id, cost=CostSpec(delta=-amount)),)
            if suffix == 4:
                return tuple(Buff(eid, attack=amount, source_id=c.source_id, expires_turn=c.state.turn)
                    for eid in characters(c, registry, c.player_id))
            if suffix == 5:
                members = tuple(OrderedGroupMember(f'{template}.raptor.{i}', SummonEntryMaterial(RAPTOR))
                    for i in range(amount))
                return (SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id, cause, members)),)
            if suffix == 6:
                return (GainArmor(c.player_id, amount),)
            if suffix == 7:
                return () if target is None else (CopyMinion(target, c.player_id, cause=cause,
                    stats=SummonStats(attack=amount, health=amount)),)
            raise ResolutionError('Unknown reviewed Elise ingredient')
        return resolve

    for tier, parts in PARTS.items():
        for cid in parts:
            registry.register_behavior(PREFIX + cid, body(tier, int(cid[-1])))

    for row in (*data['cards'], *data['dependencies'], *data['choice_only']):
        raw = row['record']; cid = raw['id']; kind = CardType(raw['type'].lower())
        fields = {}
        if cid == CARD:
            fields.update(attack=raw['attack'], health=raw['health'], battlecry=PREFIX + 'craft')
        elif cid in TEMPLATES:
            fields.update(durability=raw['health'], manual_playable=False, on_use=PREFIX + 'uninitialized')
        else:
            fields.update(choice_only=True)
        card = CardDefinition(cid, raw['name'], kind,
            cost=raw['cost'] if raw['cost'] is not None else row['numeric_normalizations']['cost'],
            metadata=metadata_from_record(raw), **fields)
        registry.register_card(card)
        if cid == CARD:
            pool = PoolCard.from_definition(card)
            if cid in registry.pool_cards:
                if registry.pool_cards[cid] != pool:
                    raise TargetValidationError('Elise changed her original pool declaration')
            else:
                registry.register_pool_card(pool)

    for tier, parts in PARTS.items():
        template = TEMPLATES[tier - 1]
        registry.register_player_effect(PlayerEffectSpec(PREFIX + template + '.moonlight', template,
            kind='next_spell_damage_until_cast', spell_damage=(1, 2, 4)[tier - 1]))
        components = tuple(LocationComponent(cid, PREFIX + cid,
            timing='deathrattle' if cid.endswith('1') else 'use',
            targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='friendly')
                if cid.endswith('7') else None,
            requires_board_space=cid.endswith(('5', '7')),
            after=tuple(x for x in parts if x.endswith(('5', '7'))) if cid.endswith('4') else ()) for cid in parts)
        registry.register_location_recipe_profile(LocationRecipeProfile(CARD, template, components, PREFIX + 'use'))
