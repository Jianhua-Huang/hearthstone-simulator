"""Turn-bound keyword lifetimes; provisional lifecycle contract R-129."""
from dataclasses import replace

from .model import CardType, Keyword, KeywordExpiry, TimedKeywordSpec, Zone
from .owner_turns import owner_turn_index

HERO_IMMUNITY = TimedKeywordSpec(Keyword.IMMUNE)


def supports_grant(entity, spec, source_id):
    """Keep the existing minion scope; only the real next-own-start hero grant extends it."""
    return (entity.kind == CardType.MINION and entity.zone == Zone.BOARD or
            entity.kind == CardType.HERO and entity.zone == Zone.HERO and
            spec == HERO_IMMUNITY and source_id is not None)


def deadline(state, controller, spec):
    player = controller if spec.player == 'controller' else 3 - controller
    return owner_deadline(state, player, spec.boundary, spec.occurrences)


def owner_deadline(state, player, boundary='turn_started', occurrences=1):
    """Shared actual interval clock, without a keyword or numeric executor."""
    index = owner_turn_index(state, player) + occurrences
    if boundary == 'turn_ended' and player == state.active_player:
        index -= 1
    creation = state.owner_turn_history[-1].id if state.owner_turn_history else (1 if state.opening is None else None)
    return KeywordExpiry(player, state.turn, max(1, index), boundary, creation)


def arm(state, entity):
    """First board installation arms dormant and active flags alike, once only."""
    if entity.zone != Zone.BOARD or entity.kind != CardType.MINION or entity.starship_building:
        return
    entity.abilities = [replace(a, keyword_expiry=deadline(state, entity.controller, a.timed_keyword))
        if a.timed_keyword is not None and a.keyword_expiry is None and not a.consumed else a
        for a in entity.abilities]


def expire(r, boundary, turn, player_id):
    """Remove all due flags before capturing any expiry reactions."""
    from .lifecycle import remove_attachments
    expired = []
    for entity in r.state.entities.values():
        ids = tuple(a.id for a in entity.abilities for expiry in (a.keyword_expiry,a.health_rule_expiry,a.attack_policy_expiry) if expiry is not None and
            expiry.boundary == boundary and expiry.player_id == player_id and
            expiry.owner_turn_index <= owner_turn_index(r.state, player_id))
        # A finite next-start grant is still available during that start's
        # capture/reactions. Retire it at the matching actual interval's end,
        # including a dormant carrier which could not capture its one window.
        ids += tuple(a.id for a in entity.abilities if a.limited_trigger_deadline is not None
            and boundary == 'turn_ended' and a.limited_trigger_deadline.player_id == player_id
            and a.limited_trigger_deadline.owner_turn_index <= owner_turn_index(r.state, player_id))
        numeric_ids = tuple(e.id for e in entity.enchantments if e.owner_turn_expiry is not None and
            e.owner_turn_expiry.boundary == boundary and e.owner_turn_expiry.player_id == player_id and
            e.owner_turn_expiry.owner_turn_index <= owner_turn_index(r.state, player_id))
        if ids or numeric_ids:
            remove_attachments(entity, enchantment_predicate=lambda e: e.id in numeric_ids,
                               ability_predicate=lambda a: a.id in ids)
            expired.append((entity.id, tuple(sorted((*ids,*numeric_ids)))))
    if expired:
        r.refresh_auras()
        for entity_id, ids in expired:
            r.emit('attachments_expired', target_id=entity_id, attachment_ids=ids)
    return bool(expired)


def validate_definition(card):
    if type(card.timed_keywords) is not tuple or any(type(s) is not TimedKeywordSpec for s in card.timed_keywords):
        raise ValueError('timed_keywords requires an immutable tuple of TimedKeywordSpec')
    if card.timed_keywords and (card.kind != CardType.MINION or card.choice_only):
        raise ValueError('Printed timed keywords require physical minions')
    seen = set()
    for spec in card.timed_keywords:
        spec.__post_init__()
        if spec.keyword not in card.keywords or spec.keyword in seen:
            raise ValueError('Each timed keyword must uniquely qualify a printed keyword')
        seen.add(spec.keyword)


def validate_instance(state, entity, ability):
    spec, expiry = ability.timed_keyword, ability.keyword_expiry
    if spec is None:
        return
    if entity.kind != CardType.MINION:
        # Replacing a hero copies its ordinary granted attachments to the new
        # hero and retains the old allocation in the graveyard. Both keep the
        # original deadline and are retired by the same shared clock.
        if (entity.kind != CardType.HERO or ability.origin != 'granted' or
                spec != HERO_IMMUNITY or ability.source_id is None or expiry is None):
            raise ValueError('Timed keywords require minion carriers or next-turn granted hero immunity')
    if expiry is None:
        if entity.zone == Zone.BOARD and not entity.starship_building and not ability.consumed:
            raise ValueError('A board timed keyword has no deadline')
        return
    if entity.starship_building:
        raise ValueError('Unlaunched construction cannot have an armed keyword clock')
    validate_deadline(state, expiry, spec.occurrences)


