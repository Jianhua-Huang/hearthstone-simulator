"""strict private wire and complete EndTurn source declarations.

EndTurnSubject already identifies the accepted recipient. Matching adds only
the physical repeat source condition, with the existing all/minion scope.
"""
from .model import (CardType, EndTurnRepeatMatchSpec, EndTurnRepeatSpec,
                    GameState, RepeatSourceEligibility)


def end_turn_match_to_dict(match):
    if match is None:
        return None
    if type(match) is not EndTurnRepeatMatchSpec:
        raise ValueError('End-turn matching requires EndTurnRepeatMatchSpec')
    match.__post_init__()
    condition = match.source_eligibility
    return {'source_eligibility': None if condition is None else {
        'profile_id': condition.profile_id, 'tribes_any': list(condition.tribes_any),
        'exclude_carrier': condition.exclude_carrier}}


def end_turn_match_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'source_eligibility'}:
        raise ValueError('End-turn matching requires exactly its declared fields')
    condition = value['source_eligibility']
    if condition is not None:
        if type(condition) is not dict or set(condition) != {'profile_id', 'tribes_any', 'exclude_carrier'}:
            raise ValueError('End-turn source eligibility requires exactly its declared fields')
        tribes = condition['tribes_any']
        if type(tribes) is not list or any(type(tribe) is not str for tribe in tribes):
            raise ValueError('End-turn witness tribes require a JSON array of strings')
        condition = RepeatSourceEligibility(condition['profile_id'], tuple(tribes), condition['exclude_carrier'])
    return EndTurnRepeatMatchSpec(condition)


def end_turn_spec_to_dict(spec):
    if type(spec) is not EndTurnRepeatSpec:
        raise ValueError('Expected end-turn repeat specification')
    spec.__post_init__()
    return {'repetitions': spec.repetitions, 'scope': spec.scope,
            'match': end_turn_match_to_dict(spec.match)}


def end_turn_spec_from_dict(value):
    if type(value) is not dict or set(value) != {'repetitions', 'scope', 'match'}:
        raise ValueError('EndTurnRepeatSpec requires exactly its declared fields')
    return EndTurnRepeatSpec(value['repetitions'], value['scope'],
                             end_turn_match_from_dict(value['match']))


def validated_source_inventory(state, registry):
    """Validate all declarations, including false/offboard/frozen sources.

    The returned catalogue contains current raw attachments only. Frozen
    declarations are provenance, never live contributors or frozen witnesses.
    """
    from .registry import Registry
    from .repeat_provenance import checked_live_attachments
    from .repeat_source_conditions import validate_source_declaration
    if type(state) is not GameState or not isinstance(registry, Registry):
        raise ValueError('End-turn source inventory requires GameState and Registry')
    inventory = checked_live_attachments(state)
    for family, carrier, value in inventory.values():
        if family == 'ability' and value.kind == 'end_turn_repeat':
            value.__post_init__()
            validate_source_declaration(registry, value.end_turn_repeat)
            entity = state.entities[carrier]
            if entity.kind != CardType.MINION or registry.card(entity.card_id).kind != CardType.MINION:
                raise ValueError('End-turn repeat sources require physical minion carriers')
        elif family == 'player_effects':
            value.__post_init__()
            declaration = registry.player_effect(value.spec_id)
            declaration.__post_init__()
            for spec in declaration.end_turn_repeats:
                validate_source_declaration(registry, spec, allow_source=False)
    for death in state.death_history:
        for ability in death.abilities:
            if ability.kind != 'end_turn_repeat':
                continue
            death.__post_init__()
            ability.__post_init__()
            validate_source_declaration(registry, ability.end_turn_repeat)
            if registry.card(death.card_id).kind != CardType.MINION:
                raise ValueError('Frozen end-turn repeat source requires a minion carrier')
    return inventory
