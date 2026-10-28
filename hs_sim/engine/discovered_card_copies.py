"""Copies of genuine Discover results through ordinary copy/creation writers.

The semantic event fixes recipient identity; the copy accepts its current
material at execution, after earlier ordinary observers. Missing/stale or burned
recipients use the original typed recipe or offered
material; they never select another same-name physical card.
"""
from dataclasses import dataclass, fields, replace
import json

from .copy_materials import CapturedCardCopyMaterial
from .discovery_delivery import COMPLETED, DiscoveryCompletion, original_recipient
from .effects import AddToHand, Effect, _integer, _player
from .model import Event, Zone
from .registry import UnsupportedDefinitionError


def same_recipient(fact, entity):
    return fact is not None and entity is not None and (
        entity.id, entity.card_id, entity.kind, entity.owner, entity.controller,
        entity.zone, entity.zone_epoch, entity.entered_order) == (
        fact.entity_id, fact.card_id, fact.kind, fact.owner, fact.controller,
        fact.zone, fact.zone_epoch, fact.entered_order)


@dataclass(frozen=True)
class CopyDiscoveredCard(Effect):
    player_id: int
    source_id: int
    event: Event

    def __post_init__(self):
        _player(self.player_id); _integer(self.source_id, 'discovery copy observer', 1)
        if type(self.event) is not Event or self.event.kind != COMPLETED or self.event.player_id != self.player_id:
            raise ValueError('Discovery copy requires its genuine original completion and actor')


def request(context, registry):
    event = context.event
    if event is None or event.kind != COMPLETED or event.player_id != context.player_id: return ()
    original_recipient(context.state, event)
    row = context.state.card_discovery_history[dict(event.data)['discovery_id']-1]
    card = registry.card(row.result.selected[0].card_id)
    if not card.hand_playable:
        raise UnsupportedDefinitionError('Copying a discovered non-hand-playable card is not implemented: '+card.id)
    return (CopyDiscoveredCard(context.player_id, context.source_id, event),)


def original(r, effect):
    effect.__post_init__(); event = effect.event
    if event.sequence > len(r.game._events) or r.game._events[event.sequence-1] != event:
        raise ValueError('Discovery copy lost its actual original completion event')
    fact = original_recipient(r.state, event)
    row = r.state.card_discovery_history[dict(event.data)['discovery_id']-1]
    if not any(s.source.entity_id == effect.source_id and s.source.controller == effect.player_id for s in row.trigger_sources):
        raise ValueError('Discovery copy has no qualified original observer')
    from .continuations import FrameCodec
    from .discovery_delivery import validate_completion
    completion = FrameCodec(r.game.mechanics, r.registry).decode(json.loads(dict(event.data)['receipt']))
    if type(completion) is not DiscoveryCompletion or completion.result != row.result or completion.recipient != fact:
        raise ValueError('Discovery copy changed its original completed selection')
    validate_completion(r.state, r.registry, completion, closed=True)
    from .discovery_offers import offer_for_result
    offer = offer_for_result(r.game, row.result)
    option = next(o for o in offer.options if o.id == row.result.selected_ids[0])
    material = next(m for m in offer.materials if m.option_id == option.id)
    return row, completion, offer, option, material


def intrinsic_rewards(r, option, entity, source_id, *, grants=True):
    from .offered_card_execution import apply_discovery_intrinsics
    apply_discovery_intrinsics(r, option, entity, source_id, gifts=grants, publish_gift=False)
    from .discovery import ResolvePoolDiscovery
    if grants and option.effects and type(option.effects[0]) is ResolvePoolDiscovery:
        spec = option.effects[0].batch.spec
        if spec.cost is not None:
            from .costs import attach_cost
            attach_cost(r.state, entity, spec.cost, source_id, spec.expires_turn)
        if spec.minion_grant is not None:
            install_copied_grant(r, entity, spec.minion_grant, source_id)
    from .lifecycle import refresh_entity
    refresh_entity(entity); r.refresh_auras()


def install_copied_grant(r, entity, grant, source_id):
    if grant is None: return
    from types import SimpleNamespace
    from .card_creation import install
    install(r.state, entity, SimpleNamespace(spell_repeat=None, minion_grant=grant,
        source_id=source_id), resolver=r, publish_gift=False)


def create_recipe_copy(r, effect, creation):
    from .opening import create_hand_card, validate_hand_card
    validate_hand_card(r, creation)
    # Retain the original grant material without another original-grant event.
    entity = create_hand_card(r, replace(creation, minion_grant=None),
        defer_publication=True, hand_entry_source_id=effect.source_id)
    install_copied_grant(r, entity, creation.minion_grant, creation.source_id)
    return entity


