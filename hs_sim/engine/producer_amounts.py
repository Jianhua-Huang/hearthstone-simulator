"""Source-independent additions to logical random summon producers.

The batch owns its original request and the accepted amount fact separately.
This is a local bounded policy pending CN calibration, not origin authentication.
"""
from dataclasses import dataclass

from .model import CardType, PlayerEffect, ProducerQuantitySpec, SummonProducerProfile, _int
from .summon_quantities import SummonCause


@dataclass(frozen=True)
class ProducerAmountDecision:
    instance: PlayerEffect
    spec_index: int
    declaration: ProducerQuantitySpec
    matched: bool
    reason: str
    additional: int

    def __post_init__(self):
        if type(self.instance) is not PlayerEffect or type(self.declaration) is not ProducerQuantitySpec:
            raise ValueError('Typed producer amount source and declaration required')
        self.instance.__post_init__(); self.declaration.__post_init__()
        _int(self.spec_index, 'producer declaration index', 0)
        _int(self.additional, 'producer contribution', 0)
        if type(self.matched) is not bool or self.reason not in (
                'qualified', 'other_unit', 'source_origin', 'source_kind', 'zero_base'):
            raise ValueError('Explicit producer qualification decision required')
        if self.matched != (self.reason == 'qualified') or self.additional != (
                self.declaration.additional if self.matched else 0):
            raise ValueError('Producer amount differs from its qualification decision')


def qualification(profile, declaration, cause, source_kind, base_count):
    if declaration.unit_id != profile.unit_id:
        return 'other_unit'
    if cause.origin not in profile.source_origins:
        return 'source_origin'
    if source_kind not in profile.source_types:
        return 'source_kind'
    if base_count == 0 and not profile.zero_base_eligible:
        return 'zero_base'
    return 'qualified'


@dataclass(frozen=True)
class AcceptedProducerAmount:
    batch_id: int
    event_cursor: int
    turn: int
    action: int
    next_entity_id: int
    next_attachment_id: int
    next_order: int
    profile: SummonProducerProfile
    cause: SummonCause
    recipient_id: int
    source_kind: CardType
    base_count: int
    inventory: tuple[PlayerEffect, ...]
    decisions: tuple[ProducerAmountDecision, ...]
    total: int
    family: str = 'pool'

    def __post_init__(self):
        for name in ('batch_id', 'turn', 'next_entity_id', 'next_attachment_id', 'next_order'):
            _int(getattr(self, name), 'producer acceptance ' + name, 1)
        for name in ('event_cursor', 'action', 'base_count', 'total'):
            _int(getattr(self, name), 'producer acceptance ' + name, 0)
        if type(self.recipient_id) is not int or self.recipient_id not in (1, 2):
            raise ValueError('Producer acceptance recipient must be a player')
        if type(self.profile) is not SummonProducerProfile or type(self.cause) is not SummonCause:
            raise ValueError('Typed logical producer profile and cause required')
        self.profile.__post_init__(); self.cause.__post_init__()
        modes = {'pool': 'random_board_batch', 'ordered_group': 'ordered_board_group'}
        if (type(self.family) is not str or self.family not in modes or
                self.profile.mode != modes[self.family] or type(self.source_kind) is not CardType):
            raise ValueError('Unsupported or borrowed logical producer amount acceptance family')
        if self.cause.turn > self.turn or self.cause.action > self.action:
            raise ValueError('Producer amount cause is newer than its acceptance')
        if self.cause.source.entity_id >= self.next_entity_id:
            raise ValueError('Producer amount carries a future causing entity')
        if type(self.inventory) is not tuple or any(type(e) is not PlayerEffect for e in self.inventory):
            raise ValueError('Complete ordered original player-effect inventory required')
        ids = [e.id for e in self.inventory]
        orders = [e.entered_order for e in self.inventory]
        if ids != sorted(set(ids)) or orders != sorted(set(orders)):
            raise ValueError('Producer amount inventory has duplicate or reordered identities')
        by_id = {e.id: e for e in self.inventory}
        for instance in self.inventory:
            instance.__post_init__()
            if (instance.id >= self.next_attachment_id or instance.source_id >= self.next_entity_id or
                    instance.entered_order >= self.next_order or instance.created_turn > self.turn):
                raise ValueError('Producer amount inventory contains a future source')
        if type(self.decisions) is not tuple or any(type(d) is not ProducerAmountDecision for d in self.decisions):
            raise ValueError('Complete typed producer amount decisions required')
        keys = []
        indices = {}
        for decision in self.decisions:
            decision.__post_init__()
            if by_id.get(decision.instance.id) != decision.instance:
                raise ValueError('Producer declaration borrowed another effect instance')
            reason = qualification(self.profile, decision.declaration, self.cause, self.source_kind, self.base_count)
            if decision.reason != reason:
                raise ValueError('Producer qualification differs from its original profile and cause')
            keys.append((decision.instance.id, decision.spec_index))
            indices.setdefault(decision.instance.id, []).append(decision.spec_index)
        if keys != sorted(set(keys)) or any(v != list(range(len(v))) for v in indices.values()):
            raise ValueError('Producer declarations must retain each original ordered index')
        if self.total != self.base_count + sum(d.additional for d in self.decisions):
            raise ValueError('Derived producer total differs from complete original contributions')


