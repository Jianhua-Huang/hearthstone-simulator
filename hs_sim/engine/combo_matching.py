"""Pure Combo matching against the physical recipient's accepted face.

The submitted card, ability declaration card and grant donor are distinct from
this operand. Live source conditions are evaluated separately at the original
family window; compact history never repeats those live queries.
"""
from .model import (ComboRecipient, ComboRecipientMetadataFilter,
                    ComboRepeatMatchSpec, ComboRepeatSpec, CardDefinition,
                    CardType, GameState, RepeatSourceEligibility)
from .pools import PoolQuery, matches_metadata


def validate_recipient(state, registry, recipient, play=None):
    """Validate compact provenance without consulting a later entity's face."""
    if type(state) is not GameState or type(recipient) is not ComboRecipient:
        raise ValueError('Combo matching requires an accepted physical recipient')
    recipient.__post_init__()
    if recipient.carrier_id not in state.entities:
        raise ValueError('Accepted Combo recipient lost its physical entity')
    definition = registry.card(recipient.card_id)
    if definition.kind != recipient.kind:
        raise ValueError('Accepted Combo face differs from its physical kind')
    if play is not None and (recipient.carrier_id != play.source_id or recipient.kind != play.kind):
        raise ValueError('Accepted Combo recipient differs from its paid play')
    return definition


def capture_recipient(state, registry, carrier_id):
    """Capture once when a physical hand payload reaches its acceptance window."""
    if type(state) is not GameState or type(carrier_id) is not int or carrier_id < 1:
        raise ValueError('Combo capture requires a physical carrier ID')
    entity = state.entities.get(carrier_id)
    if entity is None:
        raise ValueError('Combo capture lost its physical carrier')
    recipient = ComboRecipient(entity.id, entity.card_id, entity.kind)
    validate_recipient(state, registry, recipient)
    return recipient


def combo_repeat_recipient_matches(spec, *, recipient, recipient_definition, carrier_id=None):
    """Intersect kind, physical scope and accepted-face printed metadata."""
    if type(spec) is not ComboRepeatSpec or type(recipient) is not ComboRecipient:
        raise ValueError('Combo matching requires its declaration and accepted recipient')
    spec.__post_init__(); recipient.__post_init__()
    if (type(recipient_definition) is not CardDefinition or
            recipient_definition.id != recipient.card_id or recipient_definition.kind != recipient.kind):
        raise ValueError('Combo matching received another recipient definition')
    if carrier_id is not None and (type(carrier_id) is not int or carrier_id < 1):
        raise ValueError('Combo self matching requires a physical source carrier')
    if spec.scope == 'self' and carrier_id is None:
        raise ValueError('Combo self matching requires a physical source carrier')
    metadata = spec.match.recipient_metadata if spec.match is not None else None
    tribe_matches = True
    if metadata is not None and metadata.tribes_any:
        # Tribes have no default meaning for weapon or hero recipients. For a
        # minion, evaluate required metadata even if another operand is false.
        tribe_matches = recipient.kind == CardType.MINION and matches_metadata(
            PoolQuery(tribes_any=metadata.tribes_any), card_id=recipient_definition.id,
            kind=recipient_definition.kind, cost=recipient_definition.cost,
            meta=recipient_definition.metadata, spell_school=recipient_definition.spell_school,
            keywords=recipient_definition.keywords)
    return (recipient.kind in spec.kinds and
            (spec.scope == 'friendly' or carrier_id == recipient.carrier_id) and tribe_matches)


def combo_match_to_dict(match):
    if match is None:
        return None
    if type(match) is not ComboRepeatMatchSpec:
        raise ValueError('Combo matching requires ComboRepeatMatchSpec')
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
        raise ValueError('Combo recipient metadata requires exactly its declared fields')
    tribes = value['tribes_any']
    if type(tribes) is not list or any(type(t) is not str for t in tribes):
        raise ValueError('Combo recipient tribes require a JSON array of strings')
    return ComboRecipientMetadataFilter(value['basis'], tuple(tribes))


def combo_match_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'recipient_metadata', 'source_eligibility'}:
        raise ValueError('Combo matching requires exactly its declared fields')
    condition = value['source_eligibility']
    if condition is not None:
        if type(condition) is not dict or set(condition) != {'profile_id', 'tribes_any', 'exclude_carrier'}:
            raise ValueError('Combo source eligibility requires exactly its declared fields')
        tribes = condition['tribes_any']
        if type(tribes) is not list or any(type(t) is not str for t in tribes):
            raise ValueError('Combo witness tribes require a JSON array of strings')
        condition = RepeatSourceEligibility(condition['profile_id'], tuple(tribes), condition['exclude_carrier'])
    return ComboRepeatMatchSpec(_recipient_from_dict(value['recipient_metadata']), condition)


def combo_match_public_to_dict(match):
    """Only detached recipient rule parameters are public player policy facts."""
    value = combo_match_to_dict(match)
    if value is None:
        return None
    if value['source_eligibility'] is not None:
        raise ValueError('Player Combo policies have no physical board source condition')
    return {'recipient_metadata': value['recipient_metadata']}


def combo_match_public_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'recipient_metadata'}:
        raise ValueError('Public Combo matching requires only recipient metadata')
    return ComboRepeatMatchSpec(_recipient_from_dict(value['recipient_metadata']))
