"""Closed self-health and native conditional continuous attack relations.

The source ID records provenance only. The relation never reads that source,
changes damage, replaces ordinary enchantments, or adjusts prepared combat.
"""
from dataclasses import dataclass, fields, is_dataclass
from collections import Counter

from .effects import Effect, _grant
from .model import (AbilityInstance, CardType, GameState, Keyword, StatReference, StatRelationOperand, StatRelationSpec, Zone)


def validate_ordinary_face(card):
    if (card.kind != CardType.MINION or card.starship_for or
            Keyword.STARSHIP_PIECE in card.keywords or Keyword.MAGNETIC in card.keywords):
        raise ValueError('Stat relations require ordinary non-fusion minion declarations')


def _validate_relation_face(card, specs):
    weapon = tuple(s for s in specs if s.operand in (
        StatRelationOperand.CONTROLLER_ARMOR,StatRelationOperand.CONTROLLER_OVERLOADED_MANA,
        StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE))
    if weapon:
        if card.kind != CardType.WEAPON or len(specs) != 1 or card.starship_for:
            raise ValueError('Continuous weapon Attack requires one native weapon relation')
    else:
        validate_ordinary_face(card)


def validate_definition(card):
    specs = card.stat_relations
    if type(specs) is not tuple or any(type(s) is not StatRelationSpec for s in specs):
        raise ValueError('Stat relation declarations require a typed immutable tuple')
    for spec in specs:
        spec.__post_init__()
    if len(set(specs)) != len(specs):
        raise ValueError('Duplicate printed stat relation declaration')
    if specs:
        _validate_relation_face(card, specs)


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'stat_relation')
    if not rows:
        return
    if kind not in (CardType.MINION, CardType.WEAPON) or components:
        raise ValueError('Stat relations require a non-composite minion or native weapon carrier')
    card = registry.card(card_id)
    validate_definition(card)
    _validate_relation_face(card, tuple(a.stat_relation for a in rows))
    if kind != card.kind:
        raise ValueError('Stat relation carrier differs from its native card type')
    installed = Counter()
    for ability in rows:
        ability.__post_init__()
        if ability.origin == 'printed' and (ability.stat_relation not in card.stat_relations or
                ability.source_id is None or ability.expires_turn is not None or ability.consumed):
            raise ValueError('Printed stat relation differs from its native declaration')
        if ability.stat_relation.operand in (StatRelationOperand.CONTROLLER_HAS_WEAPON,
                                            StatRelationOperand.CONTROLLER_HAS_MECH,
                                            StatRelationOperand.CONTROLLER_DISCARD_COUNT,
                                            StatRelationOperand.CONTROLLER_DECK_COUNT,
                                            StatRelationOperand.CONTROLLER_ARMOR,
                                            StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT,
                                            StatRelationOperand.CONTROLLER_OVERLOADED_MANA,
                                            StatRelationOperand.CONTROLLER_OPPONENT_TURN,
                                            StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE):
            installed[ability.stat_relation] += 1
            if installed[ability.stat_relation] > card.stat_relations.count(ability.stat_relation):
                profile = ('weapon-presence' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_HAS_WEAPON else
                           'mech-presence' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_HAS_MECH else
                           'deck-count' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_DECK_COUNT else
                           'controller-armor' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_ARMOR else
                           'other-battlefield-tribe' if ability.stat_relation.operand ==
                           StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT else
                           'overload-weapon' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_OVERLOADED_MANA else
                           'spell-damage-weapon' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE else
                           'opponent-turn' if ability.stat_relation.operand ==
                           StatRelationOperand.CONTROLLER_OPPONENT_TURN else 'discard-count')
                attribute = 'Health' if ability.stat_relation.target == StatReference.HEALTH else 'Attack'
                raise ValueError(f'Duplicate native {profile} {attribute} relation')


