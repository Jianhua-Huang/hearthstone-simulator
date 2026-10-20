"""The reviewed native Rafaam family, including the tagged Sheep and their physical-play price.

This is a finite source family, never a name/prefix/tribe inference. The full
class-price fact retains all original paid faces, not a separate mutable count.
"""
ROOT = 'TIME_005'
MEMBERS = ('TIME_005t1','TIME_005t2','TIME_005t8','TIME_005t3','TIME_005t4',
           'TIME_005t6','TIME_005t5','TIME_005t7','TIME_005t9')
CONSTRUCTED = (ROOT, *MEMBERS)
FAMILY = (*CONSTRUCTED, 'TIME_005t9t')
GIANT = 'TIME_005t7'
SHEEP = 'TIME_005t9t'
PROFILE = 'cost.player-played-rafaam-v1'


def validate_registry(registry):
    from .fabled_decks import FabledSpec
    from .deck_size_rules import DeckSizeRule
    from .model import CardType
    giant = registry.cards.get(GIANT)
    if giant is None or giant.player_played_class_cost is None or giant.player_played_class_cost.profile_id != PROFILE:
        return
    if (registry.fabled.get(ROOT) != FabledSpec(ROOT,MEMBERS) or
            registry.deck_size_rules.get(ROOT) != DeckSizeRule(ROOT,40) or
            any(registry.card(cid).kind != CardType.MINION for cid in FAMILY)):
        raise ValueError('Rafaam price requires its complete original ten-face Fabled+ bundle')


def played_ids(state, registry, player_id):
    from .play_history import played_cards
    validate_registry(registry)
    return tuple(row.id for row in played_cards(state,player_id)
                 if row.played_face.card_id in FAMILY)
