"""Finite original-board partitions; health, protection and deaths stay shared."""
from dataclasses import dataclass, replace

from .effects import Damage, Effect, _integer
from .errors import ResolutionError
from .health_rules import prepare_health, rule_sources
from .model import CardType, DamageKind, HealthLayer, Zone
from .sacrifice import MinionReference, live_minion, reference_value


@dataclass(frozen=True)
class DamageMinionExcess(Effect):
    minion: MinionReference
    amount: int
    source_id: int
    spread: str
    direction: int = 0

    def __post_init__(self):
        reference_value(self.minion)
        _integer(self.amount, 'adjacent excess base damage', 0)
        _integer(self.source_id, 'adjacent excess spell source', 1)
        if type(self.spread) is not str or self.spread not in ('neighbors', 'rolling'):
            raise ValueError('Excess damage requires a declared neighbor or rolling policy')
        if (type(self.direction) is not int or self.direction not in (-1, 0, 1) or
                self.spread == 'neighbors' and self.direction != 0):
            raise ValueError('Only rolling damage can carry its single selected direction')


def original_target(state, registry, request):
    request.__post_init__()
    source = state.entities.get(request.source_id)
    if source is None or registry.card(source.card_id).kind != CardType.SPELL:
        raise ResolutionError('Adjacent excess requires its actual allocated SPELL source')
    definition = registry.card(request.minion.card_id)
    if definition.kind != CardType.MINION or definition.interactable:
        raise ResolutionError('Adjacent excess requires an ordinary original minion')
    return live_minion(state, request.minion)


def eligible(state, registry, entity_id):
    entity = state.entities[entity_id]
    return (entity.kind == CardType.MINION and entity.zone == Zone.BOARD and entity.health > 0 and
            not entity.doomed and entity.active and not registry.card(entity.card_id).interactable)


def quote(state, registry, request, target, rules):
    return prepare_health(state, registry, Damage(target.id, request.amount, request.source_id, DamageKind.SPELL),
        rules=tuple(row for row in rules if row[3].layer == HealthLayer.SOURCE))


def prepare_partition(state, registry, request, rules):
    target = original_target(state, registry, request)
    if target is None:
        return (), ()
    board = tuple(state.players[target.controller].board)
    position = board.index(target.id)
    budget = quote(state, registry, request, target, rules)
    if request.spread == 'neighbors':
        shares = [(target.id, budget.amount)]
        excess = max(0, budget.amount-target.health)
        if excess:
            shares.extend((board[i], excess) for i in (position-1, position+1)
                if 0 <= i < len(board) and eligible(state, registry, board[i]))
    else:
        first = min(budget.amount, target.health)
        shares = [(target.id, first)]
        remaining = budget.amount-first
        if remaining and len(board) > 1 and request.direction == 0:
            raise ResolutionError('Rolling excess lost its original selected direction')
        cursor = position+request.direction
        while remaining and request.direction and 0 <= cursor < len(board):
            entity_id = board[cursor]
            if not eligible(state, registry, entity_id):
                break
            amount = min(remaining, state.entities[entity_id].health)
            shares.append((entity_id, amount))
            remaining -= amount
            cursor += request.direction
    instructions = tuple(Damage(entity_id, amount, request.source_id, DamageKind.SPELL)
        for entity_id, amount in shares)
    target_rules = tuple(row for row in rules if row[3].layer == HealthLayer.TARGET)
    packets = tuple(prepare_health(state, registry, instruction, rules=target_rules,
        partition_source=budget) for instruction in instructions)
    return instructions, packets


def resolve(r, request):
    target = original_target(r.state, r.registry, request)
    if target is None:
        r.stale(request, request.minion.entity_id)
        return ()
    if request.spread == 'rolling' and request.direction == 0:
        board = r.player(target.controller).board
        position = board.index(target.id)
        # A pure source quote only decides whether a direction is needed. It
        # consumes no bonus or RNG; settlement re-quotes the unchanged window.
        if quote(r.state, r.registry, request, target, rule_sources(r.state)).amount > target.health:
            directions = tuple(d for d in (-1, 1) if 0 <= position+d < len(board))
            if directions:
                direction = directions[0]
                if len(directions) == 2:
                    direction = r.game._rng.choice(directions)
                    r.emit('random_choice', source_id=request.source_id, candidates=directions,
                        selected=direction, reason='rolling_excess_direction')
                request = replace(request, direction=direction)
    from .resolver import settle_health_batch
    return settle_health_batch(r, (), partition_request=request)


def register(mechanics):
    mechanics.register(DamageMinionExcess, resolve)
