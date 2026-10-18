"""Independent one-point discounts on actual owner turn starts while held."""
from dataclasses import dataclass, replace

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .lifecycle import attachment_id, refresh_entity
from .model import CostSpec, Enchantment, Event, Zone
from .zones import CardReference, ModifyStoredCost, reference_entity, reference_value, source_exists


def attach(state, entity, source_id):
    """Also used by atomic fresh-card creation, before acquisition notifications."""
    if source_id is None or source_id not in state.entities:
        raise ResolutionError('Periodic hand discount requires its original grant source')
    value = Enchantment(attachment_id(state), source_id=source_id,
        label='hand_turn_discount', hand_turn_discount=True)
    entity.enchantments.append(value)
    refresh_entity(entity)
    return value


@dataclass(frozen=True)
class GrantHandTurnDiscount(Effect):
    card: CardReference
    source_id: int

    def __post_init__(self):
        reference_value(self.card)
        _integer(self.source_id, 'periodic discount source', 1)
        if self.card.zone != Zone.HAND:
            raise ValueError('Periodic discount grant requires an original hand card')


@dataclass(frozen=True)
class ApplyHandTurnDiscount(Effect):
    target_id: int
    player_id: int
    hand_entry_id: int
    attachment_id: int
    event: Event

    def __post_init__(self):
        for name in ('target_id','hand_entry_id','attachment_id'):
            _integer(getattr(self,name),name,1)
        _player(self.player_id)
        if type(self.event) is not Event or self.event.kind != 'turn_started' or self.event.player_id != self.player_id:
            raise ValueError('Periodic discount requires its original owner start event')
        _integer(dict(self.event.data).get('turn'), 'original owner start turn', 1)


def grant(r, effect):
    effect.__post_init__();source_exists(r,effect.source_id)
    entity=reference_entity(r,effect.card)
    if entity is None:return ()
    attach(r.state,entity,effect.source_id)
    r.emit('hand_turn_discount_granted',source_id=effect.source_id,target_id=entity.id,player_id=entity.controller)
    return ()


def capture(r, event):
    if event.kind != 'turn_started':return ()
    return tuple(ApplyHandTurnDiscount(e.id,event.player_id,e.hand_entry_id,a.id,event)
        for eid in r.state.players[event.player_id].hand for e in (r.state.entities[eid],)
        for a in e.enchantments if a.hand_turn_discount)


def apply(r, effect):
    effect.__post_init__();event=effect.event
    turn=dict(event.data)['turn']
    if (turn != r.state.turn or event.sequence > len(r.game._events) or
            r.game._events[event.sequence-1] != event):
        raise ResolutionError('Periodic discount lost its actual owner start event')
    entity=r.state.entities.get(effect.target_id)
    if (entity is None or entity.zone != Zone.HAND or entity.controller != effect.player_id or
            entity.hand_entry_id != effect.hand_entry_id):return ()
    stamp=next((a for a in entity.enchantments if a.id==effect.attachment_id and a.hand_turn_discount),None)
    if stamp is None or stamp.hand_discount_turn==turn:return ()
    entity.enchantments[entity.enchantments.index(stamp)]=replace(stamp,hand_discount_turn=turn)
    return (ModifyStoredCost(CardReference.capture(entity),CostSpec(delta=-1),stamp.source_id),)


def validate_boundary(game):
    for entity in game._state.entities.values():
        for stamp in entity.enchantments:
            if stamp.hand_turn_discount:
                if stamp.source_id not in game._state.entities:
                    raise ValueError('Periodic hand discount lost its physical grant source')
                if stamp.hand_discount_turn is not None and stamp.hand_discount_turn > game._state.turn:
                    raise ValueError('Periodic hand discount references a future turn')


def register(mechanics):
    mechanics.register(GrantHandTurnDiscount,grant)
    mechanics.register(ApplyHandTurnDiscount,apply)
