"""Hand splitting and adjacency settlement; provisional boundaries are in R083.

Printed Shatter is consumed on recombination. Existing attachment state therefore
distinguishes a combined card from a fresh base copy without an out-of-band flag.
"""
from .hand_capacity import hand_capacity
from dataclasses import replace

from .lifecycle import attachment_id, consume_keyword, refresh_entity
from .model import CardType, Keyword, ShatterSpec, Zone


def validate_definitions(registry):
    fragments = {}
    for root in registry.cards.values():
        if (Keyword.SHATTER in root.keywords) != (root.shatter is not None):
            raise ValueError('Shatter requires its keyword and explicit fragment declaration')
        if root.shatter is None:
            continue
        if type(root.shatter) is not ShatterSpec or root.kind != CardType.SPELL or not root.hand_playable:
            raise ValueError('Shatter requires a physical spell and ShatterSpec')
        root.shatter.__post_init__()
        if root.choose_one or root.secret or root.quest or root.ongoing_effect_id or root.hand_progress:
            raise ValueError('Composite Shatter spell lifecycles are not supported')
        for card_id in (root.shatter.left_card_id, root.shatter.right_card_id):
            part = registry.card(card_id)
            if (card_id in fragments or part.kind != CardType.SPELL or not part.hand_playable or
                    part.shatter is not None or Keyword.SHATTERED not in part.keywords or
                    part.choose_one or part.secret or part.quest or part.ongoing_effect_id or part.hand_progress):
                raise ValueError('Fragments must be distinct ordinary spells belonging to one Shatter family')
            fragments[card_id] = root.id
    if any((Keyword.SHATTERED in c.keywords) != (c.id in fragments) for c in registry.cards.values()):
        raise ValueError('Shattered markers require a registered parent family')


def families(registry):
    return {part: root for root in registry.cards.values() if root.shatter is not None
            for part in (root.shatter.left_card_id, root.shatter.right_card_id)}


def suspended(state):
    # Mulligan choices refer to the offered physical cards until opening finishes.
    return state.opening is not None and state.opening.stage != 'complete'


def next_change(state, registry, mapping):
    for player in state.players.values():
        for entity_id in player.hand:
            entity = state.entities[entity_id]
            if Keyword.SHATTER in entity.keywords:
                root = registry.card(entity.card_id)
                if root.shatter is None:
                    raise ValueError('Active Shatter has no fragment declaration')
                return 'split', player, entity, root
        for a, b in zip(player.hand, player.hand[1:]):
            left, right = state.entities[a], state.entities[b]
            root = mapping.get(left.card_id)
            if (root is not None and mapping.get(right.card_id) == root and left.card_id != right.card_id and
                    Keyword.SHATTERED in left.keywords and Keyword.SHATTERED in right.keywords):
                return 'merge', player, (left, right), root
    return None


def inherit(r, source, destination):
    # Keep each new face's printed abilities; only instance modifications carry.
    destination.origin_entity_id = source.id
    destination.copy_origin = source.copy_origin
    destination.hand_lifetime = source.hand_lifetime
    destination.enchantments = [replace(e, id=attachment_id(r.state)) for e in source.enchantments]
    destination.abilities.extend(replace(a, id=attachment_id(r.state)) for a in source.abilities if a.origin != 'printed')
    refresh_entity(destination)


def settle_hands(r, *, initial=False, opening_ready=False):
    if suspended(r.state) and not opening_ready:
        return
    from .held_battlecry_forms import synchronize as synchronize_held_battlecry_forms
    synchronize_held_battlecry_forms(r)
    from .hand_combinations import settle_hands as settle_combinations
    settle_combinations(r, initial=initial)
    mapping = families(r.registry)
    if not mapping:
        return
    while change := next_change(r.state, r.registry, mapping):
        r.charge()
        kind, player, source, root = change
        if kind == 'split':
            spec = root.shatter
            r.move(source, Zone.GRAVEYARD)
            pieces = []
            for card_id, position in ((spec.left_card_id, 0), (spec.right_card_id, None)):
                zone = Zone.HAND if len(player.hand) < hand_capacity(player, r.rules) else Zone.GRAVEYARD
                part = r.create_entity(player.id, card_id, zone, position,
                                       hand_entry_reason='scenario' if initial else 'shatter')
                inherit(r, source, part)
                pieces.append(part.id)
                if zone == Zone.GRAVEYARD:
                    from .zones import emit_burn
                    emit_burn(r,part,profile='created_overflow',source_id=source.id,reason='shatter')
            r.emit('card_shattered', source_id=source.id, target_id=pieces[0], player_id=player.id,
                   fragment_ids=tuple(pieces))
        else:
            first, second = source
            position = player.hand.index(first.id)
            # R083: the declared left fragment supplies retained modifications,
            # even after hand reordering; do not double a shared initial discount.
            primary = first if first.card_id == root.shatter.left_card_id else second
            r.move(first, Zone.GRAVEYARD)
            r.move(second, Zone.GRAVEYARD)
            combined = r.create_entity(player.id, root.id, Zone.HAND, position,
                                       hand_entry_reason='scenario' if initial else 'recombine')
            inherit(r, primary, combined)
            consume_keyword(combined, Keyword.SHATTER)
            r.emit('cards_recombined', source_id=first.id, target_id=combined.id, player_id=player.id,
                   fragment_ids=(first.id, second.id))


def validate_boundary(game):
    if not suspended(game._state) and next_change(game._state, game.registry, families(game.registry)) is not None:
        raise ValueError('Unsettled Shatter hand at a stable boundary')
    from .hand_combinations import next_pair
    if not suspended(game._state) and next_pair(game._state, game.registry) is not None:
        raise ValueError('Unsettled native minion pair at a stable boundary')