def conditional_attack(state, entity, registry=None):
    """Pure native own contribution from the current controller's facts."""
    from .lifecycle import active_abilities
    from .equipment import equipped_weapon
    specs = tuple(a.stat_relation for a in active_abilities(entity, 'stat_relation')
                  if a.stat_relation.target == StatReference.ATTACK)
    if any(s.operand == StatRelationOperand.CONTROLLER_ARMOR for s in specs):
        return state.entities[state.players[entity.controller].hero_id].armor
    overloaded = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_OVERLOADED_MANA)
    if overloaded:
        player = state.players[entity.controller]
        return sum(s.amount for s in overloaded) if player.overload_owed > 0 or player.overload_locked > 0 else 0
    spell_damage = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE)
    if spell_damage:
        if registry is None:
            raise ValueError('Spell Damage weapon Attack requires its registry')
        from .health_rules import spell_bonus
        return sum(s.amount for s in spell_damage) if spell_bonus(state, entity.controller, registry) > 0 else 0
    weapon = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_HAS_WEAPON)
    bonus = (sum(s.amount for s in weapon) if weapon and
             equipped_weapon(state, state.players[entity.controller]) is not None else 0)
    mech = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_HAS_MECH)
    if mech:
        if registry is None:
            raise ValueError('Mech-presence Attack requires its fixed registry')
        from .cross_zone import MinionScope, minion_references
        from .pools import PoolQuery
        present = minion_references(state, registry, entity.controller,
            MinionScope(zones=(Zone.BOARD,), query=PoolQuery(tribes_any=('mech',)), tribe_basis='current'))
        if present:
            bonus += sum(s.amount for s in mech)
    if entity.zone == Zone.BOARD and state.active_player != entity.controller:
        bonus += sum(s.amount for s in specs if s.operand == StatRelationOperand.CONTROLLER_OPPONENT_TURN)
    discarded = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_DISCARD_COUNT)
    if discarded:
        from .discard_history import discarded_cards
        bonus += len(discarded_cards(state, entity.controller)) * sum(s.amount for s in discarded)
    counted = tuple(s for s in specs if s.operand == StatRelationOperand.CONTROLLER_DECK_COUNT)
    if counted:
        from .deck_conditions import DeckCountCondition, matches_deck_condition
        for spec in counted:
            spec.__post_init__()
            if matches_deck_condition(state, None, entity.controller,
                    DeckCountCondition(spec.card_count, spec.comparison)):
                bonus += spec.amount
    tribal = tuple(s for s in specs if s.operand == StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT)
    if tribal:
        if registry is None:
            raise ValueError('Continuous battlefield tribe Attack requires its fixed registry')
        from .tribes import has_any_tribe
        for pid in (1, 2):
            for eid in state.players[pid].board:
                target = state.entities[eid]
                card = registry.card(target.card_id)
                if target.zone != Zone.BOARD or target.controller != pid or target.kind != card.kind:
                    raise ValueError('Continuous battlefield count differs from its physical board')
                if eid == entity.id or target.kind != CardType.MINION or card.interactable is not None:
                    continue
                for spec in tribal:
                    if has_any_tribe(registry, target, (spec.count_tribe,), basis='current'):
                        bonus += spec.amount
    return bonus


def refresh_turn_attacks(state, registry):
    """Refresh only genuine turn-dependent carriers before new start capture."""
    from .stat_auras import refresh_hero_auras
    refresh_hero_auras(state)
    for entity in state.entities.values():
        if any(a.kind == 'stat_relation' and a.stat_relation.operand == StatRelationOperand.CONTROLLER_OPPONENT_TURN
               for a in entity.abilities):
            entity.conditional_attack = conditional_attack(state, entity, registry)


def conditional_health(state, entity):
    """Finite native contribution; the existing committed ledger owns the count."""
    from .lifecycle import active_abilities
    specs = tuple(a.stat_relation for a in active_abilities(entity, 'stat_relation')
                  if a.stat_relation.target == StatReference.HEALTH)
    if not specs:
        return 0
    for spec in specs:
        spec.__post_init__()
    from .discard_history import discarded_cards
    return len(discarded_cards(state, entity.controller)) * sum(spec.amount for spec in specs)


