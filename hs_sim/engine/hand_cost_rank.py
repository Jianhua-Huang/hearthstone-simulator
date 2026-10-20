"""Finite native hand-rank conditions over complete original physical quotes."""
from dataclasses import dataclass
from .costs import capture_cost_input, quote_input
from .model import CardType, HandCostRankFact, Zone

PROFILE = 'hand.highest-current-cost-before-submit-v1'


@dataclass(frozen=True)
class HandCostRankProfile:
    card_id: str
    profile_id: str = PROFILE

    def __post_init__(self):
        if type(self.card_id) is not str or not self.card_id.strip() or self.profile_id != PROFILE:
            raise ValueError('Unknown native hand-rank declaration')


def validate_profile(registry, profile):
    if type(profile) is not HandCostRankProfile: raise ValueError('Expected HandCostRankProfile')
    profile.__post_init__(); card = registry.card(profile.card_id)
    if card.kind != CardType.SPELL or not card.hand_playable or card.on_play is None:
        raise ValueError('Hand-cost rank requires its original physical spell body')


def capture(state, registry, source, *, player_id=None):
    profile = registry.hand_cost_rank_profiles.get(source.card_id)
    if profile is None: return None
    validate_profile(registry, profile)
    player_id = source.controller if player_id is None else player_id
    quotes = []
    for eid in state.players[player_id].hand:
        entity = state.entities[eid]
        if entity.zone != Zone.HAND or entity.controller != player_id:
            raise ValueError('Hand rank lost its complete original physical hand')
        quotes.append(quote_input(state, registry, capture_cost_input(entity)))
    return HandCostRankFact(profile.profile_id, source.id, source.card_id, player_id,
        source.controller, source.zone, state.turn, state.action_number, state.next_entity_id, tuple(quotes))


def validate_fact(state, registry, fact):
    if type(fact) is not HandCostRankFact: raise ValueError('Expected original hand-cost rank')
    fact.__post_init__(); profile = registry.hand_cost_rank_profiles.get(fact.card_id)
    if profile is None or profile.profile_id != fact.profile_id:
        raise ValueError('Hand rank lost its original registered declaration')
    if (fact.turn > state.turn or fact.action > state.action_number or
            fact.next_entity_id > state.next_entity_id or fact.source_id not in state.entities):
        raise ValueError('Hand rank borrowed a future physical boundary')
    for quote in fact.quotes:
        value = quote.quote_input
        if value.source_id not in state.entities or registry.card(value.card_id).kind != value.kind:
            raise ValueError('Hand rank borrowed an unknown original physical face')
        from .repeat_matching import validate_cost_quote_fact
        from .intrinsic_costs import validate_intrinsic_history_prefix
        validate_cost_quote_fact(registry, quote)
        validate_intrinsic_history_prefix(quote.intrinsic, state, registry)
        if any(c.id >= state.next_attachment_id for c in quote.contributions):
            raise ValueError('Hand rank borrowed an unallocated price contribution')


def validate_play(state, registry, play):
    fact = play.hand_cost_rank
    if (play.card_id in registry.hand_cost_rank_profiles) != (fact is not None):
        raise ValueError('Hand play lost its original hand-rank facts')
    if fact is None: return
    validate_fact(state, registry, fact); ids = tuple(q.quote_input.source_id for q in fact.quotes)
    if ((fact.source_id, fact.card_id, fact.player_id, fact.turn, fact.action) !=
            (play.source_id, play.card_id, play.player_id, play.turn, play.action) or
            not fact.source_held or len(ids) != play.hand_size or ids[play.hand_index] != play.source_id):
        raise ValueError('Hand rank differs from its complete original submission')
    if (play.submitted_cost is not None and play.submitted_cost.quote_origin == 'current_hand' and
            fact.source_quote != play.submitted_cost.quote):
        raise ValueError('Hand rank changed its original submitted source quote')


def validate_cast(state, registry, cast):
    fact = cast.hand_cost_rank
    if (cast.card_id in registry.hand_cost_rank_profiles) != (fact is not None):
        raise ValueError('Spell cast lost its original hand-rank facts')
    if fact is None: return
    validate_fact(state, registry, fact)
    if (fact.source_id, fact.card_id, fact.player_id) != (cast.source_id, cast.card_id, cast.player_id):
        raise ValueError('Spell rank borrowed another physical source')
    if cast.play_id is not None:
        if fact != state.play_history[cast.play_id-1].hand_cost_rank:
            raise ValueError('Hand cast changed its original submitted rank')
    elif (fact.turn, fact.action) != (cast.turn, cast.action):
        raise ValueError('Automatic cast changed its original rank boundary')


def satisfied(context):
    from .errors import ResolutionError
    if context.cast is None or context.cast.source_id != context.source_id or context.cast.hand_cost_rank is None:
        raise ResolutionError('Highest-cost spell requires its original cast rank')
    return context.cast.hand_cost_rank.highest
