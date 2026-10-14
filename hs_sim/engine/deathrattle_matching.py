"""Pure Deathrattle matching against the original physical recipient face.

Natural groups use their frozen DeathRecord; effect groups capture the live
carrier at acceptance. The payload declaration and its grant donor are separate
identities. Compact history never reads a later carrier face or live witnesses.
"""
from .model import (AbilityInstance, CardDefinition, CardType, DeathRecord,
                    DeathrattleCapture, DeathrattleRecipient,
                    DeathrattleRecipientMetadataFilter, DeathrattleRepeatMatchSpec,
                    DeathrattleRepeatSpec, GameState, RepeatSourceEligibility, Zone)
from .pools import PoolQuery, matches_metadata


def validate_recipient(state, registry, recipient, *, death=None):
    """Validate compact provenance without rejudging a later entity's state."""
    if type(state) is not GameState or type(recipient) is not DeathrattleRecipient:
        raise ValueError('Deathrattle matching requires an accepted physical recipient')
    recipient.__post_init__()
    if recipient.carrier_id not in state.entities:
        raise ValueError('Accepted Deathrattle recipient lost its physical entity')
    definition = registry.card(recipient.card_id)
    if definition.kind != recipient.kind:
        raise ValueError('Accepted Deathrattle face differs from its physical kind')
    if death is not None:
        if type(death) is not DeathRecord:
            raise ValueError('Natural Deathrattle matching requires a frozen DeathRecord')
        death.__post_init__()
        if ([record for record in state.death_history if record.id == death.id] != [death] or
                (death.entity_id, death.card_id) != (recipient.carrier_id, recipient.card_id) or
                death.turn > state.turn):
            raise ValueError('Accepted Deathrattle recipient differs from its original death record')
        expected_zone = Zone.HERO if recipient.kind == CardType.HERO else Zone.WEAPON if recipient.kind == CardType.WEAPON else Zone.BOARD
        if death.zone != expected_zone:
            raise ValueError('Accepted Deathrattle kind differs from its frozen death zone')
        # Validate every frozen declaration, including friendly, false and
        # consumed sources. A physical receiver is not automatically a legal
        # repeat source, and no static operand may hide an unknown profile.
        from .repeat_source_conditions import validate_source_declaration
        for ability in death.abilities:
            if ability.kind == 'deathrattle_repeat':
                if recipient.kind != CardType.MINION:
                    raise ValueError('Frozen Deathrattle repeat source requires a minion carrier')
                validate_source_declaration(registry, ability.deathrattle_repeat)
    return definition


def capture_recipient_from_state(state, registry, carrier_id, *, death=None):
    """Capture the live effect face or the natural death's frozen face once."""
    if type(state) is not GameState or type(carrier_id) is not int or carrier_id < 1:
        raise ValueError('Deathrattle capture requires a physical carrier ID')
    entity = state.entities.get(carrier_id)
    if entity is None:
        raise ValueError('Deathrattle capture lost its physical carrier')
    if death is None:
        recipient = DeathrattleRecipient(entity.id, entity.card_id, entity.kind)
    else:
        if type(death) is not DeathRecord or death.entity_id != carrier_id:
            raise ValueError('Natural Deathrattle capture requires this carrier\'s death record')
        recipient = DeathrattleRecipient(carrier_id, death.card_id, registry.card(death.card_id).kind)
    validate_recipient(state, registry, recipient, death=death)
    return recipient


def recipient_from_capture(state, registry, capture):
    """Reconstruct the pure operand from the existing durable capture fields."""
    if type(state) is not GameState or type(capture) is not DeathrattleCapture:
        raise ValueError('Deathrattle recipient requires its durable capture')
    capture.__post_init__()
    if capture.turn > state.turn or capture.action > state.action_number:
        raise ValueError('Accepted Deathrattle recipient has future chronology')
    recipient = DeathrattleRecipient(capture.carrier_id, capture.card_id, capture.kind)
    death = None
    if capture.death_id is not None:
        death = next((record for record in state.death_history if record.id == capture.death_id), None)
        if (death is None or (death.controller, death.turn) != (capture.player_id, capture.turn) or
                capture.ability not in death.abilities):
            raise ValueError('Deathrattle capture differs from its original death record')
    validate_recipient(state, registry, recipient, death=death)
    return recipient


