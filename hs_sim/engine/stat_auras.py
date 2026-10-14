"""Existing minion stat declarations and printed damaged-source weapon auras.

The weapon profile uses the carrier's current controller and current damage.
Attachment source IDs are provenance; no permanent weapon modifier is created.
"""
from collections import Counter

from .lifecycle import active_abilities, refresh_entity
from .model import AuraSpec, CardType, Zone


def validate_definition(card):
    # Preserve the original unconditional minion declaration guards.
    from .registry import _number
    if not isinstance(card.auras, tuple):
        raise ValueError(f'card {card.id} auras must be a tuple')
    for aura in card.auras:
        if not isinstance(aura, AuraSpec):
            raise ValueError(f'card {card.id} auras must contain AuraSpec values')
        _number(aura.attack, 'aura attack')
        _number(aura.health, 'aura health', 0)
        if type(aura.include_self) is not bool:
            raise ValueError('aura include_self must be boolean')
        if type(aura.adjacent_only) is not bool or aura.adjacent_only and aura.include_self:
            raise ValueError('Adjacent aura requires a boolean and excludes its source')
        aura.__post_init__()
    if card.kind != CardType.MINION and card.auras:
        raise ValueError('Only minions support aura definitions')
    conditional = tuple(s for s in card.auras if s.condition == 'self_damaged' or s.tribes_any or s.card_ids)
    if conditional:
        from .stat_relations import validate_ordinary_face
        validate_ordinary_face(card)
        if len(set(conditional)) != len(conditional):
            raise ValueError('Duplicate printed conditional weapon aura')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'aura')
    if not rows:
        return
    card = registry.card(card_id)
    native_conditional = any(s.condition == 'self_damaged' or s.tribes_any or s.card_ids for s in card.auras)
    conditional = tuple(a for a in rows if a.aura_condition == 'self_damaged' or a.aura_tribes_any or a.aura_card_ids)
    if not conditional and not native_conditional:
        return
    if kind != CardType.MINION or components:
        raise ValueError('Conditional weapon auras require non-composite minion carriers')
    validate_definition(card)
    from .stat_relations import validate_ordinary_face
    validate_ordinary_face(card)
    declared = Counter(card.auras)
    installed = Counter()
    for ability in rows:
        ability.__post_init__()
        if ability.origin == 'printed':
            spec = ability.aura_spec
            if spec not in declared:
                raise ValueError('Conditional weapon aura differs from its native declaration')
            installed[spec] += 1
            if installed[spec] > declared[spec]:
                raise ValueError('Duplicate native conditional weapon aura instance')


def matches_card_identity(entity, card_ids):
    """The existing player aura's current physical card-ID predicate."""
    return not card_ids or entity.card_id in card_ids


def weapon_bonuses(state, *, include_dying=False):
    """Pure contributions from physical active board carriers to current slots."""
    bonuses = {}
    for player in state.players.values():
        if player.weapon_id is None:
            continue
        weapon = state.entities[player.weapon_id]
        if weapon.kind != CardType.WEAPON or weapon.zone != Zone.WEAPON:
            continue
        amount = 0
        for source_id in player.board:
            source = state.entities[source_id]
            if (source.kind != CardType.MINION or not source.active or source.damage <= 0 or
                    not include_dying and (source.health <= 0 or source.doomed)):
                continue
            amount += sum(a.attack for a in active_abilities(source, 'aura')
                          if a.aura_target == 'friendly_weapon')
        bonuses[weapon.id] = amount
    return bonuses


def refresh_weapon_auras(state, *, include_dying=False):
    """Normalize weapon contributions without selecting old minion aura sources.

Used after settled health clamps and before event contexts freeze. Clearing old
weapon caches also removes a contribution after unequipping or source removal.
Only a changed weapon contribution updates the active hero; original keyword,
wear, attack-use and prepared-combat policies remain with equipment/combat.
"""
    bonuses = weapon_bonuses(state, include_dying=include_dying)
    changed = False
    for entity in state.entities.values():
        if entity.kind == CardType.WEAPON:
            amount = bonuses.get(entity.id, 0)
            if entity.aura_attack != amount:
                entity.aura_attack = amount
                refresh_entity(entity)
                changed = True
    if changed:
        player = state.players[state.active_player]
        hero = state.entities[player.hero_id]
        weapon = state.entities.get(player.weapon_id)
        hero.weapon_attack = weapon.attack if weapon is not None and weapon.durability > 0 and not weapon.doomed else 0
        refresh_entity(hero)
