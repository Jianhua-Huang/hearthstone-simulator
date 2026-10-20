"""Native held Battlecry parameter; printed card and hero classes are unchanged."""
from dataclasses import dataclass, replace
import json
from random import Random

from .effects import Effect, _integer
from .model import CardClass, CardType, Event, Zone
from .zones import CardReference

CLASSES = tuple(c for c in CardClass if c not in (CardClass.NEUTRAL, CardClass.DREAM))
VALUES = tuple(c.value for c in CLASSES)
KIND = 'class_discovery'
PUBLICATION = 'native_discovery_class_rotated'


@dataclass(frozen=True)
class RotatingDiscoveryClassProfile:
    card_id: str


def validate_profile(registry, profile):
    if type(profile) is not RotatingDiscoveryClassProfile:
        raise ValueError('Native discovery class needs its typed declaration')
    card = registry.card(profile.card_id)
    if card.kind != CardType.MINION or card.battlecry is None or card.hand_progress is None:
        raise ValueError('Native discovery class needs an actual held Battlecry source')
    spec = card.hand_progress
    if (spec.kind, spec.event, spec.goal, spec.repeat, spec.zone) != ('event','turn_started',1,True,Zone.HAND):
        raise ValueError('Native discovery rotation needs the ordinary held owner-start listener')


def source(entity, card_id=None):
    return next((a for a in entity.abilities if a.kind == KIND and not a.consumed and
                 (card_id is None or a.class_discovery_card_id == card_id)), None)


def initial_class(state, player_id):
    value = state.players[player_id].hero_class
    if value not in CLASSES:
        raise ValueError('Native class discovery requires a known constructed hero class')
    return value.value


def validate_carrier(registry, card_id, kind, abilities, components=()):
    for row in abilities:
        if row.kind != KIND:
            continue
        row.__post_init__()
        if (kind != CardType.MINION or row.class_discovery_card_id not in registry.rotating_discovery_class_profiles or
                row.class_discovery_card_id not in (card_id,*components)):
            raise ValueError('Discovery class borrowed an undeclared native minion')


def payload_value(entity, ability):
    native = source(entity, ability.battlecry_card_id)
    return None if native is None else native.discovery_class


def validate_payload(registry, payload):
    declared = payload.card_id in registry.rotating_discovery_class_profiles
    if declared != (payload.discovery_class is not None) or payload.discovery_class is not None and payload.discovery_class not in VALUES:
        raise ValueError('Battlecry discovery class lost its original native declaration')


@dataclass(frozen=True)
class RotateDiscoveryClass(Effect):
    card: CardReference
    ability_id: int
    event: Event

    def __post_init__(self):
        if type(self.card) is not CardReference or self.card.zone != Zone.HAND or type(self.event) is not Event:
            raise ValueError('Class rotation needs its original hand residence and turn event')
        self.card.__post_init__()
        _integer(self.ability_id,'native discovery class ability',1)
        if self.event.kind != 'turn_started' or self.event.player_id != self.card.player_id:
            raise ValueError('Class rotation needs a genuine owner start')


def rotate(r, effect):
    from .hand_deadlines import same_hand
    from .serialization import end_turn_rng_to_json
    effect.__post_init__()
    if not same_hand(r.state,effect.card):
        return ()
    entity=r.state.entities[effect.card.entity_id]
    native=source(entity)
    if native is None or native.id != effect.ability_id:
        return ()
    event=effect.event
    if event.sequence > len(r.game._events) or r.game._events[event.sequence-1] != event:
        raise ValueError('Class rotation borrowed a different original turn event')
    from .hand_progress import progress_ability
    progress=progress_ability(entity)
    if progress is None or f'event:{event.sequence}' not in progress.progress_keys:
        raise ValueError('Class rotation has no accepted native hand-progress witness')
    if any(e.kind==PUBLICATION and e.source_id==entity.id and
           dict(e.data).get('ability_id')==native.id and dict(e.data).get('owner_start')==event.sequence
           for e in r.game._events):
        raise ValueError('Class rotation cannot consume the same owner start twice')
    validate_carrier(r.registry,entity.card_id,entity.kind,(native,),entity.components)
    candidates=tuple(c for c in VALUES if c != native.discovery_class)
    before=r.game._rng.getstate()
    selected=candidates[r.game._rng.randrange(len(candidates))]
    after=r.game._rng.getstate()
    entity.abilities[entity.abilities.index(native)]=replace(native,discovery_class=selected)
    r.emit(PUBLICATION,source_id=entity.id,player_id=entity.controller,
        ability_id=native.id,card_id=native.class_discovery_card_id,owner_start=event.sequence,
        previous=native.discovery_class,candidates=candidates,selected=selected,
        rng_before=json.dumps(end_turn_rng_to_json(before),separators=(',',':')),
        rng_after=json.dumps(end_turn_rng_to_json(after),separators=(',',':')))
    return ()


