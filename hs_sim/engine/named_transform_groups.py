"""A captured board group receives named faces before its first notification."""
from dataclasses import dataclass

from .effects import Effect, _source
from .errors import ResolutionError, ResolutionLimitExceeded
from .model import CardType
from .sacrifice import MinionReference, live_minion, reference_value
from .zones import source_exists


@dataclass(frozen=True)
class TransformMinionsToCard(Effect):
    targets: tuple[MinionReference, ...]
    card_id: str
    source_id: int | None = None

    def __post_init__(self):
        _source(self.source_id)
        if type(self.targets) is not tuple or len({r.entity_id for r in self.targets if type(r) is MinionReference}) != len(self.targets):
            raise ValueError('Named transformation requires unique complete original targets')
        for target in self.targets:
            reference_value(target)
        if type(self.card_id) is not str or not self.card_id:
            raise ValueError('Named transformation requires one original destination')

    def validate_in_state(self, state):
        self.__post_init__()
        if self.source_id is not None and self.source_id not in state.entities:
            raise ValueError('Named transformation lost its original source')
        for ref in self.targets:
            entity = state.entities.get(ref.entity_id)
            if entity is None or ref.zone_epoch > entity.zone_epoch or ref.entered_order >= state.next_order:
                raise ValueError('Named transformation has an unknown or future target')


def transform(r, request):
    request.validate_in_state(r.state); source_exists(r, request.source_id)
    if len(request.targets) > r.rules.max_resolution_steps:
        raise ResolutionLimitExceeded('Named transformation group exceeds the effect budget')
    definition = r.registry.card(request.card_id)
    if definition.kind != CardType.MINION:
        raise ResolutionError('Named transformation requires a minion destination')
    # Accept all original living carriers before losing any shared health aura.
    entities = tuple(e for ref in request.targets if (e := live_minion(r.state, ref)) is not None)
    from .resolver import transform_minion, publish_transformation
    notices = []
    for entity in entities:
        transform_minion(r, entity, definition, source_id=request.source_id, notifications=notices)
    r.refresh_auras()
    work = []
    for notice in notices:
        work.extend(publish_transformation(r, *notice, publish_birth=True) or ())
    return tuple(work)


def register(mechanics):
    mechanics.register(TransformMinionsToCard, transform)