def request_profile(registry, effect):
    key = getattr(effect, 'producer_profile_id', None)
    if key is None:
        return None
    profile = registry.summon_producer_profile(key)
    if profile.mode != 'random_board_batch':
        raise ValueError('Declared logical summon mode is not yet implemented by random batches')
    if type(effect.cause) is not SummonCause or effect.destination != 'board':
        raise ValueError('Logical summon profile requires an attributed board batch')
    return profile


def source_kind(registry, cause):
    # Automatic spell casts can have a different physical scheduling source.
    card_id = cause.cast_card_id if cause.origin == 'spell_cast' else cause.source.card_id
    return registry.card(card_id).kind


def decisions(registry, profile, cause, kind, base_count, inventory):
    result = []
    for instance in inventory:
        spec = registry.player_effect(instance.spec_id)
        for index, declaration in enumerate(spec.producer_quantities):
            reason = qualification(profile, declaration, cause, kind, base_count)
            matched = reason == 'qualified'
            result.append(ProducerAmountDecision(instance, index, declaration, matched, reason,
                declaration.additional if matched else 0))
    return tuple(result)


def capture(r, effect):
    profile = request_profile(r.registry, effect)
    if profile is None:
        return None
    inventory = tuple(r.player(effect.cause.player_id).player_effects)
    kind = source_kind(r.registry, effect.cause)
    rows = decisions(r.registry, profile, effect.cause, kind, effect.count, inventory)
    state = r.state
    value = AcceptedProducerAmount(state.next_pool_summon_id, len(r.game._events), state.turn,
        state.action_number, state.next_entity_id, state.next_attachment_id, state.next_order,
        profile, effect.cause, effect.player_id, kind, effect.count, inventory, rows,
        effect.count + sum(row.additional for row in rows))
    validate(r.registry, value)
    return value


def capture_group(r, effect):
    if effect.producer_profile_id is None:
        return None
    profile = r.registry.summon_producer_profile(effect.producer_profile_id)
    if profile.mode != 'ordered_board_group':
        raise ValueError('Whole group amount requires its own explicit producer family')
    group = effect.group
    inventory = tuple(r.player(group.cause.player_id).player_effects)
    kind = source_kind(r.registry, group.cause)
    base_count = len(group.members)
    rows = decisions(r.registry, profile, group.cause, kind, base_count, inventory)
    state = r.state
    value = AcceptedProducerAmount(state.next_ordered_group_id, len(r.game._events), state.turn,
        state.action_number, state.next_entity_id, state.next_attachment_id, state.next_order,
        profile, group.cause, group.player_id, kind, base_count, inventory, rows,
        base_count + sum(row.additional for row in rows), family='ordered_group')
    validate(r.registry, value)
    return value


def validate(registry, value):
    if type(value) is not AcceptedProducerAmount:
        raise ValueError('Typed original producer amount fact required')
    value.__post_init__()
    if registry.summon_producer_profile(value.profile.id) != value.profile:
        raise ValueError('Producer amount profile differs from its frozen registry')
    if source_kind(registry, value.cause) != value.source_kind:
        raise ValueError('Producer amount changed its original causing card type')
    for instance in value.inventory:
        registry.card(instance.source_card_id)
        spec = registry.player_effect(instance.spec_id)
        if ((spec.duration is None) != (instance.remaining_turns is None) or
                (spec.duration is not None and instance.remaining_turns > spec.duration)):
            raise ValueError('Original producer effect lifetime differs from its declaration')
    expected = decisions(registry, value.profile, value.cause, value.source_kind, value.base_count, value.inventory)
    if expected != value.decisions:
        raise ValueError('Producer amount lost or changed a complete original declaration decision')


def validate_record(registry, root):
    fact = root.producer_amount
    if (root.spec.producer_profile_id is None) != (fact is None):
        raise ValueError('Logical batch lost or borrowed its original amount fact')
    if fact is None:
        return
    if fact.family != 'pool':
        raise ValueError('Pool amount borrowed another producer family')
    validate(registry, fact)
    if (fact.profile.id != root.spec.producer_profile_id or fact.cause != root.spec.cause or
            fact.base_count != root.spec.count or fact.recipient_id != root.spec.basis.player_id or
            (fact.batch_id, fact.event_cursor, fact.turn, fact.action) !=
            (root.id, root.event_cursor, root.turn, root.action)):
        raise ValueError('Producer amount borrowed another original request or acceptance window')


def from_dict(value):
    from .serialization import _list, _row
    from .summon_quantities import from_dict as cause_from_dict
    row = _row(value, AcceptedProducerAmount)
    profile = _row(row['profile'], SummonProducerProfile)
    profile['source_origins'] = tuple(_list(profile['source_origins'], 'producer origins'))
    profile['source_types'] = tuple(CardType(k) for k in _list(profile['source_types'], 'producer source types'))
    row['profile'] = SummonProducerProfile(**profile)
    row['cause'] = cause_from_dict(SummonCause, row['cause'])
    row['source_kind'] = CardType(row['source_kind'])
    from .serialization import player_effect_from_dict
    row['inventory'] = tuple(player_effect_from_dict(e) for e in _list(row['inventory'], 'producer inventory'))
    rows = []
    for data in _list(row['decisions'], 'producer decisions'):
        decision = _row(data, ProducerAmountDecision)
        decision['instance'] = player_effect_from_dict(decision['instance'])
        decision['declaration'] = ProducerQuantitySpec(**_row(decision['declaration'], ProducerQuantitySpec))
        rows.append(ProducerAmountDecision(**decision))
    row['decisions'] = tuple(rows)
    return AcceptedProducerAmount(**row)