def public_class(entity):
    native=source(entity)
    return None if native is None else native.discovery_class


def validate_game(game):
    registry=game.registry
    if not registry.rotating_discovery_class_profiles:
        return
    state=game._state
    for row in state.play_history:
        for payload in row.battlecries:
            validate_payload(registry,payload)
    for row in state.battlecry_batches:
        for payload in row.payloads:
            validate_payload(registry,payload)
    for row in state.battlecry_history:
        validate_payload(registry,row.payload)
    for entity in state.entities.values():
        validate_carrier(registry,entity.card_id,entity.kind,entity.abilities,entity.components)
        if (entity.card_id in registry.rotating_discovery_class_profiles and not entity.silenced and
                entity.zone in (Zone.HAND,Zone.DECK,Zone.BOARD)):
            rows=[a for a in entity.abilities if a.kind==KIND]
            if len(rows)!=1:
                raise ValueError('Native discovery class lost its complete original parameter')
    from .hero_health_history import effective_events
    from .serialization import end_turn_rng_from_json
    events=tuple(effective_events(game._events));by_id={e.sequence:e for e in events}
    last={}
    for event in events:
        if event.kind!=PUBLICATION:
            continue
        d=dict(event.data)
        if set(d)!={'ability_id','card_id','owner_start','previous','candidates','selected','rng_before','rng_after'}:
            raise ValueError('Native discovery class changed its complete random receipt')
        _integer(d['ability_id'],'native discovery receipt ability',1)
        start=by_id.get(d['owner_start'])
        if (d['card_id'] not in registry.rotating_discovery_class_profiles or
                start is None or start.kind!='turn_started' or start.player_id!=event.player_id or start.sequence>=event.sequence or
                d['previous'] not in VALUES or tuple(d['candidates'])!=tuple(c for c in VALUES if c!=d['previous'])):
            raise ValueError('Native discovery class lost its original turn or complete class domain')
        rng=Random();rng.setstate(end_turn_rng_from_json(json.loads(d['rng_before'])))
        selected=d['candidates'][rng.randrange(len(d['candidates']))]
        if selected!=d['selected'] or rng.getstate()!=end_turn_rng_from_json(json.loads(d['rng_after'])):
            raise ValueError('Native discovery class changed its original random result')
        key=(event.source_id,d['ability_id'])
        if key in last and last[key][1]>=d['owner_start']:
            raise ValueError('Native discovery class repeated an original owner-start witness')
        if key in last and last[key][0]!=d['previous']:
            raise ValueError('Native discovery class broke its original parameter chain')
        last[key]=(selected,d['owner_start'])
    for (identity,aid),(selected,_) in last.items():
        entity=state.entities.get(identity)
        if entity is None:
            raise ValueError('Native discovery class lost its original physical source')
        native=next((a for a in entity.abilities if a.id==aid and a.kind==KIND),None)
        if native is not None and native.discovery_class!=selected:
            raise ValueError('Native discovery class differs from its last accepted rotation')


def register(mechanics):
    mechanics.register(RotateDiscoveryClass,rotate)
