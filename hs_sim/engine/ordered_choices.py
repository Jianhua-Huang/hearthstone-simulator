"""Sequential, without-replacement branches on the ordinary choice interpreter."""
from dataclasses import dataclass, replace

from .effects import ChoiceOption, Effect, RequestChoice, _integer
from .model import ChoicePurpose


@dataclass(frozen=True)
class ChooseInOrder(Effect):
    player_id: int
    options: tuple[ChoiceOption, ...]
    count: int = 1
    source_id: int | None = None
    prompt: str = 'Choose the next effect'
    purpose: ChoicePurpose = ChoicePurpose.EFFECT

    def __post_init__(self):
        _integer(self.count, 'ordered choice count', 0)
        # Reuse the common option, uniqueness, player and range contract.
        RequestChoice(self.player_id, self.options, self.source_id, self.prompt,
                      self.count, self.count, purpose=self.purpose)


@dataclass(frozen=True)
class ResolveOrderedOption(Effect):
    request: ChooseInOrder
    selected_id: str

    def __post_init__(self):
        if type(self.request) is not ChooseInOrder:
            raise ValueError('Ordered continuation requires ChooseInOrder')
        self.request.__post_init__()
        if not self.request.count or self.selected_id not in tuple(o.id for o in self.request.options):
            raise ValueError('Ordered continuation has no such remaining option')


def choose_in_order(r, effect):
    from .choices import request_choice
    if not effect.count:
        return request_choice(r, RequestChoice(effect.player_id, effect.options, effect.source_id,
                              effect.prompt, 0, 0, purpose=effect.purpose))
    options = tuple(replace(o, effects=(ResolveOrderedOption(effect, o.id),)) for o in effect.options)
    return request_choice(r, RequestChoice(effect.player_id, options, effect.source_id,
                                          effect.prompt, purpose=effect.purpose))


def resolve_ordered_option(r, effect):
    request = effect.request
    selected = next(o for o in request.options if o.id == effect.selected_id)
    remaining = tuple(o for o in request.options if o.id != effect.selected_id)
    # The selected branch, its reactions and any nested choices finish before
    # the next request. Nothing precomputes a mutable future board or RNG result.
    tail = (replace(request, options=remaining, count=request.count - 1),) if request.count > 1 else ()
    return (*selected.effects, *tail)


def register_ordered_choices(mechanics):
    mechanics.register(ChooseInOrder, choose_in_order)
    mechanics.register(ResolveOrderedOption, resolve_ordered_option)
