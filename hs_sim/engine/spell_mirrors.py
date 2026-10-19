"""One native held spell follows real own casts, copying current material."""
from copy import deepcopy
from dataclasses import replace

from .model import AbilityInstance, CardType, SpellMirrorBinding, Zone

ACQUISITIONS = frozenset(('card_created', 'card_added_to_hand', 'card_moved_to_hand',
    'card_drawn', 'card_returned', 'stored_card_transformed'))


def source(entity):
    rows = [a for a in entity.abilities if a.kind == 'spell_mirror']
    if len(rows) > 1:
        raise ValueError('A native spell mirror has one original source')
    return rows[0] if rows else None


def validate_declaration(registry, card_id):
    card = registry.card(card_id)
    if card.kind != CardType.SPELL or card.manual_playable or not card.hand_playable:
        raise ValueError('Spell mirror requires its originally unplayable native spell')


def install(state, registry, entity):
    if (entity.zone == Zone.HAND and entity.card_id in registry.spell_mirror_ids and
            not entity.silenced and source(entity) is None):
        from .lifecycle import attachment_id
        validate_declaration(registry, entity.card_id)
        entity.abilities.append(AbilityInstance(attachment_id(state), 'spell_mirror',
            source_id=entity.id, origin='printed', spell_mirror=SpellMirrorBinding(entity.card_id)))


def synchronize(r, event):
    if not r.registry.spell_mirror_ids:
        return
    if event.kind in ACQUISITIONS:
        target = r.state.entities.get(event.target_id)
        if target is not None:
            install(r.state, r.registry, target)
        return  # Acquisition does not replay an earlier cast, including its own draw.
    if event.kind != 'spell_cast_accepted':
        return
    from .spell_casts import accepted_cast
    record = accepted_cast(r.state, event)
    held = [(r.state.entities[i], source(r.state.entities[i]))
            for i in tuple(r.state.players[record.player_id].hand)]
    held = [(entity, ability) for entity, ability in held if ability is not None]
    if not held:
        return
    original = deepcopy(r.state.entities[record.source_id])
    if original.kind != CardType.SPELL or original.card_id != record.card_id:
        raise ValueError('Spell mirror lost its actual accepted physical spell face')
    from .cross_zone import reset_stored_entity, announce_stored_transform
    from .zones import copy_current_stored_state
    changed = []
    for entity, ability in held:
        validate_entity(r.state, r.registry, entity)
        old = entity.card_id
        reset_stored_entity(r, entity, r.registry.card(record.card_id))
        copy_current_stored_state(r.state, original, entity)
        entity.abilities = [a for a in entity.abilities if a.kind != 'spell_mirror']
        entity.abilities.append(replace(ability, source_id=entity.id,
            spell_mirror=SpellMirrorBinding(ability.spell_mirror.declaring_card_id, record.id)))
        changed.append((entity, old))
    # Finish every current physical copy before publishing the first private notice.
    for entity, old in changed:
        announce_stored_transform(r, entity, old, source_id=entity.id)


def validate_entity(state, registry, entity):
    ability = source(entity)
    if ability is None:
        return
    ability.__post_init__()
    binding = ability.spell_mirror
    if (entity.zone != Zone.HAND or entity.kind != CardType.SPELL or entity.silenced or
            ability.source_id != entity.id or binding.declaring_card_id not in registry.spell_mirror_ids):
        raise ValueError('Spell mirror lost its native physical hand source')
    validate_declaration(registry, binding.declaring_card_id)
    if binding.cast_id is None:
        if entity.card_id != binding.declaring_card_id:
            raise ValueError('Unbound spell mirror borrowed a different face')
    else:
        from .spell_casts import cast_record
        record = cast_record(state, binding.cast_id)
        if record.card_id != entity.card_id or not record.payload_started or record.failure is not None:
            raise ValueError('Spell mirror differs from its original accepted cast')


def validate_game(game):
    if not game.registry.spell_mirror_ids:
        return
    for entity in game._state.entities.values():
        validate_entity(game._state, game.registry, entity)
        if (entity.zone == Zone.HAND and entity.card_id in game.registry.spell_mirror_ids and
                not entity.silenced and source(entity) is None):
            raise ValueError('Native held spell lost its original mirror binding')
