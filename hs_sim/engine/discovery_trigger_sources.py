"""Pre-delivery qualification for finite ordinary after-Discover observers.

This is an eligibility roster, not another trigger queue. Completion still
captures surviving ordinary abilities in the existing listener order.
"""
from dataclasses import dataclass

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .model import CardType, Zone, _int, _name

EVENT = 'card_discovered'


@dataclass(frozen=True)
class DiscoveryTriggerProfile:
    card_id: str
    behavior_id: str

    def __post_init__(self):
        _name(self.card_id, 'native discovery observer')
        _name(self.behavior_id, 'native discovery observer behavior')


def validate_profile(registry, profile):
    if type(profile) is not DiscoveryTriggerProfile:
        raise ValueError('Expected a finite native discovery observer profile')
    profile.__post_init__()
    card = registry.card(profile.card_id)
    declarations = tuple(t for t in card.triggers if t.event == EVENT and t.behavior_id == profile.behavior_id)
    if (card.kind != CardType.MINION or card.choice_only or card.starship_for or
            card.interactable is not None or len(declarations) != 1 or declarations[0].end_turn is not None):
        raise ValueError('Discovery qualification requires its original ordinary minion trigger')
    registry.behavior(profile.behavior_id)


@dataclass(frozen=True)
class DiscoveryTriggerSource:
    source: SourceAllocationFact
    ability_id: int
    behavior_id: str
    next_attachment_id: int

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact:
            raise ValueError('Discovery observer requires its original physical source')
        self.source.__post_init__()
        _int(self.ability_id, 'original discovery observer ability', 1)
        _name(self.behavior_id, 'original discovery observer behavior')
        _int(self.next_attachment_id, 'discovery observer attachment bound', 1)
        if ((self.source.kind, self.source.zone) != (CardType.MINION, Zone.BOARD) or
                self.ability_id >= self.next_attachment_id):
            raise ValueError('Discovery observer lost its original active ordinary trigger')

    @property
    def order(self): return self.source.entered_order, self.source.entity_id, self.ability_id

    def matches(self, entity, ability):
        s = self.source
        return (ability.kind == 'trigger' and ability.event == EVENT and
            ability.end_turn_spec is None and not ability.consumed and
            (entity.id, entity.card_id, entity.kind, entity.owner, entity.controller,
            entity.zone, entity.zone_epoch, entity.entered_order, ability.id, ability.behavior_id) == (
            s.entity_id, s.card_id, s.kind, s.owner, s.controller, s.zone,
            s.zone_epoch, s.entered_order, self.ability_id, self.behavior_id))


def capture(state, registry, player_id):
    if not registry.discovery_trigger_profiles: return ()
    from .end_turns import listeners
    from .lifecycle import active_abilities
    result = []
    for controller, _, entity_id, player_effect in listeners(state):
        if controller != player_id or player_effect is not None: continue
        entity = state.entities[entity_id]
        if (entity.kind, entity.zone) != (CardType.MINION, Zone.BOARD): continue
        for ability in sorted(active_abilities(entity, 'trigger'), key=lambda a:a.id):
            if ability.event == EVENT and ability.behavior_id in registry.discovery_trigger_profiles:
                result.append(DiscoveryTriggerSource(SourceAllocationFact.capture(state, entity),
                    ability.id, ability.behavior_id, state.next_attachment_id))
    return tuple(result)


def validate_record(record):
    values = record.trigger_sources
    if type(values) is not tuple or any(type(s) is not DiscoveryTriggerSource for s in values):
        raise ValueError('Discovery requires its complete immutable original observer roster')
    if record.is_control and values:
        raise ValueError('A refresh control cannot reserve discovery observers')
    for value in values:
        value.__post_init__()
        if value.source.controller != record.result.choice.player_id:
            raise ValueError('Discovery observer borrowed the other player')
    orders = tuple(s.order for s in values)
    if orders != tuple(sorted(set(orders))):
        raise ValueError('Discovery observer roster changed order or repeated an ability')
    bounds = {(s.source.next_entity_id, s.source.next_order, s.next_attachment_id) for s in values}
    if len(bounds) > 1:
        raise ValueError('Discovery observers borrowed different original acceptance windows')


def validate_history(state, registry, record):
    validate_record(record)
    for value in record.trigger_sources:
        validate_allocation(state, registry, value.source, closed=True)
        if value.next_attachment_id > state.next_attachment_id or value.behavior_id not in registry.discovery_trigger_profiles:
            raise ValueError('Discovery observer borrowed a future or undeclared trigger')


def eligible(state, registry, event, entity, ability):
    if event.kind != EVENT or ability.behavior_id not in registry.discovery_trigger_profiles:
        return True
    from .discovery_delivery import original_recipient
    original_recipient(state, event)
    row = state.card_discovery_history[dict(event.data)['discovery_id']-1]
    return any(s.matches(entity, ability) for s in row.trigger_sources)


def from_dict(value):
    from .serialization import _row
    row = _row(value, DiscoveryTriggerSource)
    row['source'] = allocation_from_dict(row['source'])
    return DiscoveryTriggerSource(**row)


def register(mechanics):
    mechanics.register_payload_type(DiscoveryTriggerSource)
