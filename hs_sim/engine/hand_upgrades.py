"""Stored-card stat changes and attachment-preserving upgrades in hand.

These are effects, not automatic Corrupt/Infuse triggers. Hidden changes have
owner-only events; Forge keeps its separate, public action-completion event.
"""
from dataclasses import dataclass, replace

from .effects import Effect
from .equipment import WEAPON_KEYWORDS
from .errors import ResolutionError
from .lifecycle import attachment_id, install_printed, refresh_entity
from .model import CardType, CostSpec, Enchantment, Keyword, Zone, _int, _name, _optional_id
from .zones import CardReference, reference_entity, reference_value, source_exists
from .discard_history import DiscardRecord, material_value, material_entity


@dataclass(frozen=True)
class BuffStoredCard(Effect):
    card: CardReference | DiscardRecord
    attack: int = 0
    health: int = 0
    source_id: int | None = None
    expires_turn: int | None = None
    cost: CostSpec | None = None

    def __post_init__(self):
        if type(self.card) is DiscardRecord:
            material_value(self.card)
            if self.cost is not None or self.expires_turn is not None:
                raise ValueError('Discard material only accepts its plain numeric growth')
            if self.source_id is not None and self.source_id != self.card.entity_id:
                raise ValueError('Discard numeric growth requires its own original source')
        else:
            reference_value(self.card)
        _int(self.attack, 'stored attack')
        _int(self.health, 'stored health', 0)
        _optional_id(self.source_id, 'stored buff source')
        _optional_id(self.expires_turn, 'stored buff expiry')
        if self.cost is not None:
            if type(self.cost) is not CostSpec:raise ValueError('Stored buff cost requires CostSpec')
            self.cost.__post_init__()


@dataclass(frozen=True)
class UpgradeHandCard(Effect):
    card: CardReference
    card_id: str
    source_id: int | None = None
    health_to_durability: bool = False

    def __post_init__(self):
        reference_value(self.card)
        if self.card.zone != Zone.HAND:
            raise ValueError('Upgrade requires a captured hand card')
        _name(self.card_id, 'upgrade card')
        _optional_id(self.source_id, 'upgrade source')
        if type(self.health_to_durability) is not bool:
            raise ValueError('Health conversion must be boolean')


def buff_stored_card(r, effect):
    from .costs import attach_cost,validate_cost_targets
    effect.__post_init__()
    source_exists(r, effect.source_id)
    definition=r.registry.card(effect.card.card_id)
    if definition.kind != CardType.MINION:
        raise ResolutionError('Stored stat buffs currently require a minion')
    if effect.expires_turn is not None and effect.expires_turn < r.state.turn:
        raise ResolutionError('Stored buff already expired')
    entity = material_entity(r, effect.card) if type(effect.card) is DiscardRecord else reference_entity(r, effect.card)
    if entity is None:
        return
    validate_cost_targets(r.state,effect,((definition,entity),))
    if entity.kind != CardType.MINION:
        raise ResolutionError('Stored stat buffs currently require a minion')
    if effect.attack == effect.health == 0 and effect.cost is None:
        return
    if effect.attack or effect.health:
        entity.enchantments.append(Enchantment(attachment_id(r.state), source_id=effect.source_id,
            attack=effect.attack, health=effect.health, expires_turn=effect.expires_turn, label='stored_buff'))
    cost=attach_cost(r.state,entity,effect.cost,effect.source_id,effect.expires_turn) if effect.cost is not None else None
    refresh_entity(entity)
    r.emit('stored_card_buffed', target_id=entity.id, source_id=effect.source_id,
           player_id=entity.controller, attack_delta=effect.attack, health_delta=effect.health)
    if cost is not None:
        r.emit('cost_modified',target_id=entity.id,source_id=effect.source_id,attachment_id=cost.id)


def upgrade_face(r, source, card_id, *, health_to_durability=False, cost_policy='preserve'):
    """Change only the printed face of a physical stored card, without playing."""
    if type(cost_policy) is not str or cost_policy not in ('preserve', 'clear_local'):
        raise ResolutionError('Unknown upgrade cost policy')
    from .game_boards import resolve_card_id
    card_id = resolve_card_id(r.state, r.registry, card_id)
    definition = r.registry.card(card_id)
    if source.zone not in (Zone.HAND, Zone.DECK) or source.components or not definition.hand_playable or definition.starship_for:
        raise ResolutionError('Upgrade requires a physical, non-composite stored form')
    changing_type = definition.kind != source.kind
    if health_to_durability:
        if (source.kind, definition.kind) != (CardType.MINION, CardType.WEAPON):
            raise ResolutionError('Health conversion requires a minion-to-weapon upgrade')
    elif changing_type:
        raise ResolutionError('Cross-type upgrade requires an explicit conversion policy')
    if source.card_id != card_id:
        if cost_policy == 'clear_local':
            kept = []
            for row in source.enchantments:
                if row.cost or row.set_cost is not None or row.cost_minimum or row.payment is not None:
                    if (row.attack or row.health or row.set_attack is not None or row.set_health is not None or
                            row.magnetic_id is not None or row.tribe_change is not None or row.cthun_ritual is not None):
                        row = replace(row, cost=0, set_cost=None, cost_minimum=0, payment=None)
                    else:
                        continue
                kept.append(row)
            source.enchantments = kept
        granted = [a for a in source.abilities if a.origin != 'printed']
        durability = definition.durability
        if health_to_durability:
            # Health becomes a one-time durability value, not weapon health.
            durability = source.health
            if durability < 1:
                raise ResolutionError('Cannot convert nonpositive health into durability')
            for ability in granted:
                allowed = (ability.kind in ('trigger', 'deathrattle', 'cost_aura') or
                    ability.kind == 'keyword' and ability.keyword in WEAPON_KEYWORDS or
                    ability.kind == 'limited_trigger' and ability.limited_trigger.keyword != Keyword.FRENZY)
                if not allowed:
                    raise ResolutionError('Granted ability has no weapon conversion policy')
            source.enchantments = [replace(e, health=0, set_health=None) for e in source.enchantments]
            source.damage = source.armor = 0
            source.frozen_until_owner_turn = None
            source.doomed = False
        source.herald_rank = None
        source.enchantments = [e for e in source.enchantments if e.label != 'herald']
        source.card_id, source.kind = card_id, definition.kind
        source.zone_epoch += 1
        source.base_attack, source.base_health, source.base_cost = definition.attack, definition.health, definition.cost
        source.durability = durability
        source.use_limit = definition.uses_per_turn
        source.corpse_value = int(definition.kind == CardType.MINION) if definition.corpse_value is None else definition.corpse_value
        source.silenced = False
        install_printed(r.state, source, definition)
        source.abilities.extend(granted)
        refresh_entity(source)
    if source.zone == Zone.HAND:
        r.game._information.hide_hand_identity(source.id)
    else:
        r.game._information.conceal(source.id)


def upgrade_hand_card(r, effect):
    source_exists(r, effect.source_id)
    # Reject unknown destinations even when the captured target has departed.
    r.registry.card(effect.card_id)
    source = reference_entity(r, effect.card)
    if source is None:
        return
    upgrade_face(r, source, effect.card_id, health_to_durability=effect.health_to_durability)
    r.emit('hand_card_upgraded', target_id=source.id, source_id=effect.source_id, player_id=source.controller)


def register_hand_upgrades(mechanics):
    mechanics.register(BuffStoredCard, buff_stored_card)
    mechanics.register(UpgradeHandCard, upgrade_hand_card)
