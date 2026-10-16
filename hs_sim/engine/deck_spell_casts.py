"""A real physical deck cast, with stored cost filtering and shared target selection."""
from dataclasses import dataclass
from .automatic_targets import PreferredMinionTarget, validate_preferred_source
from .costs import local_cost
from .effects import Effect, _integer, _player
from .model import CardType, Zone
from .spell_casts import CastStoredSpell
from .zones import CardReference, source_exists


@dataclass(frozen=True)
class CastRandomDeckSpell(Effect):
    player_id: int
    max_cost: int
    source_id: int
    target_preference: PreferredMinionTarget | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.max_cost, 'deck spell cost ceiling', 0)
        _integer(self.source_id, 'deck spell causing source', 1)
        if self.target_preference is not None and type(self.target_preference) is not PreferredMinionTarget:
            raise ValueError('Deck spell preference requires its original minion')
        validate_preferred_source(self.target_preference, self.source_id)


def cast_matching(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    validate_preferred_source(effect.target_preference, effect.source_id, r.state)
    candidates = []
    for eid in r.player(effect.player_id).deck:
        entity = r.state.entities[eid]
        definition = r.registry.card(entity.card_id)
        if (entity.zone == Zone.DECK and entity.controller == effect.player_id and
                definition.kind == CardType.SPELL and max(0, local_cost(entity)[0]) <= effect.max_cost):
            candidates.append(CardReference.capture(entity))
    if not candidates:
        return ()
    selected = r.game._rng.choice(candidates)
    return (CastStoredSpell(selected, effect.player_id, effect.source_id,
        target_preference=effect.target_preference),)


def register(mechanics):
    mechanics.register(CastRandomDeckSpell, cast_matching)
