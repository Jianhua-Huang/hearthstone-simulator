"""Shared original graveyard return delivery, reset, capacity and publication."""
from .allocation_facts import SourceAllocationFact
from .hand_capacity import hand_capacity
from .lifecycle import reset_to_definition
from .model import CardType,CostSpec,Zone


def deliver(r,entity,source_id,*,cost_delta=0,recipient_id=None,preserve_spell_material=False):
    player=r.player(entity.controller if recipient_id is None else recipient_id)
    previous=entity.zone
    if previous!=Zone.GRAVEYARD:raise ValueError('Captured graveyard return delivery required')
    if preserve_spell_material and entity.kind!=CardType.SPELL:
        raise ValueError('Native spell return requires an actual physical spell')
    def move(zone):
        old_controller=entity.controller
        r.move(entity,zone,hand_entry_reason=None)
        if player.id!=old_controller:
            getattr(r.player(old_controller),zone.value).remove(entity.id)
            getattr(player,zone.value).append(entity.id);entity.controller=player.id
    if len(player.hand)>=hand_capacity(player,r.rules):
        original=SourceAllocationFact.capture(r.state,entity)
        move(Zone.GRAVEYARD);r.refresh_auras()
        from .zones import emit_burn
        emit_burn(r,entity,profile='graveyard_delivery_overflow',original=original,
            source_id=source_id,player_id=player.id,reason='return_hand_full')
        return ()
    value=None;aura_sources=()
    if preserve_spell_material:
        from .native_spell_values import bound_value,validate_carrier
        from .aura_duration import KIND
        validate_carrier(r.state,r.registry,entity.card_id,entity.kind,entity.abilities)
        value=bound_value(entity);aura_sources=tuple(a.source_id for a in entity.abilities if a.kind==KIND)
    move(Zone.HAND)
    from .hand_history import enter_hand,publish
    enter_hand(r.state,entity,previous,'return',source_id=source_id)
    reset_to_definition(r.state,entity,r.registry.card(entity.card_id),r.registry,
        preserve_jade=True,preserve_cthun=True,preserve_weapon_spell=preserve_spell_material)
    if value is not None:
        from .native_spell_values import install
        install(r.state,r.registry,entity,value)
    if aura_sources:
        from .aura_duration import install
        for original_source in aura_sources:install(r.state,r.registry,entity,original_source)
    if cost_delta:
        from .zones import CardReference,ModifyStoredCost,modify_stored_cost
        modify_stored_cost(r,ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=cost_delta),source_id))
    r.refresh_auras()
    r.emit('card_returned',source_id=source_id,target_id=entity.id,player_id=player.id)
    publish(r,entity.hand_entry_id)
    return ()
