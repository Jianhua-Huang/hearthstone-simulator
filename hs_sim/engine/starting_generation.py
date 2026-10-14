"""31.0 constructed generation eligibility from immutable starting deck facts.

The two real group inventories below are a pinned local survey, not an assertion
that M0's complete current formal pool is known. Other pool exclusions still
apply. Eligibility never depends on whether a card has an executable adapter.
"""
from .effects import _player
from .errors import ResolutionError
from .model import Keyword


VERSION = 'starting-generation-v1'
CTHUN = frozenset((
    'OG_096', 'OG_131', 'OG_162', 'OG_188', 'OG_255', 'OG_280', 'OG_281',
    'OG_282', 'OG_283', 'OG_284', 'OG_286', 'OG_293', 'OG_301', 'OG_302',
    'OG_303', 'OG_321', 'OG_334', 'OG_339', 'WON_010', 'WON_075', 'WON_111',
    'WON_124', 'WON_125', 'WON_127', 'WON_131', 'WON_134', 'WON_135',
    'WON_144', 'WON_304', 'WON_313', 'WON_322'))
GALAKROND = frozenset((
    'DRG_019', 'DRG_021', 'DRG_027', 'DRG_030', 'DRG_050', 'DRG_099',
    'DRG_202', 'DRG_203', 'DRG_217', 'DRG_218', 'DRG_242', 'DRG_246',
    'DRG_247', 'DRG_248', 'DRG_249', 'DRG_250', 'DRG_300', 'DRG_303',
    'DRG_600', 'DRG_600t2', 'DRG_600t3', 'DRG_610', 'DRG_610t2', 'DRG_610t3',
    'DRG_620', 'DRG_620t2', 'DRG_620t3', 'DRG_650', 'DRG_650t2', 'DRG_650t3',
    'DRG_660', 'DRG_660t2', 'DRG_660t3'))


def group_for(registry, card_id, keywords=None):
    if card_id in CTHUN:
        return 'cthun'
    if card_id in GALAKROND:
        return 'galakrond'
    if registry.cthun_profile is not None and card_id in registry.cthun_profile.card_ids:
        return 'cthun'
    if registry.invoke_profile is not None and registry.invoke_profile.family(card_id) is not None:
        return 'galakrond'
    if keywords is None:
        if card_id in registry.pool_cards:
            keywords = registry.pool_card(card_id).keywords
        elif card_id in registry.cards:
            keywords = registry.card(card_id).keywords
        else:
            keywords = ()
    return 'galakrond' if Keyword.INVOKE in keywords else None


def eligible(registry, context, player_id, card_id, keywords=()):
    group = group_for(registry, card_id, keywords)
    if group is None:
        return True
    if context.starting_decks is None or player_id is None:
        raise ResolutionError('Restricted generation requires explicit starting decks and the recipient player')
    _player(player_id)
    return any(group_for(registry, cid) == group for cid in context.starting_decks[player_id - 1])


def validate_context(context, state):
    context.__post_init__()
    if context.starting_decks is not None and context.starting_decks != tuple(
            state.players[p].original_deck for p in (1, 2)):
        raise ValueError('Generation eligibility differs from the immutable original decks')
