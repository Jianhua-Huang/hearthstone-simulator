"""Strict private wire for sustained hero-power repeat source conditions.

The receiver is already identified by HeroPowerRecord. This family has no
recipient tribe or physical-self interpretation; matching concerns its source.
"""
from .model import HeroPowerRepeatMatchSpec, RepeatSourceEligibility


def hero_power_match_to_dict(match):
    if match is None:
        return None
    if type(match) is not HeroPowerRepeatMatchSpec:
        raise ValueError('Hero power matching requires HeroPowerRepeatMatchSpec')
    match.__post_init__()
    condition = match.source_eligibility
    return {'source_eligibility': None if condition is None else {
        'profile_id': condition.profile_id, 'tribes_any': list(condition.tribes_any),
        'exclude_carrier': condition.exclude_carrier}}


def hero_power_match_from_dict(value):
    if value is None:
        return None
    if type(value) is not dict or set(value) != {'source_eligibility'}:
        raise ValueError('Hero power matching requires exactly its declared fields')
    condition = value['source_eligibility']
    if condition is not None:
        if type(condition) is not dict or set(condition) != {'profile_id', 'tribes_any', 'exclude_carrier'}:
            raise ValueError('Hero power source eligibility requires exactly its declared fields')
        tribes = condition['tribes_any']
        if type(tribes) is not list or any(type(tribe) is not str for tribe in tribes):
            raise ValueError('Hero power witness tribes require a JSON array of strings')
        condition = RepeatSourceEligibility(condition['profile_id'], tuple(tribes), condition['exclude_carrier'])
    return HeroPowerRepeatMatchSpec(condition)
