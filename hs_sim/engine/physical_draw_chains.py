"""An original Battlecry's successive top draws through the ordinary draw writer.

The finite condition is the printed Dragon identity needed by Wrathion. Each
continuation refers to its actual direct DrawRecord, never the last draw made
by a reaction or a casts-when-drawn replacement. No extra draw ledger is kept.
"""
from dataclasses import dataclass

from .draw_casts import draw_one, draw_record
from .effects import Effect, _integer
from .model import CardType
from .pools import PoolQuery, matches_metadata


DRAGONS = PoolQuery(kinds=(CardType.MINION,), tribes_any=('dragon',))


def is_dragon(registry, row):
    if row.card_id is None:
        return False
    card = registry.card(row.card_id)
    return card.kind == CardType.MINION and matches_metadata(DRAGONS,
        card_id=card.id, kind=card.kind, cost=card.cost, meta=card.metadata,
        spell_school=card.spell_school, keywords=card.keywords)


@dataclass(frozen=True)
class DrawBattlecryUntilNonDragon(Effect):
    battlecry_id: int

    def __post_init__(self):
        _integer(self.battlecry_id, 'original successive-draw Battlecry', 1)

    def validate_in_state(self, state, registry):
        from .battlecries import battlecry_record, validate_record
        self.__post_init__()
        row = battlecry_record(state, self.battlecry_id)
        validate_record(state, registry, row)
        if (row.completed or row.interrupted or row.failure is not None or
                not row.payload_started or registry.card(row.card_id).kind != CardType.MINION):
            raise ValueError('Successive draws require their actual running minion Battlecry')
        return row


@dataclass(frozen=True)
class ContinueBattlecryDragonDraws(Effect):
    request: DrawBattlecryUntilNonDragon
    draw_ids: tuple[int, ...]

    def __post_init__(self):
        if type(self.request) is not DrawBattlecryUntilNonDragon:
            raise ValueError('Draw continuation requires its complete original Battlecry request')
        self.request.__post_init__()
        if type(self.draw_ids) is not tuple or not self.draw_ids:
            raise ValueError('Draw continuation requires its ordered actual direct draws')
        for number in self.draw_ids:
            _integer(number, 'original direct draw', 1)
        if any(a >= b for a, b in zip(self.draw_ids, self.draw_ids[1:])):
            raise ValueError('Successive direct draws must keep their original unique order')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        battlecry = self.request.validate_in_state(state, registry)
        rows = tuple(draw_record(state, number) for number in self.draw_ids)
        for index, row in enumerate(rows):
            if ((row.player_id, row.source_id, row.turn, row.parent_id) !=
                    (battlecry.player_id, battlecry.source_id, battlecry.turn, None) or
                    not battlecry.action <= row.action <= state.action_number or row.interrupted):
                raise ValueError('Successive draws borrowed another player, source, turn or replacement')
            if index < len(rows)-1 and (not row.completed or not is_dragon(registry, row)):
                raise ValueError('Successive draws continued past an unfinished or non-Dragon draw')
        return battlecry, rows[-1]


def advance(r, request, previous=()):
    battlecry = request.validate_in_state(r.state, r.registry)
    number = len(r.state.draw_history)+1
    work = draw_one(r, battlecry.player_id, source_id=battlecry.source_id)
    tail = ContinueBattlecryDragonDraws(request, (*previous, number))
    tail.validate_in_state(r.state, r.registry)
    return (*work, tail)


def begin(r, request):
    return advance(r, request)


def continue_draws(r, effect):
    _, row = effect.validate_in_state(r.state, r.registry)
    if not row.completed:
        raise ValueError('Successive draws cannot pass their original ordinary draw completion')
    return advance(r, effect.request, effect.draw_ids) if is_dragon(r.registry, row) else ()


def register(mechanics):
    mechanics.register(DrawBattlecryUntilNonDragon, begin)
    mechanics.register(ContinueBattlecryDragonDraws, continue_draws)
