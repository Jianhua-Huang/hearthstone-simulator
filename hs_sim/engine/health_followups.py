"""Fresh-state continuation retaining one original committed health result."""
from dataclasses import dataclass
from .effects import Effect, _behavior
from .errors import ResolutionError
from .health_outcomes import health_result
from .model import Event


@dataclass(frozen=True)
class InvokeHealthResult(Effect):
    behavior_id: str
    event: Event

    def __post_init__(self):
        _behavior(self.behavior_id)
        result = health_result(self.event)
        if result is None or result.source_id is None or result.source_controller is None:
            raise ValueError('Health continuation requires its original sourced result')


def invoke(r, request):
    request.__post_init__()
    r.registry.behavior(request.behavior_id)
    if (not 1 <= request.event.sequence <= len(r.game._events) or
            r.game._events[request.event.sequence-1] != request.event):
        raise ResolutionError('Health continuation lost its original committed event')
    result = health_result(request.event)
    if result.source_id not in r.state.entities:
        raise ResolutionError('Health continuation lost its original allocated source')
    return (r.call(request.behavior_id, result.source_id, result.source_controller,
                   target_id=result.original_target_id, event=request.event),)


def register(mechanics):
    mechanics.register(InvokeHealthResult, invoke)
