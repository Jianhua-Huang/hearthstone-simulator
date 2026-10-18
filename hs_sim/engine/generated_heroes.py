"""Trusted generated hero-card installation primitive, pending native tests.

This deliberately stops at installation. It does not execute a card body,
accept a replay root, forge a paid PlayRecord, or advance a public turn clock.
The inheritance policy is the existing local manual hero-card contract R-038;
it is not new evidence about the target CN server's rules.
"""
from dataclasses import dataclass

from .effects import Effect, ReplaceHeroPower, _behavior, _integer, _player
from .errors import ResolutionError
from .hero_powers import (
    assign_hero_class, installation_definition, replace_hero_additional_powers,
    replace_hero_power)
from .lifecycle import copy_attachments, refresh_entity
from .model import CardType, Zone
from .zones import source_exists


@dataclass(frozen=True)
class InstallGeneratedHeroCard(Effect):
    """Install a fresh printed playable hero, without hand entry or payment.

    player_id is the explicit beneficiary; source_id is an existing physical
    issuer, which may belong to either player and need not remain in play.
    Dynamic effects of an old submitted hand card are not copied from history.
    """
    player_id: int
    card_id: str
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        _integer(self.source_id, 'generated hero issuer', 1)


@dataclass(frozen=True)
class GeneratedHeroInstallation:
    """Host result for a future trusted child installer, not history proof."""
    player_id: int
    card_id: str
    source_id: int
    old_hero_id: int
    hero_id: int
    old_power_id: int | None
    power_id: int
    removed_additional_power_ids: tuple[int, ...]

    def __post_init__(self):
        _player(self.player_id)
        _behavior(self.card_id)
        for name in ('source_id', 'old_hero_id', 'hero_id', 'power_id'):
            _integer(getattr(self, name), name, 1)
        if self.old_power_id is not None:
            _integer(self.old_power_id, 'old power', 1)
        if type(self.removed_additional_power_ids) is not tuple:
            raise ValueError('Removed power IDs must be an immutable tuple')
        for value in self.removed_additional_power_ids:
            _integer(value, 'removed additional power', 1)
        physical = (self.old_hero_id, self.hero_id, self.power_id,
                    *(() if self.old_power_id is None else (self.old_power_id,)),
                    *self.removed_additional_power_ids)
        if len(set(physical)) != len(physical):
            raise ValueError('Hero and power installation identities must be distinct')


def install_generated_hero_card(r, effect, *, offered=None):
    """Trusted resolver-only helper. Public card callbacks return the Effect."""
    if type(effect) is not InstallGeneratedHeroCard:
        raise ValueError('Generated hero installation requires its typed effect')
    effect.__post_init__()
    source_exists(r, effect.source_id)
    player = r.player(effect.player_id)
    definition = r.registry.card(effect.card_id)
    if (definition.kind != CardType.HERO or not definition.hero_card or
            not definition.hand_playable):
        raise ResolutionError('Generated installation requires a playable hero card')
    power_effect = ReplaceHeroPower(player.id, definition.initial_hero_power)
    # Validate every definition before vacating any physical slot.
    installation_definition(r, power_effect)
    old = r.state.entities.get(player.hero_id)
    if (old is None or old.kind != CardType.HERO or old.zone != Zone.HERO or
            old.controller != player.id or old.health <= 0 or old.doomed):
        raise ResolutionError('Generated hero installation requires the living current hero')
    old_power_id = player.hero_power_id
    from .hero_health_history import snapshot as hero_health_snapshot
    health_before = hero_health_snapshot(old)
    removed = (tuple(player.additional_hero_power_ids)
               if definition.additional_power_policy == 'remove' else ())
    # Match the existing hero replacement lifecycle: this is not a death and
    # Resolver.move explicitly forbids moving HERO entities. No HAND staging.
    old.zone = Zone.GRAVEYARD
    player.graveyard.append(old.id)
    player.hero_id = 0
    new = r.create_entity(player.id, definition.id, Zone.HERO)
    if offered is not None:
        from .offered_card_execution import apply_material
        apply_material(r, *offered, new)
    offered_enchantments = list(new.enchantments)
    printed = new.abilities
    copy_attachments(r.state, old, new)
    new.enchantments = [*offered_enchantments, *new.enchantments]
    new.abilities = [*printed, *(a for a in new.abilities if a.origin != 'printed')]
    new.base_health = old.base_health
    new.silenced = False
    refresh_entity(new)
    new.damage = max(0, new.max_health - old.health)
    new.armor = old.armor + definition.hero_armor
    new.attacks_this_turn = old.attacks_this_turn
    new.frozen_until_owner_turn = old.frozen_until_owner_turn
    new.origin_entity_id = old.id
    assign_hero_class(player, definition)
    r.refresh_auras()
    replace_hero_additional_powers(r, player, definition.additional_power_policy)
    r.emit('hero_replaced', source_id=old.id, target_id=new.id, player_id=player.id,
           _hero_health_before=health_before)
    replace_hero_power(r, power_effect)
    return GeneratedHeroInstallation(player.id, definition.id, effect.source_id,
        old.id, new.id, old_power_id, player.hero_power_id, removed)


def handle_generated_hero_card(r, effect):
    install_generated_hero_card(r, effect)
    return ()


def register(mechanics):
    if GeneratedHeroInstallation not in mechanics.payload_types:
        mechanics.register_payload_type(GeneratedHeroInstallation)
    mechanics.register(InstallGeneratedHeroCard, handle_generated_hero_card)
    return mechanics
