"""Pure, complete witness queries for sustained board repeat conditions.

Presence is declared by a frozen registry profile. The returned identities are
transient query facts: durable repeat history does not keep or rejudge witnesses.
"""
from .model import (AbilityInstance, BattlecryRepeatSpec, ComboRepeatSpec, CardType,
                    DeathRecord, DeathrattleRepeatSpec, HeroPowerRepeatSpec, EndTurnRepeatSpec, GameState,
                    RepeatSourceEligibility, SpellRepeatSpec, Zone)
from .pools import PoolQuery, matches_metadata


def validate_source_declaration(registry, spec, *, allow_source=True):
    """Validate the complete declaration before any recipient or stale exit."""
    if type(spec) not in (SpellRepeatSpec, BattlecryRepeatSpec, ComboRepeatSpec, DeathrattleRepeatSpec, HeroPowerRepeatSpec, EndTurnRepeatSpec) or type(allow_source) is not bool:
        raise ValueError('Repeat source validation requires a supported repeat specification and a boolean scope')
    spec.__post_init__()
    if type(spec) is SpellRepeatSpec:
        from .repeat_matching import validate_repeat_cost_declaration
        validate_repeat_cost_declaration(registry, spec)
    if type(spec) in (BattlecryRepeatSpec, ComboRepeatSpec, DeathrattleRepeatSpec) and not allow_source and spec.scope != 'friendly':
        raise ValueError('Player repeat policies have no physical self carrier')
    condition = spec.match.source_eligibility if spec.match is not None else None
    if condition is not None:
        if not allow_source:
            raise ValueError('This repeat source has no physical board carrier')
        registry.repeat_witness_profile(condition.profile_id).__post_init__()
    return condition


def _witness_profile(state, registry, *, player_id, carrier_id, eligibility):
    """Validate the query without deciding whether its source is live or frozen."""
    if type(state) is not GameState or type(eligibility) is not RepeatSourceEligibility:
        raise ValueError('Repeat witnesses require GameState and RepeatSourceEligibility')
    eligibility.__post_init__()
    profile = registry.repeat_witness_profile(eligibility.profile_id)
    profile.__post_init__()
    if type(player_id) is not int or player_id not in (1, 2) or type(carrier_id) is not int:
        raise ValueError('Repeat witnesses require a player and physical carrier')
    return profile


def _qualifying_board_witnesses(state, registry, *, player_id, carrier_id, eligibility, profile):
    """Complete pure board traversal, reached only through a checked source wrapper."""
    player = state.players[player_id]
    query = PoolQuery(tribes_any=eligibility.tribes_any)
    witnesses = []
    # Complete traversal is intentional. A known matching first candidate may
    # not hide required but unknown metadata on another qualified candidate.
    for entity_id in player.board:
        entity = state.entities[entity_id]
        if entity.zone != Zone.BOARD or entity.controller != player_id:
            raise ValueError('Repeat witness board membership disagrees with control')
        if entity.kind != CardType.MINION or eligibility.exclude_carrier and entity_id == carrier_id:
            continue
        if ((entity.dormancy is not None and not profile.include_dormant) or
                (entity.starship_building and not profile.include_starship_building) or
                (entity.doomed and not profile.include_doomed) or
                (profile.require_positive_health and entity.health <= 0)):
            continue
        definition = registry.card(entity.card_id)
        if definition.kind != CardType.MINION:
            raise ValueError('Repeat witness face is not a minion')
        if profile.basis=='current_tribes':
            from .tribes import has_any_tribe
            matched=has_any_tribe(registry,entity,eligibility.tribes_any,basis='current')
        else:
            matched = matches_metadata(query, card_id=definition.id, kind=definition.kind,
                cost=definition.cost, meta=definition.metadata, spell_school=definition.spell_school,
                keywords=definition.keywords)
        if matched:
            witnesses.append(entity_id)
    return tuple(witnesses)


def qualifying_repeat_witnesses(state, registry, *, player_id, carrier_id, eligibility):
    """Return every qualified physical witness for this player's live board source."""
    profile = _witness_profile(state, registry, player_id=player_id,
        carrier_id=carrier_id, eligibility=eligibility)
    player = state.players[player_id]
    carrier = state.entities.get(carrier_id)
    if (carrier is None or carrier.kind != CardType.MINION or carrier.zone != Zone.BOARD or
            carrier.controller != player_id or carrier_id not in player.board):
        raise ValueError('Repeat source is not this player\'s physical board minion')
    return _qualifying_board_witnesses(state, registry, player_id=player_id,
        carrier_id=carrier_id, eligibility=eligibility, profile=profile)


def qualifying_deathrattle_self_witnesses(state, registry, *, player_id, carrier_id,
                                         eligibility, death, source_ability):
    """Query the original post-removal board for one authenticated frozen self policy.

    This cannot turn an arbitrary removed carrier into a live repeat source. The
    death record and the complete source ability must belong to this exact state.
    """
    profile = _witness_profile(state, registry, player_id=player_id,
        carrier_id=carrier_id, eligibility=eligibility)
    if type(death) is not DeathRecord or type(source_ability) is not AbilityInstance:
        raise ValueError('Frozen Deathrattle self source requires its death and ability')
    death.__post_init__(); source_ability.__post_init__()
    records = [record for record in state.death_history if record.id == death.id]
    carrier = state.entities.get(carrier_id)
    if (len(records) != 1 or records[0] != death or death.entity_id != carrier_id or
            death.controller != player_id or death.zone != Zone.BOARD or
            registry.card(death.card_id).kind != CardType.MINION or
            carrier is None or carrier.kind != CardType.MINION or carrier.zone == Zone.BOARD or
            any(carrier_id in player.board for player in state.players.values())):
        raise ValueError('Frozen Deathrattle self source is not its original removed board minion')
    members = [ability for ability in death.abilities if ability.id == source_ability.id]
    if (len(members) != 1 or members[0] != source_ability or
            source_ability.kind != 'deathrattle_repeat' or source_ability.consumed or
            source_ability.deathrattle_repeat.scope != 'self' or
            source_ability.expires_turn is not None and source_ability.expires_turn < death.turn):
        raise ValueError('Frozen Deathrattle self source differs from its unconsumed self declaration')
    if validate_source_declaration(registry, source_ability.deathrattle_repeat) != eligibility:
        raise ValueError('Frozen Deathrattle self condition differs from its complete declaration')
    return _qualifying_board_witnesses(state, registry, player_id=player_id,
        carrier_id=carrier_id, eligibility=eligibility, profile=profile)
