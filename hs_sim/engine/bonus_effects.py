"""Constructed bonus effects, separate from Battlegrounds upgrade effects.

The pool and readiness edge policy are versioned with the core rules. See the
M4 bonus-effects contract for evidence boundaries and pending CN calibration.
"""
from dataclasses import dataclass, replace

from .effects import Effect, GrantKeyword, _integer, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardType, Keyword, Zone


BONUS_EFFECTS = (
    Keyword.TAUNT, Keyword.DIVINE_SHIELD, Keyword.ELUSIVE, Keyword.LIFESTEAL,
    Keyword.POISONOUS, Keyword.REBORN, Keyword.RUSH, Keyword.WINDFURY,
)


def bonus_candidates(state, entity):
    # Readiness means attack timing, independent of current enemy targets. An
    # old minion facing only immune enemies must not gain redundant Rush.
    rush_useful = (entity.controller == state.active_player and entity.attacks_this_turn == 0
                   and entity.summoned_turn == state.turn and Keyword.CHARGE not in entity.keywords)
    return tuple(k for k in BONUS_EFFECTS if k not in entity.keywords
                 and (k != Keyword.RUSH or rush_useful))


@dataclass(frozen=True)
class GrantRandomBonusEffects(Effect):
    target_id: int
    count: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'target_id', 1)
        _integer(self.count, 'bonus count', 0)
        _source(self.source_id)


def grant_random_bonus_effects(r, effect):
    if effect.source_id is not None and effect.source_id not in r.state.entities:
        raise ResolutionError('Bonus effect source does not exist')
    if effect.count > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Bonus effects exceed resolution budget')
    if not effect.count:
        return ()
    entity = r.live_character(effect.target_id)
    if entity is None:
        r.stale(effect, effect.target_id)
        return ()
    if entity.zone != Zone.BOARD or r.registry.card(entity.card_id).kind != CardType.MINION:
        raise ResolutionError('Bonus effects require a minion')
    candidates = bonus_candidates(r.state, entity)
    if not candidates:
        r.emit('random_choice_skipped', source_id=effect.source_id, reason='no_bonus_effects')
        return ()
    keyword = r.game._rng.choice(candidates)
    # Shared attachments handle silence, expiry, copies and consumed keywords.
    # Reactions resolve before the next pick, whose eligibility is read afresh.
    return (GrantKeyword(entity.id, keyword, effect.source_id), replace(effect, count=effect.count - 1))


def register_bonus_effects(mechanics):
    mechanics.register(GrantRandomBonusEffects, grant_random_bonus_effects)
