"""Explicit current/starting deck predicates and serializable branches (R-123).

Host/rule queries only. Starting facts require the constructed opening record;
an arbitrary scenario's remaining cards never stand in for its original deck.
"""
from dataclasses import dataclass

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import SpellSchool


class UnknownDeckFacts(ResolutionError):
    """The requested condition cannot be decided from reviewed match facts."""


@dataclass(frozen=True)
class DeckCondition:
    scope: str = 'current'
    predicate: str = 'no_duplicates'

    def __post_init__(self):
        if type(self.scope) is not str or self.scope not in ('current', 'starting'):
            raise ValueError('Deck condition scope must be current or starting')
        if type(self.predicate) is not str or self.predicate not in ('no_duplicates', 'no_neutral', 'no_minions', 'empty', 'all_even_cost', 'all_odd_cost', 'no_spells'):
            raise ValueError('Unsupported deck condition predicate')
        if self.predicate == 'no_neutral' and self.scope != 'current':
            raise ValueError('No-Neutral deck condition requires current scope')
        if self.predicate == 'no_minions' and self.scope != 'current':
            raise ValueError('No-Minions deck condition requires current scope')
        if self.predicate == 'empty' and self.scope != 'current':
            raise ValueError('Empty deck condition requires current scope')
        if self.predicate == 'no_spells' and self.scope != 'starting':
            raise ValueError('No-Spells deck condition requires starting scope')
        if self.predicate in ('all_even_cost', 'all_odd_cost') and self.scope != 'starting':
            raise ValueError('Deck cost parity requires starting scope')


@dataclass(frozen=True)
class DeckCountCondition:
    """Current physical deck count is inclusively at most/at least card_count."""
    card_count: int
    comparison: str
    scope: str = 'current'

    def __post_init__(self):
        _integer(self.card_count, 'current deck count threshold', 0)
        if type(self.comparison) is not str or self.comparison not in ('at_most', 'at_least'):
            raise ValueError('Deck count comparison requires at_most or at_least')
        if type(self.scope) is not str or self.scope != 'current':
            raise ValueError('Deck count condition requires current scope')


@dataclass(frozen=True)
class DeckCostCondition:
    """No current physical deck card has this explicitly declared local cost."""
    cost: int
    cost_basis: str
    scope: str = 'current'

    def __post_init__(self):
        _integer(self.cost, 'excluded deck cost', 0)
        if type(self.cost_basis) is not str or self.cost_basis != 'local':
            raise ValueError('Deck cost exclusion requires explicit local cost basis')
        if type(self.scope) is not str or self.scope != 'current':
            raise ValueError('Deck cost exclusion requires current scope')


@dataclass(frozen=True)
class DeckSpellSchoolCondition:
    """Every SPELL in the original constructed deck has the declared school.

    Non-spells are excluded. With no spells the universal condition is true;
    this explicit internal policy still requires exact CN calibration.
    """
    spell_school: SpellSchool
    scope: str = 'starting'

    def __post_init__(self):
        if type(self.spell_school) is not SpellSchool:
            raise ValueError('Deck spell-school condition requires a SpellSchool')
        if type(self.scope) is not str or self.scope != 'starting':
            raise ValueError('Deck spell-school condition requires starting scope')


@dataclass(frozen=True)
class DeckMinionCostCondition:
    """Every current deck MINION has a local cost strictly below/above cost."""
    cost: int
    comparison: str
    cost_basis: str
    scope: str = 'current'

    def __post_init__(self):
        _integer(self.cost, 'deck minion cost threshold', 0)
        if type(self.comparison) is not str or self.comparison not in ('less', 'greater'):
            raise ValueError('Deck minion comparison requires less or greater')
        if type(self.cost_basis) is not str or self.cost_basis != 'local':
            raise ValueError('Deck minion comparison requires explicit local cost basis')
        if type(self.scope) is not str or self.scope != 'current':
            raise ValueError('Deck minion comparison requires current scope')


@dataclass(frozen=True)
class DeckCostCeilingCondition:
    """Every original constructed card's printed cost is at most cost_limit."""
    cost_limit: int
    cost_basis: str
    scope: str = 'starting'

    def __post_init__(self):
        _integer(self.cost_limit, 'starting deck cost ceiling', 0)
        if type(self.cost_basis) is not str or self.cost_basis != 'printed':
            raise ValueError('Starting deck cost ceiling requires explicit printed cost basis')
        if type(self.scope) is not str or self.scope != 'starting':
            raise ValueError('Deck cost ceiling requires starting scope')


@dataclass(frozen=True)
class DeckMinionCostSumCondition:
    """Original starting MINION printed costs sum to this exact total."""
    total_cost: int
    cost_basis: str
    scope: str = 'starting'

    def __post_init__(self):
        _integer(self.total_cost, 'starting minion total cost', 0)
        if type(self.cost_basis) is not str or self.cost_basis != 'printed':
            raise ValueError('Starting minion cost sum requires explicit printed cost basis')
        if type(self.scope) is not str or self.scope != 'starting':
            raise ValueError('Starting minion cost sum requires starting scope')