def deathrattle_repeat_recipient_matches(spec, *, recipient, recipient_definition,
                                       payload_ability, source_carrier_id=None):
    """Intersect kind, physical scope, payload origin and printed-face tribes."""
    if type(spec) is not DeathrattleRepeatSpec or type(recipient) is not DeathrattleRecipient:
        raise ValueError('Deathrattle matching requires its declaration and accepted recipient')
    spec.__post_init__()
    recipient.__post_init__()
    if (type(recipient_definition) is not CardDefinition or
            recipient_definition.id != recipient.card_id or recipient_definition.kind != recipient.kind):
        raise ValueError('Deathrattle matching received another recipient definition')
    if type(payload_ability) is not AbilityInstance:
        raise ValueError('Deathrattle matching requires its accepted payload ability')
    payload_ability.__post_init__()
    if payload_ability.kind != 'deathrattle' or payload_ability.consumed:
        raise ValueError('Deathrattle matching requires an unconsumed Deathrattle payload')
    if source_carrier_id is not None and (type(source_carrier_id) is not int or source_carrier_id < 1):
        raise ValueError('Deathrattle self matching requires a physical source carrier')
    if spec.scope == 'self' and source_carrier_id is None:
        raise ValueError('Deathrattle self matching requires a physical source carrier')
    metadata = spec.match.recipient_metadata if spec.match is not None else None
    tribe_matches = True
    if metadata is not None and metadata.tribes_any:
        # Non-minion receivers have no tribe interpretation. For minions,
        # required metadata is checked even when scope/kind/origin is false.
        tribe_matches = recipient.kind == CardType.MINION and matches_metadata(
            PoolQuery(tribes_any=metadata.tribes_any), card_id=recipient_definition.id,
            kind=recipient_definition.kind, cost=recipient_definition.cost,
            meta=recipient_definition.metadata, spell_school=recipient_definition.spell_school,
            keywords=recipient_definition.keywords)
    return (recipient.kind in spec.kinds and payload_ability.origin in spec.origins and
            (spec.scope == 'friendly' or source_carrier_id == recipient.carrier_id) and tribe_matches)


def deathrattle_match_to_dict(match):
    if match is None:
        return None
    if type(match) is not DeathrattleRepeatMatchSpec:
        raise ValueError('Deathrattle matching requires DeathrattleRepeatMatchSpec')
    match.__post_init__()
    metadata, condition = match.recipient_metadata, match.source_eligibility
    return {'recipient_metadata': None if metadata is None else {
        'basis': metadata.basis, 'tribes_any': list(metadata.tribes_any)},
        'source_eligibility': None if condition is None else {
            'profile_id': condition.profile_id, 'tribes_any': list(condition.tribes_any),
            'exclude_carrier': condition.exclude_carrier}}


def _recipient_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'basis', 'tribes_any'}:
        raise ValueError('Deathrattle recipient metadata requires exactly its declared fields')
    tribes = value['tribes_any']
    if type(tribes) is not list or any(type(tribe) is not str for tribe in tribes):
        raise ValueError('Deathrattle recipient tribes require a JSON array of strings')
    return DeathrattleRecipientMetadataFilter(value['basis'], tuple(tribes))


def deathrattle_match_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'recipient_metadata', 'source_eligibility'}:
        raise ValueError('Deathrattle matching requires exactly its declared fields')
    condition = value['source_eligibility']
    if condition is not None:
        if type(condition) is not dict or set(condition) != {'profile_id', 'tribes_any', 'exclude_carrier'}:
            raise ValueError('Deathrattle source eligibility requires exactly its declared fields')
        tribes = condition['tribes_any']
        if type(tribes) is not list or any(type(tribe) is not str for tribe in tribes):
            raise ValueError('Deathrattle witness tribes require a JSON array of strings')
        condition = RepeatSourceEligibility(condition['profile_id'], tuple(tribes), condition['exclude_carrier'])
    return DeathrattleRepeatMatchSpec(_recipient_from_dict(value['recipient_metadata']), condition)