def validate_deadline(state, expiry, occurrences=1):
    """Validate the original creation interval, not the present controller."""
    expiry.__post_init__()
    if expiry.created_turn > state.turn:
        raise ValueError('Timed keyword was created in the future')
    origin = expiry.created_owner_turn_id
    if origin is None:
        if state.opening is None or expiry.created_turn != 1:
            raise ValueError('Pre-first keyword clock requires a constructed opening')
        active_at_creation, index = state.opening.first_player, 0
    elif not state.owner_turn_history and state.opening is None:
        # Scenario entities are installed before its conceptual interval is recorded.
        if origin != 1 or expiry.created_turn != 1 or state.turn != 1:
            raise ValueError('Invalid conceptual keyword creation interval')
        active_at_creation = state.active_player
        index = int(expiry.player_id == active_at_creation)
    else:
        if origin > len(state.owner_turn_history):
            raise ValueError('Keyword creation interval does not exist')
        record = state.owner_turn_history[origin - 1]
        if record.id != origin or record.turn != expiry.created_turn:
            raise ValueError('Keyword creation interval disagrees with its actual turn')
        active_at_creation = record.player_id
        previous = next((v for v in reversed(state.owner_turn_history[:origin])
                         if v.player_id == expiry.player_id), None)
        index = previous.owner_index if previous is not None else 0
    expected = index + occurrences - int(expiry.boundary == 'turn_ended' and expiry.player_id == active_at_creation)
    if expiry.owner_turn_index != max(1, expected):
        raise ValueError('Keyword deadline disagrees with its boundary count')


def validate_boundary(game):
    state = game._state
    # End-boundary expirations may still be pending during an ending-turn choice.
    # Start-boundary removal is atomic before any reaction can pause.
    for entity in state.entities.values():
        for ability in entity.abilities:
            expiry = ability.limited_trigger_deadline
            if expiry is not None:
                validate_deadline(state, expiry)
                previous = next((v for v in reversed(state.owner_turn_history) if v.player_id == expiry.player_id), None)
                index = previous.owner_index if previous is not None else 0
                if expiry.owner_turn_index < index or expiry.owner_turn_index == index and previous.closed:
                    raise ValueError('Expired finite next-start grant at action boundary')
            expiry=ability.health_rule_expiry
            if expiry is not None and expiry.owner_turn_index<=owner_turn_index(state,expiry.player_id):
                raise ValueError('Expired owner health rule at action boundary')
        for enchantment in entity.enchantments:
            expiry = enchantment.owner_turn_expiry
            if expiry is not None and expiry.owner_turn_index <= owner_turn_index(state, expiry.player_id):
                raise ValueError('Expired numeric owner buff at action boundary')
            expiry = enchantment.control_return_expiry
            if expiry is not None:
                previous = next((v for v in reversed(state.owner_turn_history) if v.player_id == expiry.player_id), None)
                index = previous.owner_index if previous is not None else 0
                if expiry.owner_turn_index < index or expiry.owner_turn_index == index and previous.closed:
                    raise ValueError('Expired owner-end control at action boundary')
        for ability in entity.abilities:
            expiry = ability.keyword_expiry
            if expiry is not None:
                previous = next((v for v in reversed(state.owner_turn_history) if v.player_id == expiry.player_id), None)
                index = previous.owner_index if previous is not None else 0
                if (expiry.owner_turn_index < index or expiry.owner_turn_index == index and
                        (expiry.boundary == 'turn_started' or previous.closed)):
                    raise ValueError('Expired timed keyword at action boundary')
            expiry=ability.attack_policy_expiry
            if expiry is not None:
                previous=next((v for v in reversed(state.owner_turn_history)if v.player_id==expiry.player_id),None)
                index=previous.owner_index if previous is not None else 0
                if expiry.owner_turn_index<index or expiry.owner_turn_index==index and previous.closed:
                    raise ValueError('Expired timed attack restriction at action boundary')


def public_durations(entity):
    return [dict(keyword=a.keyword.value, boundary=a.keyword_expiry.boundary,
                 player_id=a.keyword_expiry.player_id, owner_turn_index=a.keyword_expiry.owner_turn_index)
            for a in entity.abilities if a.keyword_expiry is not None and not a.consumed]
