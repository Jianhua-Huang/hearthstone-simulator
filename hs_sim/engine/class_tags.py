"""Decode client class tags, independently of executable coverage or legality.

EntityBase.GetClasses in the pinned local build gives MULTIPLE_CLASSES precedence;
its least significant bit is TAG_CLASS 1. Unsupported class bits fail explicitly.
"""
from types import MappingProxyType
from hs_sim.targets import TargetValidationError
from .model import CardClass

CLASS_TAGS = MappingProxyType({
    1: CardClass.DEATH_KNIGHT, 2: CardClass.DRUID, 3: CardClass.HUNTER,
    4: CardClass.MAGE, 5: CardClass.PALADIN, 6: CardClass.PRIEST,
    7: CardClass.ROGUE, 8: CardClass.SHAMAN, 9: CardClass.WARLOCK,
    10: CardClass.WARRIOR, 11: CardClass.DREAM, 12: CardClass.NEUTRAL, 14: CardClass.DEMON_HUNTER,
})
KNOWN_MASK = sum(1 << (value - 1) for value in CLASS_TAGS)


def classes_from_tags(tags):
    if type(tags) is not dict:
        raise TargetValidationError('Expected raw class tags')
    mask = tags.get('MULTIPLE_CLASSES', 0)
    if type(mask) is not int or not 0 <= mask < 2**32:
        raise TargetValidationError('Invalid unsigned class mask')
    if mask:
        if mask & ~KNOWN_MASK:
            raise TargetValidationError('Unsupported class mask bits')
        result = tuple(cls for value, cls in CLASS_TAGS.items() if mask & (1 << (value - 1)))
        if len(result) > 1 and CardClass.NEUTRAL in result:
            raise TargetValidationError('Neutral cannot share a playable class mask')
        return result
    primary = tags.get('CLASS')
    if type(primary) is not int or primary not in CLASS_TAGS:
        raise TargetValidationError('Unknown primary class metadata')
    return (CLASS_TAGS[primary],)
