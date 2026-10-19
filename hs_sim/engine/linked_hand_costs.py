"""Actual hand-cost attachments remembered by a native Deathrattle.

The native link owns one exact cost layer, never an arbitrary reset of every
discount. Infinity's numeric value and restoration policy await CN calibration.
"""
from dataclasses import dataclass, replace

from .costs import attach_cost
from .deathrattle_memory import validate_reference
from .effects import Effect, _integer, _player
from .infinite_damage import INFINITE_HEALTH_VALUE
from .lifecycle import remove_attachments
from .model import CostSpec, RememberedCost
from .sacrifice import MinionReference, reference_value, same_instance

INFINITE_COST_VALUE = INFINITE_HEALTH_VALUE
INFINITE_COST_POLICY = 'int32-max-removable-local-cost-v1'


def validate_link(state, registry, link, *, closed=False):
    if type(link) is not RememberedCost:
        raise ValueError('Cost restoration requires its original typed attachment')
    link.__post_init__()
    if link.battlecry_id > len(state.battlecry_history) or link.enchantment_id >= state.next_attachment_id:
        raise ValueError('Cost link borrowed a future Battlecry or attachment')
    row = state.battlecry_history[link.battlecry_id-1]
    spec = registry.card(row.payload.card_id).native_deathrattle
    from .hand_history import hand_entry
    entry = hand_entry(state, link.hand_entry_id)
    if (not row.payload_started or row.failure is not None or spec is None or spec.kind != 'cost_link' or
            (entry.entity_id, entry.player_id) != (link.entity_id, row.player_id) or
            (entry.turn, entry.action) > (row.turn, row.action)):
        raise ValueError('Cost link changed its actual native source or original hand acquisition')
    target = state.entities.get(link.entity_id)
    if target is None:
        if closed: return
        raise ValueError('Cost link lost its original physical target')
    attachment = next((e for e in target.enchantments if e.id == link.enchantment_id), None)
    if attachment is not None and (attachment.source_id != row.source_id or attachment.cost != 0 or
            attachment.set_cost != INFINITE_COST_VALUE or attachment.cost_minimum != 0 or
            attachment.payment is not None or attachment.expires_turn is not None):
        raise ValueError('Cost link borrowed a different original cost operation')


@dataclass(frozen=True)
class SetRandomHandCostForDeathrattle(Effect):
    player_id: int
    battlecry_id: int
    reference: MinionReference | None
    ability_ids: tuple[int, ...]

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.battlecry_id, 'actual cost-link Battlecry', 1)
        if self.reference is not None: reference_value(self.reference)
        if type(self.ability_ids) is not tuple or len(set(self.ability_ids)) != len(self.ability_ids):
            raise ValueError('Cost linkage requires unique original memory abilities')
        for identity in self.ability_ids: _integer(identity, 'native cost-link ability', 1)
        if self.reference is None and self.ability_ids:
            raise ValueError('A departed carrier cannot claim later cost-memory attachments')

    def validate_in_state(self, state, registry):
        self.__post_init__()
        if self.battlecry_id > len(state.battlecry_history):
            raise ValueError('Cost linkage lost its actual Battlecry')
        row = state.battlecry_history[self.battlecry_id-1]
        spec = registry.card(row.payload.card_id).native_deathrattle
        if (row.completed or row.interrupted or not row.payload_started or row.failure is not None or
                row.player_id != self.player_id or spec is None or spec.kind != 'cost_link' or
                self.reference is not None and self.reference.entity_id != row.source_id):
            raise ValueError('Cost linkage changed its original active native Battlecry')
        if self.reference is not None: validate_reference(state, self.reference, self.ability_ids)
        return row


@dataclass(frozen=True)
class RestoreRememberedCost(Effect):
    deathrattle_id: int
    link: RememberedCost

    def __post_init__(self):
        _integer(self.deathrattle_id, 'actual cost-restoration Deathrattle', 1)
        if type(self.link) is not RememberedCost:
            raise ValueError('Cost restoration requires its complete original link')
        self.link.__post_init__()

    def validate_in_state(self, state, registry):
        self.__post_init__()
        validate_link(state, registry, self.link)
        from .deathrattles import record
        row = record(state, self.deathrattle_id)
        memory = row.capture.ability.deathrattle_memory
        if (row.execution_order is None or row.completed or row.interrupted or memory is None or
                memory.spec.kind != 'cost_link' or self.link not in memory.cost_links):
            raise ValueError('Cost restoration lost its actual frozen active Deathrattle')
        return row


def set_cost(r, effect):
    row = effect.validate_in_state(r.state, r.registry)
    candidates = tuple(r.player(effect.player_id).hand)
    if not candidates:
        return ()
    source = None if effect.reference is None else same_instance(r.state, effect.reference)
    abilities = [] if source is None else [a for a in source.abilities if a.id in effect.ability_ids]
    for ability in abilities:
        from .deathrattle_memory import validate_ability
        validate_ability(r.state, r.registry, ability)
        memory = ability.deathrattle_memory
        if memory is None or memory.spec.kind != 'cost_link' or any(x.battlecry_id == row.id for x in memory.cost_links):
            raise ValueError('Cost linkage changed or duplicated its original native memory')
    target = r.state.entities[r.game._rng.choice(candidates)]
    # This is the common ordered local cost installer. Memory is committed
    # before the ordinary notification can capture any reacting source state.
    attachment = attach_cost(r.state, target, CostSpec(set_to=INFINITE_COST_VALUE), row.source_id)
    link = RememberedCost(row.id, target.id, target.hand_entry_id, attachment.id)
    validate_link(r.state, r.registry, link)
    if source is not None:
        updates = {a.id: replace(a, deathrattle_memory=replace(a.deathrattle_memory,
            cost_links=(*a.deathrattle_memory.cost_links, link))) for a in abilities}
        source.abilities = [updates.get(a.id, a) for a in source.abilities]
    r.emit('cost_modified', target_id=target.id, source_id=row.source_id, attachment_id=attachment.id)
    return ()


def restore(r, effect):
    row = effect.validate_in_state(r.state, r.registry)
    target = r.state.entities[effect.link.entity_id]
    if not any(e.id == effect.link.enchantment_id for e in target.enchantments):
        return ()
    remove_attachments(target, enchantment_predicate=lambda e: e.id == effect.link.enchantment_id,
        ability_predicate=lambda a: False)
    r.emit('cost_modified', target_id=target.id, source_id=row.capture.carrier_id,
        attachment_id=effect.link.enchantment_id)
    return ()


def register(mechanics):
    mechanics.register(SetRandomHandCostForDeathrattle, set_cost)
    mechanics.register(RestoreRememberedCost, restore)
