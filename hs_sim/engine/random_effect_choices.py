"""Select one finite effect branch; execute it through the ordinary work queue."""
from dataclasses import dataclass

from .effects import ChoiceOption, Effect, _integer, _player


@dataclass(frozen=True)
class ChooseRandomEffects(Effect):
    player_id: int
    source_id: int
    options: tuple[ChoiceOption, ...]
    weights: tuple[int, ...] = ()

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.source_id, 'random branch source', 1)
        if type(self.options) is not tuple or not self.options or any(
                type(option) is not ChoiceOption for option in self.options):
            raise ValueError('Random branches require explicit immutable alternatives')
        for option in self.options:
            option.__post_init__()
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError('Random branch identities must be unique')
        if type(self.weights) is not tuple or self.weights and len(self.weights)!=len(self.options):
            raise ValueError('Random branch weights must cover the complete ordered alternatives')
        for value in self.weights:_integer(value,'random branch weight',1)

    def validate_in_state(self, state):
        self.__post_init__()
        if self.source_id not in state.entities:
            raise ValueError('Random branches lost their allocated original source')


def choose(r, effect):
    effect.validate_in_state(r.state)
    r.player(effect.player_id)
    # Validate instruction types before sampling, without executing any body.
    for option in effect.options:
        for work in option.effects:
            r.game.mechanics.handler(work)
    selected = (r.game._rng.choices(effect.options,weights=effect.weights,k=1)[0]
                if effect.weights else r.game._rng.choice(effect.options))
    r.emit('random_choice', source_id=effect.source_id, player_id=effect.player_id,
        candidates=tuple(option.id for option in effect.options), selected=selected.id,
        producer='effect_branch',**({'weights':effect.weights}if effect.weights else{}))
    return selected.effects


def register(mechanics):
    mechanics.register(ChooseRandomEffects, choose)
