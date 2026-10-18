"""Frozen original offered-card material applied by existing entry pipelines.

No hand staging, acquisition, payment, original-card removal or effect loop.
Only the per-option intrinsic gift travels; selected-only delivery rewards do
not become grants on the other options. These policies remain CN-calibratable.
"""
from dataclasses import replace
from functools import lru_cache
from types import SimpleNamespace

from .offered_card_selection import OfferedCardSelection


@lru_cache(maxsize=1)
def _core_codec_mechanics():
    from .resolver import default_mechanics
    return default_mechanics()


@lru_cache(maxsize=32)
def original_offer(registry, encoded):
    # Cache only immutable source recipes under the actual registry identity;
    # never cache a live Game, GameState, Resolution or RNG.
    from .discovery_offers import decode_offer
    return decode_offer(SimpleNamespace(registry=registry, mechanics=_core_codec_mechanics()), encoded)


def original(registry, selection, slot_id):
    if type(selection) is not OfferedCardSelection:
        return None
    offer = original_offer(registry, selection.discovery.original_offer)
    if offer.choice != selection.discovery.result.choice or not 1 <= slot_id <= len(offer.options):
        raise ValueError('Offered execution lost its complete original choice and slot')
    return offer.options[slot_id - 1], offer.materials[slot_id - 1]


def components_for(registry, selection, slot_id):
    found = original(registry, selection, slot_id)
    if found is None: return ()
    _, material = found
    if material.physical is not None: return material.physical.components
    if material.death is not None: return material.death.components
    if material.discard is not None: return material.discard.components
    return ()


def copy_mode(state, option):
    from .zones import CopyCard, MoveCard
    from .hand_choice_followups import ResolveHandFollowupChoice, record
    if not option.effects: return 'base'
    work = option.effects[0]
    if type(work) is CopyCard: return work.mode
    if type(work) is MoveCard: return 'base' if work.reset else 'current'
    if type(work) is ResolveHandFollowupChoice:
        return 'base' if record(state, work.followup_id).request.operation == 'copy_base' else 'current'
    return 'current'


def saved_branch(state, registry, selection, slot_id):
    found = original(registry, selection, slot_id)
    if found is None: raise ValueError('Offered branch requires its exact source')
    option, material = found
    local = material.physical.local if material.physical is not None else (
        material.copied.local if material.copied is not None else None)
    branch = local.choose_branch if local is not None and copy_mode(state, option) == 'current' else None
    if branch is None: return None
    from .choose_branch_state import validate_selection
    validate_selection(registry, branch, card_id=option.card_id)
    return branch


def selected_branch(state, registry, selection, slot_id, origin):
    branch = saved_branch(state, registry, selection, slot_id)
    return None if branch is None or origin not in branch.origins else replace(branch, origins=(origin,))


def apply_material(r, selection, slot_id, entity):
    found = original(r.registry, selection, slot_id)
    if found is None: return
    option, material = found
    from .offered_card_materials import validate_material
    validate_material(r.state, r.registry, material)
    if entity.card_id != material.card_id:
        raise ValueError('Offered material borrowed another allocated card')
    if material.route == 'unavailable':
        raise ValueError('Original offered physical card was already unavailable')
    if material.copied is not None:
        from .copy_materials import apply
        apply(r, material.copied, entity)
    elif material.physical is not None:
        source = material.physical.entity()
        from .jade import inherit_printed
        inherit_printed(source, entity)
        if copy_mode(r.state, option) == 'current':
            from .zones import copy_current_stored_state
            copy_current_stored_state(r.state, source, entity)
            # A copy played from an offered battlefield card is a fresh body,
            # using the same stored-acquisition injury cleanup as CopyCard.
            from .model import Zone
            if source.zone == Zone.BOARD: entity.damage = 0
    elif material.death is not None or material.discard is not None:
        row = material.death or material.discard
        from .jade import inherit_printed
        from .model import Entity, Zone
        inherit_printed(Entity(row.entity_id, row.card_id, row.owner if material.death else row.card.owner,
            row.controller if material.death else row.player_id, Zone.GRAVEYARD,
            kind=entity.kind, components=row.components, jade_size=row.jade_size), entity)
    gift = None
    if option.effects:
        from .discovery import ResolvePoolDiscovery
        from .stored_gift_discovery import SelectGiftedDeckCard, gift_by_id
        work = option.effects[0]
        if type(work) is ResolvePoolDiscovery: gift = work.selection.gift
        elif type(work) is SelectGiftedDeckCard: gift = gift_by_id(work.offered[work.index].gift_id)
    if gift is not None:
        from .card_creation import install
        source_id = selection.discovery.result.choice.source_id
        install(r.state, entity, SimpleNamespace(spell_repeat=None,
            minion_grant=replace(gift.grant, identity=gift.id), source_id=source_id))
        if gift.cost_delta:
            from .costs import attach_cost
            from .model import CostSpec
            attach_cost(r.state, entity, CostSpec(delta=gift.cost_delta), source_id)
    from .lifecycle import refresh_entity
    refresh_entity(entity)
    r.refresh_auras()


def entry_context(state, material):
    """Resolve one already accepted primary, never infer allocated IDs."""
    ledger = state.whole_card_replay_ledger
    root = ledger.roots[material.root_id - 1]
    child = ledger.children[material.child_id - 1]
    return root.selection, child.occurrence_id


def components_for_entry(state, registry, material):
    return components_for(registry, *entry_context(state, material))


def apply_entry(r, material, entity):
    apply_material(r, *entry_context(r.state, material), entity)
    entity.origin_entity_id = r.state.whole_card_replay_ledger.roots[material.root_id - 1].caster.entity_id