@dataclass(frozen=True)
class DeckCostDiversityCondition:
    """At least this many distinct original main-deck printed cost values."""
    min_distinct_costs: int
    cost_basis: str
    scope: str = 'starting'

    def __post_init__(self):
        _integer(self.min_distinct_costs, 'starting distinct cost minimum', 0)
        if type(self.cost_basis) is not str or self.cost_basis != 'printed':
            raise ValueError('Starting cost diversity requires explicit printed cost basis')
        if type(self.scope) is not str or self.scope != 'starting':
            raise ValueError('Deck cost diversity requires starting scope')


def _matches_starting_cost_diversity(state, registry, player_id, condition):
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    costs = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        _integer(card.cost, 'starting printed cost', 0)
        costs.append(card.cost)
    # All original definitions are known before deduplication/comparison.
    return len(set(costs)) >= condition.min_distinct_costs


def _matches_starting_minion_cost_sum(state, registry, player_id, condition):
    from .model import CardType
    from .pools import PoolQuery, matches_metadata
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    query = PoolQuery(kinds=(CardType.MINION,))
    costs = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        if matches_metadata(query, card_id=card.id, kind=card.kind,
                cost=card.cost, meta=card.metadata, spell_school=card.spell_school,
                keywords=card.keywords):
            _integer(card.cost, 'starting minion printed cost', 0)
            costs.append(card.cost)
    # Every original definition is known before aggregation; copies each count.
    return sum(costs) == condition.total_cost


def _matches_starting_cost_ceiling(state, registry, player_id, condition):
    from .pools import PoolQuery, matches_metadata
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    query = PoolQuery(max_cost=condition.cost_limit)
    matched_cards = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        _integer(card.cost, 'printed deck cost', 0)
        matched_cards.append(matches_metadata(query, card_id=card.id, kind=card.kind,
            cost=card.cost, meta=card.metadata, spell_school=card.spell_school,
            keywords=card.keywords))
    # Validate all original definitions before the universal aggregation.
    return all(matched_cards)


def _matches_deck_minion_cost(state, registry, player_id, condition):
    from .costs import local_cost
    from .model import CardType
    matched_minions = []
    for identity in state.players[player_id].deck:
        entity = state.entities[identity]
        card = registry.card(entity.card_id)
        if card.kind == CardType.MINION:
            cost = local_cost(entity)[0]
            _integer(cost, 'deck minion local cost', 0)
            matched_minions.append(cost < condition.cost if condition.comparison == 'less'
                                   else cost > condition.cost)
    # Validate all definitions before aggregation; non-minions do not compare.
    return all(matched_minions)


def _matches_starting_spell_school(state, registry, player_id, condition):
    from .model import CardType
    from .pools import PoolQuery, matches_metadata
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    query = PoolQuery(kinds=(CardType.SPELL,), spell_schools=(condition.spell_school,))
    matched_spells = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        if card.kind == CardType.SPELL:
            matched_spells.append(matches_metadata(query, card_id=card.id, kind=card.kind,
                cost=card.cost, meta=card.metadata, spell_school=card.spell_school,
                keywords=card.keywords))
    # Check every definition before aggregation, even after a nonmatching spell.
    return all(matched_spells)


def _matches_deck_cost(state, registry, player_id, condition):
    from .costs import local_cost
    from .pools import PoolQuery, matches_metadata
    query = PoolQuery(min_cost=condition.cost, max_cost=condition.cost)
    matched_cards = []
    for identity in state.players[player_id].deck:
        entity = state.entities[identity]
        card = registry.card(entity.card_id)
        matched_cards.append(matches_metadata(query, card_id=card.id, kind=card.kind,
            cost=local_cost(entity)[0], meta=card.metadata,
            spell_school=card.spell_school, keywords=card.keywords))
    # Do not short-circuit past an unknown physical definition after a match.
    return not any(matched_cards)


def _matches_starting_cost_parity(state, registry, player_id, condition):
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    remainder = 1 if condition.predicate == 'all_odd_cost' else 0
    matched_cards = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        _integer(card.cost, 'printed deck cost', 0)
        matched_cards.append(card.cost % 2 == remainder)
    # Validate every original definition even after a known parity mismatch.
    return all(matched_cards)


def _matches_starting_no_spells(state, registry, player_id):
    from .model import CardType
    from .pools import PoolQuery, matches_metadata
    if state.opening is None:
        raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
    query = PoolQuery(kinds=(CardType.SPELL,))
    matched_cards = []
    for card_id in state.players[player_id].original_deck:
        card = registry.card(card_id)
        matched_cards.append(matches_metadata(query, card_id=card.id, kind=card.kind,
            cost=card.cost, meta=card.metadata, spell_school=card.spell_school,
            keywords=card.keywords))
    # Resolve every original definition, even after finding a known SPELL.
    return not any(matched_cards)


