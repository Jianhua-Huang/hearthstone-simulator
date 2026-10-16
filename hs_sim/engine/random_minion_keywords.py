"""One original random recipient, then existing captured keyword grants."""
from dataclasses import dataclass

from .effects import Effect, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardType, Keyword
from .sacrifice import GrantCapturedKeyword, MinionReference, live_minion
from .zones import source_exists


@dataclass(frozen=True)
class RandomGrantMinionKeywords(Effect):
    candidates: tuple[MinionReference, ...]
    keywords: tuple[Keyword, ...]
    source_id: int | None = None

    def __post_init__(self):
        if type(self.candidates) is not tuple or any(type(r) is not MinionReference for r in self.candidates):
            raise ValueError('Random keyword grants require immutable physical minion references')
        for ref in self.candidates:
            ref.__post_init__()
        if len({r.entity_id for r in self.candidates}) != len(self.candidates):
            raise ValueError('Random keyword recipients require unique physical weights')
        if (type(self.keywords) is not tuple or not self.keywords or
                len(set(self.keywords)) != len(self.keywords) or
                any(type(k) is not Keyword or k not in (Keyword.DIVINE_SHIELD, Keyword.TAUNT) for k in self.keywords)):
            raise ValueError('Random keyword grants currently support explicit Shield/Taunt only')
        _source(self.source_id)

    def validate_in_state(self, state):
        self.__post_init__()
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Random keyword source is unknown')
        for ref in self.candidates:
            entity = state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
                raise ValueError('Random keyword candidate borrowed unknown or future physical material')


def random_grant(r, effect):
    effect.validate_in_state(r.state)
    source_exists(r, effect.source_id)
    if len(effect.candidates) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Random keyword candidate inventory exceeds resolution budget')
    for ref in effect.candidates:
        if r.registry.card(ref.card_id).kind != CardType.MINION:
            raise ResolutionError('Random keyword candidates require original minion definitions')
    candidates = tuple(sorted((ref for ref in effect.candidates if live_minion(r.state, ref) is not None),
                              key=lambda ref: ref.entity_id))
    if not candidates:
        return ()
    chosen = r.game._rng.choice(candidates)
    r.emit('random_choice', source_id=effect.source_id, target_id=chosen.entity_id)
    return tuple(GrantCapturedKeyword(chosen, keyword, effect.source_id) for keyword in effect.keywords)


def register(mechanics):
    mechanics.register(RandomGrantMinionKeywords, random_grant)
