"""Shared entity materialization into a caller-owned state; no RNG or events."""
from .errors import ResolutionError
from .model import CardType, Entity, Zone
from .lifecycle import install_base, initialize_dormancy
from .hero_powers import assign_hero_class


def _player(state, player_id):
    if type(player_id) is not int or player_id not in state.players:
        raise ResolutionError(f'Unknown player: {player_id}')
    return state.players[player_id]


def create_entity(state, registry, player_id, card_id, zone, position=None, ready=False, *, components=(), hand_entry_reason='created', hand_entry_source_id=None, additional_hero_power=False, entry_herald_count=None, interactable_object=False, entry_dormant_turns=None):
    # HAND previews fork entities, player hands, hand_entries and scalar ID
    # counters; existing entities/histories are read-only. New state-side writes
    # in this path must also be detached by generated_card_preview._preview_inputs.
    from .game_boards import resolve_card_id
    card_id = resolve_card_id(state, registry, card_id)
    player = _player(state, player_id)
    definition = registry.card(card_id)
    if (type(interactable_object) is not bool or (definition.interactable is not None) != interactable_object or
            interactable_object and (zone != Zone.BOARD or components)):
        raise ResolutionError('Interactable carriers require their dedicated board installation')
    if type(additional_hero_power) is not bool or (additional_hero_power and zone != Zone.HERO_POWER):
        raise ResolutionError('Additional hero powers require the hero power zone')
    if zone == Zone.HERO_POWER and definition.kind != CardType.HERO_POWER:
        raise ResolutionError('Hero power installation requires a hero power definition')
    if definition.choice_only:
        raise ResolutionError('Choice-only definitions cannot become physical cards')
    entity_id = state.next_entity_id
    state.next_entity_id += 1
    entity = Entity(id=entity_id, card_id=card_id, owner=player_id, controller=player_id,
                    zone=zone, kind=definition.kind, base_attack=definition.attack, base_health=definition.health,
                    base_cost=definition.cost, keywords=set(definition.keywords),
                    summoned_turn=0 if ready else state.turn,
                    durability=definition.durability, use_limit=definition.uses_per_turn,
                    interactable_object=interactable_object,
                    corpse_value=(int(definition.kind == CardType.MINION) if definition.corpse_value is None
                                  else definition.corpse_value))
    state.entities[entity_id] = entity
    if entry_herald_count is not None:
        from .effects import _integer
        _integer(entry_herald_count,'accepted entry Herald count',0)
        if not definition.herald_scaling or zone!=Zone.BOARD:raise ResolutionError('Deferred entry strength requires its scaling board definition')
    install_base(state, entity, definition, registry, components, entry_herald_count=entry_herald_count)
    from .cthun import initialize_instance as initialize_cthun
    initialize_cthun(state, registry, entity)
    initialize_dormancy(state, entity, definition, turns_override=entry_dormant_turns)
    if additional_hero_power:
        player.additional_hero_power_ids.append(entity_id)
    elif zone in (Zone.HERO, Zone.WEAPON, Zone.HERO_POWER):
        field = {Zone.HERO: 'hero_id', Zone.WEAPON: 'weapon_id', Zone.HERO_POWER: 'hero_power_id'}[zone]
        if getattr(player, field):
            raise ResolutionError('Entity slot is already occupied')
        setattr(player, field, entity_id)
        if zone == Zone.HERO:
            assign_hero_class(player, definition)
    else:
        dest = getattr(player, zone.value.lower())
        if position is None:
            dest.append(entity_id)
        else:
            dest.insert(max(0, min(position, len(dest))), entity_id)
    if zone in (Zone.HERO, Zone.BOARD, Zone.WEAPON, Zone.QUEST, Zone.SECRET, Zone.HERO_POWER):
        entity.entered_order = state.next_order
        state.next_order += 1
    if zone == Zone.BOARD and entity.kind == CardType.MINION:
        entity.board_presence_id = entity.entered_order
    if zone == Zone.HAND:
        from .hand_history import enter_hand
        enter_hand(state, entity, reason=hand_entry_reason, source_id=hand_entry_source_id)
    from .location_rune_locks import initialize as initialize_location_lock
    initialize_location_lock(state, registry, entity)
    from .spell_mana_freeze import initialize as initialize_spell_mana_freeze
    initialize_spell_mana_freeze(state,registry,entity)
    from .school_freeze import initialize as initialize_school_freeze
    initialize_school_freeze(state,registry,entity,fresh=True)
    return entity

