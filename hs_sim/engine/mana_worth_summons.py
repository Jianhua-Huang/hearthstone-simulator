"""Printed-mana budget over original weighted summon roots, one pick at a time."""
from dataclasses import dataclass

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import CardType
from .pools import GenerationPolicy, PoolQuery, SummonFromPool, summon_from_pool
from .summon_quantities import SummonCause, FinishCardSummon, record


@dataclass(frozen=True)
class ManaWorthEntryLink:
    budget: int
    remaining: int
    previous_root_id: int | None = None

    def __post_init__(self):
        _integer(self.budget, 'original printed-mana budget', 1)
        _integer(self.remaining, 'remaining printed-mana budget', 1)
        if self.remaining > self.budget: raise ValueError('Remaining summon budget exceeds its original amount')
        if self.previous_root_id is None:
            if self.remaining != self.budget: raise ValueError('Initial budget entry lost its original amount')
        else: _integer(self.previous_root_id, 'previous actual budget root', 1)


@dataclass(frozen=True)
class SummonManaWorth(Effect):
    player_id: int
    pool_id: str
    amount: int
    cause: SummonCause

    def __post_init__(self):
        _player(self.player_id); _integer(self.amount, 'printed-mana summon amount', 1)
        if type(self.pool_id) is not str or not self.pool_id: raise ValueError('Budget summon requires its registered pool')
        if type(self.cause) is not SummonCause: raise ValueError('Budget summon requires original typed attribution')
        self.cause.__post_init__()
        if self.player_id != self.cause.player_id: raise ValueError('Budget summon recipient differs from its original caster')


@dataclass(frozen=True)
class ContinueManaWorth(Effect):
    root_id: int
    def __post_init__(self): _integer(self.root_id, 'actual budget summon root', 1)


def query(remaining):
    return PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=0, max_cost=remaining)


def validate_recipe(request):
    link = request.producer_link
    if type(link) is not ManaWorthEntryLink: raise ValueError('Typed original mana budget link required')
    link.__post_init__()
    basis = request.pool_basis
    if (request.selection != 'weighted' or basis is None or request.position is not None or
            request.capacity != 'selection_requires_space' or request.player_id != request.cause.player_id or
            basis.query != query(link.remaining) or basis.policy != GenerationPolicy() or
            basis.entry_keywords or basis.entry_dormant_turns is not None):
        raise ValueError('Budget entry changed its original ordinary printed-minion pool recipe')


def remaining_after(registry, root):
    validate_recipe(root.request)
    if root.selected is None: return None
    selected = root.request.materials[root.selected].card_id
    cost = registry.pool_card(selected).cost
    if cost > root.request.producer_link.remaining: raise ValueError('Selected minion exceeds its original remaining budget')
    return root.request.producer_link.remaining - cost


def validate_link(state, registry, root, *, closed=False, roots=None):
    validate_recipe(root.request)
    link = root.request.producer_link
    if link.previous_root_id is None: return
    if link.previous_root_id >= root.id: raise ValueError('Budget entry borrowed a future or equal original root')
    inventory = {r.id: r for r in state.card_summon_history} if roots is None else roots
    previous = inventory.get(link.previous_root_id)
    if previous is None:
        if closed and roots is None: return  # Retired receipt parents are checked together below.
        raise ValueError('Budget entry lost its actual previous summon root')
    validate_recipe(previous.request)
    if (previous.status != 'completed' or previous.selected is None or
            previous.request.cause != root.request.cause or previous.request.player_id != root.request.player_id or
            previous.request.pool_basis.pool_id != root.request.pool_basis.pool_id or
            previous.request.pool_basis.context != root.request.pool_basis.context or
            previous.request.producer_link.budget != link.budget or
            remaining_after(registry, previous) != link.remaining):
        raise ValueError('Budget entry changed the original previous pick, amount or attribution')


def accept_entry(r, player_id, pool_id, cause, link):
    # The ordinary handler accepts the actual root and returns its original
    # controls. Read that returned identity; never guess a future allocator ID.
    work = summon_from_pool(r, SummonFromPool(player_id, pool_id, query(link.remaining),
        cause.source.entity_id, cause=cause), producer_link=link)
    finishes = [w for w in work if type(w) is FinishCardSummon]
    if len(finishes) != 1: raise ResolutionError('Budget summon lost its actual accepted root output')
    root = record(r.state, finishes[0].root_id)
    if root.request.producer_link != link: raise ResolutionError('Budget root output differs from its original request')
    return (*work, ContinueManaWorth(root.id))


def start(r, effect):
    effect.__post_init__()
    return accept_entry(r, effect.player_id, effect.pool_id, effect.cause, ManaWorthEntryLink(effect.amount, effect.amount))


def validate_control(state, registry, effect):
    effect.__post_init__()
    root = record(state, effect.root_id)
    validate_link(state, registry, root)
    if root.status == 'interrupted': raise ValueError('Interrupted budget entry retained control work')
    return root


def continue_budget(r, effect):
    root = validate_control(r.state, r.registry, effect)
    if root.status not in ('completed', 'skipped'): raise ResolutionError('Budget continuation preceded complete original delivery')
    remaining = remaining_after(r.registry, root)
    if remaining is None or remaining == 0: return ()
    link = root.request.producer_link
    return accept_entry(r, root.request.player_id, root.request.pool_basis.pool_id, root.request.cause,
        ManaWorthEntryLink(link.budget, remaining, root.id))


def validate_queue(state, registry, work):
    roots = {r.id: r for r in state.card_summon_history}
    budget_roots = {i: r for i, r in roots.items() if type(r.request.producer_link) is ManaWorthEntryLink}
    controls = [w for w in work if type(w) is ContinueManaWorth]
    for effect in controls: validate_control(state, registry, effect)
    children = {}
    for root in budget_roots.values():
        validate_link(state, registry, root, roots=roots)
        previous = root.request.producer_link.previous_root_id
        if previous is not None:
            if previous in children: raise ValueError('One original budget pick forked into multiple continuations')
            children[previous] = root.id
    for root in budget_roots.values():
        pending = [w for w in controls if w.root_id == root.id]
        child = children.get(root.id)
        if root.status == 'active':
            if len(pending) != 1 or child is not None: raise ValueError('Active budget root lost or duplicated its original continuation')
        elif root.status == 'completed' and remaining_after(registry, root) > 0:
            if int(child is not None) + len(pending) != 1: raise ValueError('Incomplete or duplicated remaining printed-mana budget')
        elif pending or child is not None:
            raise ValueError('Exhausted, skipped or interrupted budget retains a later entry')


def validate_events(state, registry, roots):
    children = set()
    for root in roots.values():
        if type(root.request.producer_link) is not ManaWorthEntryLink: continue
        validate_link(state, registry, root, closed=True, roots=roots)
        previous = root.request.producer_link.previous_root_id
        if previous is not None:
            if previous in children: raise ValueError('Historical budget entry forked its original root')
            children.add(previous)


def register(mechanics):
    mechanics.register_payload_type(ManaWorthEntryLink)
    mechanics.register(SummonManaWorth, start)
    mechanics.register(ContinueManaWorth, continue_budget)
