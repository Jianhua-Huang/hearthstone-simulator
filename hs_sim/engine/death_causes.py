"""Fatal transitions, incarnation resets and immutable death attribution (R-110)."""
from .model import CardType, DeathCause, DeathRecord, HealthFlow, Zone, _int, _name
from .health_outcomes import result_from_payload, _kill_result_value


KINDS = {'damage', 'poison', 'destroy', 'health_loss', 'health_state', 'durability', 'replaced'}


def validate_cause(c):
    if c.kind not in KINDS:
        raise ValueError('Unknown death cause kind')
    _name(c.reason, 'death cause reason')
    _name(c.target_card_id, 'death target card')
    for name in ('target_id', 'turn'): _int(getattr(c, name), name, 1)
    for name in ('target_zone_epoch', 'target_entered_order'): _int(getattr(c, name), name, 0)
    for name in ('target_controller', 'active_player'):
        if type(getattr(c, name)) is not int or getattr(c, name) not in (1, 2):
            raise ValueError('Invalid death cause player')
    source=(c.source_card_id, c.source_controller, c.source_zone_epoch, c.source_entered_order)
    if c.source_id is None:
        if any(v is not None for v in source): raise ValueError('Source-less cause has metadata')
    else:
        _int(c.source_id, 'death source', 1); _name(c.source_card_id, 'death source card')
        if type(c.source_controller) is not int or c.source_controller not in (1, 2):
            raise ValueError('Invalid death source controller')
        _int(c.source_zone_epoch, 'death source epoch', 0)
        _int(c.source_entered_order, 'death source order', 0)
    if type(c.result) is not tuple: raise ValueError('Death result must be frozen')
    if c.kind not in ('damage', 'poison'):
        if c.result: raise ValueError('Non-damage death cannot claim a damage result')
        return
    v=result_from_payload(c.result)
    if (v.target_id, v.target_card_id, v.target_controller, v.target_zone_epoch, v.target_entered_order,
        v.turn, v.active_player, v.source_id, v.source_card_id, v.source_controller, v.source_zone_epoch, v.source_entered_order) != (
        c.target_id, c.target_card_id, c.target_controller, c.target_zone_epoch, c.target_entered_order,
        c.turn, c.active_player, c.source_id, *source):
        raise ValueError('Death cause and captured result disagree')
    if v.flow != HealthFlow.DAMAGE.value or v.prevention or v.health_before <= 0 or v.doomed_before:
        raise ValueError('Death cause requires a new unprevented fatal damage transition')
    if c.kind == 'damage' and (v.health_after > 0 or v.health_lost < v.health_before):
        raise ValueError('Numeric death requires lethal health loss')
    if c.kind == 'poison' and (not v.doomed_after or v.health_after <= 0):
        raise ValueError('Poison-only death requires newly doomed positive health')


def dying(e):
    return (not e.starship_building and e.zone in (Zone.BOARD, Zone.WEAPON, Zone.HERO) and
            (e.doomed or (e.durability <= 0 if e.kind in (CardType.WEAPON, CardType.LOCATION) else e.health <= 0)))


def source_fields(source):
    return dict(source_id=source.id, source_card_id=source.card_id, source_controller=source.controller,
                source_zone_epoch=source.zone_epoch, source_entered_order=source.entered_order) if source else {}


def capture(state, e, kind, reason, source=None, result=()):
    return DeathCause(kind, reason, e.id, e.card_id, e.controller, e.zone_epoch, e.entered_order,
                      state.turn, state.active_player, **source_fields(source), result=result)


def sync_state(state, reason='checkpoint', *, cause_source=None, cause_target_id=None):
    """Deterministic state normalizer, shared with detached event projection."""
    for entity in state.entities.values():
        if not dying(entity):
            entity.death_cause = None
        elif entity.death_cause is None:
            kind = 'durability' if entity.kind in (CardType.WEAPON, CardType.LOCATION) and not entity.doomed else 'health_state'
            source = cause_source if cause_target_id == entity.id else None
            entity.death_cause = capture(state, entity, kind, reason, source)


def sync(r, reason='checkpoint'):
    sync_state(r.state, reason, cause_source=getattr(r, '_cause_source', None),
               cause_target_id=getattr(r, '_cause_target_id', None))


def health_transition(state, e, payload):
    """Called per packet, before later packets or intrinsic lifesteal settle."""
    v=result_from_payload(payload)
    if not dying(e):
        e.death_cause = None
    elif e.death_cause is None:
        if v.flow == HealthFlow.DAMAGE and not v.prevention and v.health_before > 0 and not v.doomed_before:
            kind = 'damage' if v.health_after <= 0 and v.health_lost >= v.health_before else 'poison'
            # Eligibility/source facts are frozen for the batch; target identity is current.
            e.death_cause = capture(state, e, kind, 'health_packet', state.entities.get(v.source_id), payload)
        else:
            e.death_cause = capture(state, e, 'health_state', 'preexisting_health_state')


def mark(r, e, kind, reason, source_id=None):
    source = r.state.entities.get(source_id)
    if source_id is not None and source is None:
        raise ValueError('Death cause source does not exist')
    if e.death_cause is None:
        e.death_cause = capture(r.state, e, kind, reason, source)


def was_honorably_killed(record):
    """Query an actual death, never infer from its later final health."""
    if record is None: return False
    if type(record) is not DeathRecord: raise ValueError('Expected DeathRecord')
    record.__post_init__()
    cause = record.cause
    if cause.kind != 'damage' or cause.source_id is None: return False
    v = _kill_result_value(cause.health_result, cause.source_id)
    return v is not None and v.target_controller != v.source_controller and v.health_lost == v.health_before


def validate_in_state(state, registry, cause):
    cause.__post_init__()
    registry.card(cause.target_card_id)
    if cause.turn > state.turn or cause.target_id not in state.entities:
        raise ValueError('Death cause has missing target or future turn')
    if cause.target_zone_epoch > state.entities[cause.target_id].zone_epoch or cause.target_entered_order >= state.next_order:
        raise ValueError('Death cause has future target incarnation')
    if cause.source_id is not None:
        registry.card(cause.source_card_id)
        source=state.entities.get(cause.source_id)
        if source is None or cause.source_zone_epoch > source.zone_epoch or cause.source_entered_order >= state.next_order:
            raise ValueError('Death cause has missing source or future incarnation')
    result=cause.health_result
    if result and result.target_kind != registry.card(cause.target_card_id).kind.value:
        raise ValueError('Death result target kind disagrees with its definition')
    if result and result.weapon_id is not None:
        weapon=state.entities.get(result.weapon_id)
        if weapon is None or weapon.kind != CardType.WEAPON or result.weapon_zone_epoch > weapon.zone_epoch or result.weapon_entered_order >= state.next_order:
            raise ValueError('Death cause has invalid captured weapon')