def fallback(r, effect, row, completion, offer, option, material):
    from .zones import AddToDeck, CopyCard, copy_physical_card
    from .temporary_cards import CreateTemporaryCard
    from .discovery_destinations import DeliverDiscoveredSpell
    from .spell_weapons import DeliverDiscoveredSpellWeapon
    from .spell_casts import CastSpell
    from .opening import create_hand_card
    if offer.on_select is not None:
        raise UnsupportedDefinitionError('Stale discovered copies with a custom selection continuation require its original material')
    recipe = completion.recipe; original_source = completion.result.choice.source_id
    entity = None; mode = 'base'
    if type(recipe) in (AddToHand, AddToDeck):
        values = {f.name:getattr(recipe, f.name) for f in fields(AddToHand) if hasattr(recipe, f.name)}
        values.update(player_id=effect.player_id, revealed_to=())
        creation = AddToHand(**values)
        entity = create_recipe_copy(r, effect, creation)
        intrinsic_rewards(r, option, entity, original_source, grants=False)
    elif type(recipe) is CreateTemporaryCard:
        creation = AddToHand(effect.player_id, recipe.card_id, original_source, cost=recipe.cost,
            expires_turn=recipe.cost_expires_turn, spell_repeat=recipe.spell_repeat)
        entity = create_hand_card(r, creation, defer_publication=True, hand_entry_source_id=effect.source_id)
        from .model import HandLifetime
        entity.hand_lifetime = HandLifetime(original_source, row.turn,
            recipe.expires_turn, recipe.minimum_cost)
        mode = 'current'
        intrinsic_rewards(r, option, entity, original_source, grants=False)
    elif type(recipe) in (DeliverDiscoveredSpell, DeliverDiscoveredSpellWeapon, CastSpell):
        # Original producer validators require a plain spell discovery.
        entity = create_hand_card(r, AddToHand(effect.player_id, option.card_id, effect.source_id), defer_publication=True)
    elif material.route in ('physical', 'death', 'discard'):
        from .offered_card_execution import copy_mode
        source = material.physical or material.death or material.discard
        mode = copy_mode(r.state, option) if material.physical is not None else 'base'
        if material.physical is not None and material.physical.origin.zone in (Zone.BOARD, Zone.GRAVEYARD): mode = 'base'
        if type(recipe) is CopyCard and recipe.cast_when_drawn:
            raise UnsupportedDefinitionError('Stale discovered draw-cast copies require their original delivered material')
        operation = CopyCard(source, effect.player_id, mode=mode, source_id=effect.source_id)
        entity = copy_physical_card(r, operation, publish=False)
        intrinsic_rewards(r, option, entity, original_source)
        if type(recipe) is CopyCard and recipe.stats is not None:
            from .lifecycle import apply_summon_stats
            apply_summon_stats(r.state, entity, recipe.stats)
        if type(recipe) is CopyCard and recipe.cost is not None:
            from .costs import attach_cost
            attach_cost(r.state, entity, recipe.cost, original_source, recipe.expires_turn)
    elif material.route == 'printed':
        from .sideboards import _TakeSideboardCard
        if recipe is not None and type(recipe) is not _TakeSideboardCard:
            raise UnsupportedDefinitionError('Unreviewed original printed discovery-copy recipe: '+type(recipe).__name__)
        card = r.registry.card(option.card_id)
        if card.starship_for:
            raise UnsupportedDefinitionError('Discovered Starship copy requires its complete original composition')
        entity = create_hand_card(r, AddToHand(effect.player_id, option.card_id, effect.source_id), defer_publication=True)
        intrinsic_rewards(r, option, entity, original_source)
    elif material.route == 'copied':
        mode = material.copied.mode
        from .hand_capacity import hand_capacity
        zone = Zone.HAND if len(r.player(effect.player_id).hand) < hand_capacity(r.player(effect.player_id), r.rules) else Zone.GRAVEYARD
        entity = r.create_entity(effect.player_id, option.card_id, zone,
            components=material.copied.stored_components, hand_entry_source_id=effect.source_id)
        from .copy_materials import apply
        apply(r, replace(material.copied, minion_grant=None, grant_source_id=None), entity)
        install_copied_grant(r, entity, material.copied.minion_grant, material.copied.grant_source_id)
        intrinsic_rewards(r, option, entity, original_source)
    else:
        raise UnsupportedDefinitionError('Original discovered copy material is unavailable: '+option.card_id)
    fact = completion.recipient
    if fact is not None:
        entity.origin_entity_id = fact.entity_id
        from .held_opponent_copies import copy_origin
        entity.copy_origin = copy_origin(fact)
    return entity, mode


def copy_original_selection(r, effect, row, completion, offer, option, offered):
    card = r.registry.card(option.card_id)
    if not card.hand_playable:
        raise UnsupportedDefinitionError('Copying a discovered non-hand-playable card is not implemented: '+card.id)
    from .zones import CopyCard, copy_physical_card, announce_copied_card
    fact = completion.recipient
    recipient = None if fact is None else r.state.entities.get(fact.entity_id)
    if (same_recipient(fact, recipient) and (fact.card_id, fact.kind) == (card.id, card.kind) and
            fact.zone in (Zone.HAND, Zone.DECK, Zone.BOARD, Zone.WEAPON)):
        material = CapturedCardCopyMaterial.capture(r.state, recipient)
        mode = 'current' if fact.zone in (Zone.HAND, Zone.DECK) else 'base'
        entity = copy_physical_card(r, CopyCard(material, effect.player_id,
            mode=mode, source_id=effect.source_id), publish=False)
        if mode == 'base': intrinsic_rewards(r, option, entity, row.result.choice.source_id)
    else:
        entity, mode = fallback(r, effect, row, completion, offer, option, offered)
    if completion.recipient is not None:
        from types import SimpleNamespace
        publication = SimpleNamespace(player_id=effect.player_id, source_id=effect.source_id,
            destination=Zone.HAND, mode=mode)
        announce_copied_card(r, entity, publication, completion.recipient.entity_id)
    else:
        from .opening import announce_hand_card
        announce_hand_card(r, AddToHand(effect.player_id, option.card_id, effect.source_id), entity)
    return ()


def execute(r, effect):
    return copy_original_selection(r, effect, *original(r, effect))


def register(mechanics):
    mechanics.register(CopyDiscoveredCard, execute)
