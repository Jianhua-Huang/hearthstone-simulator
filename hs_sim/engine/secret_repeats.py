"""One accepted extra Secret body from live ordinary native sources."""
from dataclasses import dataclass

from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import CardType,Event
from .sacrifice import MinionReference,reference_value


@dataclass(frozen=True)
class NativeSecretRepeatProfile:
    card_id: str
    executions: int = 2

    def __post_init__(self):
        if type(self.card_id)is not str or not self.card_id or type(self.executions)is not int or self.executions!=2:
            raise ValueError('Native Secret repeat requires its explicit two-execution source')


def validate_profile(registry,profile):
    if type(profile)is not NativeSecretRepeatProfile:raise ValueError('Typed native Secret repeat profile required')
    profile.__post_init__();card=registry.card(profile.card_id)
    from .stat_relations import validate_ordinary_face
    validate_ordinary_face(card)
    if card.kind!=CardType.MINION:raise ValueError('Native Secret repeat requires an ordinary minion source')


@dataclass(frozen=True)
class RepeatSecretBody(Effect):
    secret_id: int
    secret_card_id: str
    instance_id: int
    player_id: int
    target_id: int | None
    event: Event
    sources: tuple[MinionReference,...]

    def __post_init__(self):
        _integer(self.secret_id,'original Secret source',1);_integer(self.instance_id,'original Secret instance',1)
        _player(self.player_id)
        if type(self.secret_card_id)is not str or not self.secret_card_id or type(self.event)is not Event:
            raise ValueError('Secret repeat requires its original face and captured event')
        if self.target_id is not None:_integer(self.target_id,'original Secret target',1)
        if type(self.sources)is not tuple or not self.sources:raise ValueError('Secret repeat requires accepted native sources')
        for source in self.sources:reference_value(source)
        if len({x.entity_id for x in self.sources})!=len(self.sources):raise ValueError('Native Secret repeat sources cannot repeat')

    def validate_in_state(self,state,registry,events=None):
        self.__post_init__()
        if self.secret_id not in state.entities or registry.card(self.secret_card_id).secret is None:
            raise ValueError('Secret repeat lost its original declared Secret source')
        for ref in self.sources:
            entity=state.entities.get(ref.entity_id)
            profile=registry.native_secret_repeat_profiles.get(ref.card_id)
            if(entity is None or ref.zone_epoch>entity.zone_epoch or ref.entered_order>=state.next_order or
                    ref.player_id!=self.player_id or profile is None):
                raise ValueError('Secret repeat borrowed an unknown/future allocation or undeclared source')
            validate_profile(registry,profile)
        if events is not None and(not 1<=self.event.sequence<=len(events)or events[self.event.sequence-1]!=self.event):
            raise ValueError('Secret repeat changed its original captured event')


def capture_extra(r,secret,event,target_id):
    sources=tuple(MinionReference.capture(e)for eid in r.player(secret.controller).board
        for e in(r.state.entities[eid],)if e.kind==CardType.MINION and e.active and e.health>0 and not e.doomed
        and not e.silenced and e.card_id in r.registry.native_secret_repeat_profiles)
    # Each physical source declares "twice". Multiple such sources retain the
    # same two-body maximum, never a product or one extra for every source.
    return None if not sources else RepeatSecretBody(secret.id,secret.card_id,secret.secret_instance_id,
        secret.controller,target_id,event,sources)


def repeat(r,effect):
    effect.validate_in_state(r.state,r.registry,r.game._events)
    from .interrupts import find_window
    window_id=dict(effect.event.data).get('window_id')
    window=find_window(r.state,window_id)if window_id is not None else None
    if window_id is not None and window is None:
        raise ResolutionError('Accepted Secret repeat lost its original active window')
    spec=r.registry.card(effect.secret_card_id).secret
    # The first body has finished. Reaccept only the extra body against this
    # new state, with the original event/window/target; do not reveal, consume,
    # pay for or run the Secret eligibility predicate a second time.
    return(r.call(spec.behavior_id,effect.secret_id,effect.player_id,effect.target_id,
        event=effect.event,window=window),)


def register(mechanics):mechanics.register(RepeatSecretBody,repeat)