def matches_deck_condition(state, registry, player_id, condition=DeckCondition()):
    """Evaluate validated state; unknown required facts raise, never inferred."""
    _player(player_id)
    if type(condition) is DeckCountCondition:
        condition.__post_init__()
        count = len(state.players[player_id].deck)
        return count <= condition.card_count if condition.comparison == 'at_most' else count >= condition.card_count
    if type(condition) is DeckCostDiversityCondition:
        condition.__post_init__()
        return _matches_starting_cost_diversity(state, registry, player_id, condition)
    if type(condition) is DeckMinionCostSumCondition:
        condition.__post_init__()
        return _matches_starting_minion_cost_sum(state, registry, player_id, condition)
    if type(condition) is DeckCostCeilingCondition:
        condition.__post_init__()
        return _matches_starting_cost_ceiling(state, registry, player_id, condition)
    if type(condition) is DeckMinionCostCondition:
        condition.__post_init__()
        return _matches_deck_minion_cost(state, registry, player_id, condition)
    if type(condition) is DeckSpellSchoolCondition:
        condition.__post_init__()
        return _matches_starting_spell_school(state, registry, player_id, condition)
    if type(condition) is DeckCostCondition:
        condition.__post_init__()
        return _matches_deck_cost(state, registry, player_id, condition)
    if type(condition) is not DeckCondition:
        raise ValueError('Expected DeckCondition')
    condition.__post_init__()
    if condition.predicate == 'no_spells':
        return _matches_starting_no_spells(state, registry, player_id)
    if condition.predicate in ('all_even_cost', 'all_odd_cost'):
        return _matches_starting_cost_parity(state, registry, player_id, condition)
    player = state.players[player_id]
    if condition.predicate == 'empty':
        # Emptiness is a physical-zone fact, independent of any card face or
        # metadata. The host supplies validated state, as for other queries.
        return not player.deck
    if condition.scope == 'starting':
        # validate_opening_boundary binds this record and original_deck to the
        # host MatchSetup, including on restoration. A tuple alone is no proof.
        if state.opening is None:
            raise UnknownDeckFacts('Starting deck facts are unknown for this scenario')
        card_ids = player.original_deck
    else:
        card_ids = tuple(state.entities[i].card_id for i in player.deck)
    identities = []; matched_cards = []
    query = None
    if condition.predicate in ('no_neutral', 'no_minions'):
        from .pools import PoolQuery, matches_metadata
        from .model import CardType
        query = (PoolQuery(include_neutral=False) if condition.predicate == 'no_neutral'
                 else PoolQuery(kinds=(CardType.MINION,)))
    for card_id in card_ids:
        card = registry.card(card_id)
        if condition.predicate != 'no_minions':
            if card.metadata is None:
                # Do not disclose which hidden card failed through an error message.
                raise UnknownDeckFacts('Deck condition requires reviewed identity metadata')
            identities.append(card.metadata.deck_identity or card.id)
        if query is not None:
            matched_cards.append(matches_metadata(query, card_id=card.id, kind=card.kind,
                cost=card.cost, meta=card.metadata, spell_school=card.spell_school, keywords=card.keywords))
    if query is not None:
        # Evaluate every physical row before aggregation, even after a match.
        return not any(matched_cards) if condition.predicate == 'no_minions' else all(matched_cards)
    return len(identities) == len(set(identities))


@dataclass(frozen=True)
class CheckDeckCondition(Effect):
    player_id: int
    condition: DeckCondition | DeckCostCondition | DeckSpellSchoolCondition | DeckMinionCostCondition | DeckCostCeilingCondition | DeckMinionCostSumCondition | DeckCostDiversityCondition | DeckCountCondition
    on_match: tuple[Effect, ...]
    on_miss: tuple[Effect, ...] = ()

    def __post_init__(self):
        _player(self.player_id)
        if type(self.condition) not in (DeckCondition, DeckCostCondition, DeckSpellSchoolCondition, DeckMinionCostCondition, DeckCostCeilingCondition, DeckMinionCostSumCondition, DeckCostDiversityCondition, DeckCountCondition):
            raise ValueError('Deck branch requires a supported deck condition')
        self.condition.__post_init__()
        for branch in (self.on_match, self.on_miss):
            if type(branch) is not tuple or any(not isinstance(e, Effect) for e in branch):
                raise ValueError('Deck branches require immutable tuples of effects')


def check(r, effect):
    effect.__post_init__()
    matched = matches_deck_condition(r.state, r.registry, effect.player_id, effect.condition)
    # Decide once at this effect's turn, then let the ordinary interpreter own
    # the selected sequence, its checkpoints, nested choices and restoration.
    return effect.on_match if matched else effect.on_miss


def register(mechanics):
    mechanics.register_payload_type(DeckCondition)
    mechanics.register_payload_type(DeckCostCondition)
    mechanics.register_payload_type(DeckSpellSchoolCondition)
    mechanics.register_payload_type(DeckMinionCostCondition)
    mechanics.register_payload_type(DeckCostCeilingCondition)
    mechanics.register_payload_type(DeckMinionCostSumCondition)
    mechanics.register_payload_type(DeckCostDiversityCondition)
    mechanics.register_payload_type(DeckCountCondition)
    mechanics.register(CheckDeckCondition, check)