def refresh_conditional_health(state, *, clamp=True):
    """Use the ordinary remaining-health clamp when this contribution shrinks."""
    for entity in state.entities.values():
        if not entity.conditional_health and not any(a.kind == 'stat_relation' and not a.consumed and
                a.stat_relation.target == StatReference.HEALTH for a in entity.abilities):
            continue
        old_health, old_bonus = entity.health, entity.conditional_health
        entity.conditional_health = conditional_health(state, entity)
        if clamp and entity.conditional_health < old_bonus:
            entity.damage = max(0, entity.max_health - old_health)


def refresh_conditional_attacks(state, registry=None):
    """Normalize only self numeric caches; never rematch external aura sources."""
    refresh_conditional_health(state)
    for entity in state.entities.values():
        entity.conditional_attack = conditional_attack(state, entity, registry)
    # Continuous inputs can change before an event freezes its context. Keep the original
    # active hero equipment view current without changing wear or attack uses.
    from .lifecycle import refresh_entity
    from .equipment import equipped_weapon
    player = state.players[state.active_player]
    weapon = equipped_weapon(state, player)
    if weapon is not None and any(a.stat_relation.operand in (
            StatRelationOperand.CONTROLLER_ARMOR,StatRelationOperand.CONTROLLER_OVERLOADED_MANA,
            StatRelationOperand.CONTROLLER_HAS_SPELL_DAMAGE)
            for a in weapon.abilities if a.kind == 'stat_relation' and not a.consumed):
        hero = state.entities[player.hero_id]
        hero.weapon_attack = weapon.attack
        refresh_entity(hero)


@dataclass(frozen=True)
class GrantStatRelation(Effect):
    target_id: int
    spec: StatRelationSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _grant(self.target_id, self.source_id, self.expires_turn)
        if type(self.spec) is not StatRelationSpec:
            raise ValueError('GrantStatRelation requires its closed typed specification')
        self.spec.__post_init__()
        if self.spec.operand != StatRelationOperand.SELF_CURRENT_HEALTH:
            raise ValueError('GrantStatRelation currently supports only the existing self-health relation')


def validate_grant(state, registry, effect):
    effect.__post_init__()
    target = state.entities.get(effect.target_id)
    if target is None:
        raise ValueError('Unknown continuous stat relation target')
    if effect.source_id is not None and effect.source_id not in state.entities:
        raise ValueError('Unknown continuous stat relation source')
    if target.kind != CardType.MINION or target.components:
        raise ValueError('Continuous stat relation grant requires a non-composite minion')
    # Known off-board, dormant, dead and expired queued work is not rematched.
    # The existing delivery/stale/expired policies determine its later outcome.
    card = registry.card(target.card_id)
    validate_definition(card)
    validate_ordinary_face(card)


def validate_frame_references(state, registry, value):
    """Bind new work in current queues, but use each captured original domain."""
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec

    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Stat relation frame references exceed codec depth')
        if type(item) is GrantStatRelation:
            validate_grant(scope, registry, item)
            return
        if type(item) is RuleContext:
            for field in fields(item):
                if field.name != 'state':
                    visit(getattr(item, field.name), item.state, depth + 1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            visit(item.work, item.state, depth + 1)
            return
        if type(item) is GameState:
            # All typed saved ability carriers are checked by model invariants.
            return
        if isinstance(item, (tuple, list)):
            for child in item:
                visit(child, scope, depth + 1)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child, scope, depth + 1)
        elif is_dataclass(item) and not isinstance(item, type):
            for field in fields(item):
                visit(getattr(item, field.name), scope, depth + 1)

    visit(value, state, 0)


def grant(r, effect):
    from .lifecycle import attachment_id
    from .resolver import board_minion, validate_attachment_source
    validate_grant(r.state, r.registry, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    entity = board_minion(r, effect)
    if entity is None:
        return ()
    ability = AbilityInstance(attachment_id(r.state), 'stat_relation',
        source_id=effect.source_id, stat_relation=effect.spec, expires_turn=effect.expires_turn)
    entity.abilities.append(ability)
    r.refresh_auras()
    r.emit('ability_granted', target_id=entity.id, source_id=effect.source_id,
           ability_id=ability.id, ability_kind=ability.kind)
    return ()


def register(mechanics):
    mechanics.register(GrantStatRelation, grant)
