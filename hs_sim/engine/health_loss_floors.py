"""Explicit EFFECT debit floor at atomic LoseHealth delivery (local M6 profile).

This is independent of damage, costs, stat writes and explicit destruction.
Accepted rows and replacement eligibility are frozen; HP allowance is live.
Private compact results retain original facts through lifecycle changes/Retry.
They establish bounded internal consistency, not unsigned origin authenticity.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, is_dataclass

from .effects import Effect, _integer, _source
from .lifecycle import active_abilities, attachment_id
from .model import (AbilityInstance, CardType, Event, GameState, HealthLossFloorSpec,
                    HealthLossKind, Keyword, Zone)
from .resource_operations import SourceAllocationFact, allocation_from_payload


PROFILE = 'effect_live_debit_max_original_rows'


def validate_face(card):
    if (card.kind not in (CardType.HERO, CardType.MINION, CardType.WEAPON) or card.starship_for or
            Keyword.MAGNETIC in card.keywords or Keyword.STARSHIP_PIECE in card.keywords):
        raise ValueError('EFFECT health floor requires an ordinary non-composite carrier')


def validate_carrier(registry, card_id, kind, abilities, components=()):
    rows = tuple(a for a in abilities if a.kind == 'health_loss_floor')
    if not rows:
        return
    card = registry.card(card_id)
    validate_face(card)
    if kind != card.kind or components:
        raise ValueError('Composite EFFECT health floor carrier is unsupported')
    for a in rows:
        a.__post_init__()
        if a.origin == 'printed' and (a.health_loss_floor not in card.health_loss_floors or
                a.source_id is None or a.expires_turn is not None or a.consumed):
            raise ValueError('Printed EFFECT floor differs from its native declaration')


@dataclass(frozen=True)
class GrantHealthLossFloor(Effect):
    target_id: int
    spec: HealthLossFloorSpec
    source_id: int | None = None
    expires_turn: int | None = None

    def __post_init__(self):
        _integer(self.target_id, 'EFFECT floor holder', 1)
        _source(self.source_id)
        if type(self.spec) is not HealthLossFloorSpec:
            raise ValueError('EFFECT floor requires its exact typed specification')
        self.spec.__post_init__()
        if self.expires_turn is not None:
            _integer(self.expires_turn, 'EFFECT floor expiry', 1)


def validate_grant(state, registry, effect):
    effect.__post_init__()
    target = state.entities.get(effect.target_id)
    if target is None or (effect.source_id is not None and effect.source_id not in state.entities):
        raise ValueError('EFFECT floor grant has an unknown/future reference')
    validate_face(registry.card(target.card_id))
    if target.components:
        raise ValueError('Composite EFFECT floor grant is unsupported')


def grant(r, effect):
    from .resolver import validate_attachment_source
    validate_grant(r.state, r.registry, effect)
    validate_attachment_source(r, effect.source_id, effect.expires_turn)
    e = r.state.entities[effect.target_id]
    if not eligible(e):
        r.stale(effect, e.id)
        return ()
    a = AbilityInstance(attachment_id(r.state), 'health_loss_floor', source_id=effect.source_id,
        health_loss_floor=effect.spec, expires_turn=effect.expires_turn)
    e.abilities.append(a)
    r.emit('ability_granted', source_id=effect.source_id, target_id=e.id,
        ability_id=a.id, ability_kind=a.kind)
    return ()


def eligible(e):
    return bool(e.active and not e.doomed and
        ((e.kind == CardType.MINION and e.zone == Zone.BOARD and e.health > 0) or
         (e.kind == CardType.HERO and e.zone == Zone.HERO and e.health > 0) or
         (e.kind == CardType.WEAPON and e.zone == Zone.WEAPON and e.durability > 0)))


@dataclass(frozen=True)
class LossFloorAcceptedRow:
    ability: AbilityInstance
    carrier: SourceAllocationFact

    def __post_init__(self):
        if type(self.ability) is not AbilityInstance or type(self.carrier) is not SourceAllocationFact:
            raise ValueError('EFFECT floor requires complete typed original row/carrier')
        self.ability.__post_init__()
        self.carrier.__post_init__()
        if self.ability.kind != 'health_loss_floor' or self.ability.consumed:
            raise ValueError('Accepted EFFECT floor row is not a live floor attachment')
        if (self.carrier.kind, self.carrier.zone) not in ((CardType.MINION, Zone.BOARD),
                (CardType.HERO, Zone.HERO), (CardType.WEAPON, Zone.WEAPON)):
            raise ValueError('Accepted EFFECT floor carrier has an unsupported zone/kind')


@dataclass(frozen=True)
class LossFloorPlan:
    rows: tuple[LossFloorAcceptedRow, ...]
    floor: int
    turn: int
    active_player: int
    next_attachment_id: int
    source: SourceAllocationFact | None
    target: SourceAllocationFact
    replacement_ability: AbilityInstance | None
    replacement_carrier: SourceAllocationFact | None
    profile: str = PROFILE

    def __post_init__(self):
        from .effects import _player
        from .health_rules import relation_matches
        for n in ('floor', 'turn', 'next_attachment_id'):
            _integer(getattr(self, n), n, 1)
        _player(self.active_player)
        if type(self.profile) is not str or self.profile != PROFILE:
            raise ValueError('Unknown EFFECT floor union profile')
        if type(self.target) is not SourceAllocationFact:
            raise ValueError('EFFECT floor target requires original allocation facts')
        self.target.__post_init__()
        if (self.target.kind, self.target.zone) not in ((CardType.HERO, Zone.HERO), (CardType.MINION, Zone.BOARD)):
            raise ValueError('EFFECT loss target must be a live character incarnation')
        if self.source is not None:
            if type(self.source) is not SourceAllocationFact:
                raise ValueError('EFFECT loss source requires typed original facts')
            self.source.__post_init__()
            self.same_bounds(self.source)
        if type(self.rows) is not tuple or not self.rows or any(type(r) is not LossFloorAcceptedRow for r in self.rows):
            raise ValueError('EFFECT floor plan requires nonempty typed rows')
        ids = tuple(r.ability.id for r in self.rows)
        if ids != tuple(sorted(set(ids))):
            raise ValueError('EFFECT floor rows require unique allocation order')
        for r in self.rows:
            r.__post_init__()
            self.same_bounds(r.carrier)
            self.check_ability(r.ability)
            spec = r.ability.health_loss_floor
            if (self.target.kind not in spec.target_kinds or not relation_matches(spec.target_relation,
                    self.target.entity_id, self.target.controller, r.carrier.entity_id, r.carrier.controller)):
                raise ValueError('EFFECT floor row differs from original target matching')
        if self.floor != max(r.ability.health_loss_floor.floor for r in self.rows):
            raise ValueError('EFFECT floor differs from original maximum row union')
        if (self.replacement_ability is None) != (self.replacement_carrier is None):
            raise ValueError('EFFECT floor replacement requires both row and carrier')
        if self.replacement_ability is not None:
            a, c = self.replacement_ability, self.replacement_carrier
            if type(a) is not AbilityInstance or type(c) is not SourceAllocationFact:
                raise ValueError('EFFECT floor replacement requires typed original facts')
            a.__post_init__(); c.__post_init__(); self.check_ability(a); self.same_bounds(c)
            if (a.kind != 'health_loss_replacement' or a.consumed or c.kind != CardType.MINION or c.zone != Zone.BOARD or
                    self.target.kind != CardType.HERO or c.controller != self.target.controller or
                    HealthLossKind.EFFECT not in a.health_loss_replacement.kinds or
                    (a.health_loss_replacement.own_turn_only and self.active_player != self.target.controller)):
                raise ValueError('Replacement differs from original EFFECT eligibility')

    def same_bounds(self, c):
        if (c.next_entity_id, c.next_order) != (self.target.next_entity_id, self.target.next_order):
            raise ValueError('Loss acceptance facts have different original allocation windows')

    def check_ability(self, a):
        if (a.id >= self.next_attachment_id or
                (a.source_id is not None and a.source_id >= self.target.next_entity_id) or
                (a.expires_turn is not None and a.expires_turn < self.turn)):
            raise ValueError('Accepted loss ability is future or expired in its own window')


def capture_plan(state, registry, target, source_id, replacement):
    from .health_rules import relation_matches
    rows = []
    for e in state.entities.values():
        if not eligible(e):
            continue
        for a in active_abilities(e, 'health_loss_floor'):
            spec = a.health_loss_floor
            if target.kind in spec.target_kinds and relation_matches(spec.target_relation,
                    target.id, target.controller, e.id, e.controller):
                validate_carrier(registry, e.card_id, e.kind, (a,), e.components)
                rows.append(LossFloorAcceptedRow(deepcopy(a), SourceAllocationFact.capture(state, e)))
    if not rows:
        return None
    rows.sort(key=lambda r: r.ability.id)
    carrier = None if replacement is None else state.entities[replacement.source_id]
    ability = None if carrier is None else next(a for a in carrier.abilities if a.id == replacement.ability_id)
    return LossFloorPlan(tuple(rows), max(r.ability.health_loss_floor.floor for r in rows), state.turn,
        state.active_player, state.next_attachment_id, SourceAllocationFact.capture(state, state.entities.get(source_id)),
        SourceAllocationFact.capture(state, target), deepcopy(ability), SourceAllocationFact.capture(state, carrier))


@dataclass(frozen=True)
class LossFloorResult:
    plan: LossFloorPlan
    event_sequence: int
    action: int
    requested_loss: int
    prevented_by_floor: int
    accepted_loss: int
    actual_lost: int
    health_replaced: int
    health_before: int
    health_after: int
    max_before: int
    max_after: int
    damage_before: int
    damage_after: int
    doomed_before: bool
    doomed_after: bool

    def __post_init__(self):
        if type(self.plan) is not LossFloorPlan:
            raise ValueError('Loss floor result requires typed original acceptance')
        self.plan.__post_init__()
        _integer(self.event_sequence, 'loss result sequence', 1)
        for n in ('action', 'requested_loss', 'prevented_by_floor', 'accepted_loss', 'actual_lost',
                'health_replaced', 'max_before', 'max_after', 'damage_before', 'damage_after'):
            _integer(getattr(self, n), n, 0)
        for n in ('health_before', 'health_after'):
            _integer(getattr(self, n), n)
        if type(self.doomed_before) is not bool or type(self.doomed_after) is not bool:
            raise ValueError('Loss floor result Doom requires booleans')
        allowed = min(self.requested_loss, max(0, self.health_before-self.plan.floor))
        replaced = allowed if self.plan.replacement_ability is not None else 0
        if (self.accepted_loss != allowed or self.prevented_by_floor != self.requested_loss-allowed or
                self.health_replaced != replaced or self.actual_lost != allowed-replaced or
                self.damage_after != self.damage_before+self.actual_lost or self.max_after != self.max_before+replaced or
                self.health_before != self.max_before-self.damage_before or self.health_after != self.max_after-self.damage_after or
                self.doomed_after != self.doomed_before):
            raise ValueError('Non-damage loss result violates live allowance/conservation')


def project_floor_loss(state, target, amount, kind, source_id, replacement, plan, event_sequence):
    from .health_loss import HealthLossProjection, project_loss
    if type(plan) is not LossFloorPlan:
        raise ValueError('Floor projection requires a typed accepted plan')
    plan.__post_init__()
    _integer(amount, 'effect loss projection amount', 0)
    fact = SourceAllocationFact.capture(state, target)
    # Target identity/incarnation must still be the accepted one. Allocation
    # clocks may advance, but a later form/body never inherits an old plan.
    if (type(kind) is not HealthLossKind or kind != HealthLossKind.EFFECT or
            (fact.entity_id, fact.card_id, fact.kind, fact.owner, fact.controller, fact.zone, fact.zone_epoch, fact.entered_order) !=
            (plan.target.entity_id, plan.target.card_id, plan.target.kind, plan.target.owner, plan.target.controller,
             plan.target.zone, plan.target.zone_epoch, plan.target.entered_order) or
            source_id != (None if plan.source is None else plan.source.entity_id) or
            (replacement is None) != (plan.replacement_ability is None) or
            (replacement is not None and (replacement.source_id, replacement.ability_id) !=
                (plan.replacement_carrier.entity_id, plan.replacement_ability.id))):
        raise ValueError('Floor projection differs from accepted EFFECT identities')
    allowed = min(amount, max(0, target.health-plan.floor))
    projected = project_loss(state, target, allowed, kind, source_id, replacement)
    after = projected.target
    replaced = allowed if replacement is not None else 0
    result = LossFloorResult(plan, event_sequence, state.action_number, amount, amount-allowed, allowed,
        allowed-replaced, replaced, target.health, after.health, target.max_health, after.max_health,
        target.damage, after.damage, target.doomed, after.doomed)
    return HealthLossProjection(after, projected.next_attachment_id, projected.events, result)


def result_payload(result):
    def freeze(v):
        if type(v) is dict:
            return tuple((k, freeze(value)) for k, value in v.items())
        if isinstance(v, (list, tuple)):
            return tuple(freeze(value) for value in v)
        return v
    return freeze(asdict(result))


def result_from_payload(raw):
    from .serialization import _ability_from_dict
    def obj(v, cls):
        if (type(v) is not tuple or any(type(r) is not tuple or len(r) != 2 or type(r[0]) is not str for r in v) or
                len(dict(v)) != len(v) or set(dict(v)) != {f.name for f in fields(cls)}):
            raise ValueError('Loss floor payload requires exact immutable declared fields')
        return dict(v)
    def thaw(v):
        if type(v) is tuple:
            if v and all(type(r) is tuple and len(r) == 2 and type(r[0]) is str for r in v):
                if len(dict(v)) != len(v):
                    raise ValueError('Duplicate loss floor ability payload fields')
                return {k: thaw(value) for k, value in v}
            return [thaw(value) for value in v]
        return v
    out = obj(raw, LossFloorResult)
    p = obj(out['plan'], LossFloorPlan)
    if type(p['rows']) is not tuple:
        raise ValueError('Loss floor rows must be immutable')
    rows = []
    for raw_row in p['rows']:
        r = obj(raw_row, LossFloorAcceptedRow)
        rows.append(LossFloorAcceptedRow(_ability_from_dict(thaw(r['ability'])), allocation_from_payload(r['carrier'])))
    p['rows'] = tuple(rows)
    for key in ('target', 'source', 'replacement_carrier'):
        p[key] = allocation_from_payload(p[key])
    if p['replacement_ability'] is not None:
        p['replacement_ability'] = _ability_from_dict(thaw(p['replacement_ability']))
    out['plan'] = LossFloorPlan(**p)
    return LossFloorResult(**out)


def loss_floor_result(event):
    raw = dict(event.data).get('loss_floor_result')
    if event.kind != 'health_loss_floor_resolved':
        if raw is not None:
            raise ValueError('EFFECT floor receipt is attached to an unrelated event')
        return None
    if raw is None:
        raise ValueError('EFFECT floor event is missing its compact original receipt')
    result = result_from_payload(raw)
    if (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount) != (
            result.event_sequence, result.action, None if result.plan.source is None else result.plan.source.entity_id,
            result.plan.target.entity_id, result.plan.target.controller, result.actual_lost):
        raise ValueError('Loss floor event differs from its accepted result')
    return result


def validate_fact(state, registry, c):
    c.__post_init__()
    if registry.card(c.card_id).kind != c.kind or c.next_entity_id > state.next_entity_id or c.next_order > state.next_order:
        raise ValueError('Loss floor allocation is unregistered or future')
    current = state.entities.get(c.entity_id)
    if current is not None:
        if current.owner != c.owner or c.zone_epoch > current.zone_epoch:
            raise ValueError('Loss floor allocation has foreign owner/future incarnation')
        if c.zone_epoch == current.zone_epoch and (c.card_id, c.kind) != (current.card_id, current.kind):
            raise ValueError('Loss floor original face differs in the same incarnation')


def validate_plan(state, registry, plan):
    plan.__post_init__()
    if plan.turn > state.turn or plan.next_attachment_id > state.next_attachment_id:
        raise ValueError('Loss floor plan exceeds its original turn/attachment domain')
    facts = [plan.target, plan.source, plan.replacement_carrier, *(r.carrier for r in plan.rows)]
    for c in facts:
        if c is not None:
            validate_fact(state, registry, c)
    allocated = {a.id: (e, a) for e in state.entities.values() for a in e.abilities}
    def check_row(a, c):
        known = allocated.get(a.id)
        if known is not None and (known[0].id != c.entity_id or known[1] != a):
            raise ValueError('Loss floor accepted row borrows another physical attachment')
    for r in plan.rows:
        validate_carrier(registry, r.carrier.card_id, r.carrier.kind, (r.ability,))
        check_row(r.ability, r.carrier)
    if plan.replacement_ability is not None:
        a, c = plan.replacement_ability, plan.replacement_carrier
        if a.origin == 'printed' and a.health_loss_replacement not in registry.card(c.card_id).health_loss_replacements:
            raise ValueError('Accepted replacement differs from its original printed row')
        check_row(a, c)


def validate_result(state, registry, result):
    result.__post_init__()
    if result.action > state.action_number:
        raise ValueError('Loss floor result has a future action')
    validate_plan(state, registry, result.plan)


def validate_event_results(state, registry, events):
    for event in events:
        result = loss_floor_result(event)
        if result is not None:
            validate_result(state, registry, result)


def validate_frame_references(state, registry, value):
    from .registry import RuleContext
    from .paid_hand_acceptance import PaidHandChoiceBoundaryProof
    from .continuations import FrameCodec
    def visit(item, scope, depth):
        if depth > FrameCodec.MAX_DEPTH:
            raise ValueError('Loss floor frame exceeds depth limit')
        if type(item) is GrantHealthLossFloor:
            validate_grant(scope, registry, item); return
        if type(item) is LossFloorPlan:
            validate_plan(scope, registry, item); return
        if type(item) is LossFloorResult:
            validate_result(scope, registry, item); return
        if type(item) is Event:
            result = loss_floor_result(item)
            if result is not None:
                validate_result(scope, registry, result)
            return
        if type(item) is RuleContext:
            for f in fields(item):
                if f.name != 'state':
                    visit(getattr(item, f.name), item.state, depth+1)
            return
        if type(item) is PaidHandChoiceBoundaryProof:
            visit(item.work, item.state, depth+1); return
        if type(item) is GameState:
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                visit(child, scope, depth+1)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child, scope, depth+1)
        elif is_dataclass(item) and not isinstance(item, type):
            for f in fields(item):
                visit(getattr(item, f.name), scope, depth+1)
    visit(value, state, 0)


def register(mechanics):
    mechanics.register(GrantHealthLossFloor, grant)
    for cls in (LossFloorAcceptedRow, LossFloorPlan, LossFloorResult):
        mechanics.register_payload_type(cls)
