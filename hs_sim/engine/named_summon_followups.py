"""A fixed named entry's exact delivery owns its ordinary continuation."""
from dataclasses import asdict, dataclass, replace
import json
from .board_presence import resolve_board_presence
from .effects import Effect, _behavior, _integer
from .errors import ResolutionError
from .model import BoardPresenceReference

EVENT = 'named_summon_followup_started'


@dataclass(frozen=True)
class ContinueNamedMinion(Effect):
    root_id: int
    index: int
    beneficiary: BoardPresenceReference
    behavior_id: str

    def __post_init__(self):
        _integer(self.root_id, 'original named root', 1)
        _integer(self.index, 'named delivery', 0)
        if type(self.beneficiary) is not BoardPresenceReference:
            raise ValueError('Named continuation requires its original delivered residence')
        self.beneficiary.__post_init__()
        _behavior(self.behavior_id)


def decode(value):
    from .serialization import _row
    row = dict(_row(json.loads(value), ContinueNamedMinion))
    row['beneficiary'] = BoardPresenceReference(**_row(row['beneficiary'], BoardPresenceReference))
    return ContinueNamedMinion(**row)


def for_root(root, effect):
    from .summon_quantities import SummonEntryMaterial
    effect.__post_init__()
    material = None if root.selected is None else root.request.materials[root.selected]
    if root.id != effect.root_id or type(material) is not SummonEntryMaterial or material.on_summon != effect.behavior_id:
        raise ValueError('Named continuation differs from its exact accepted material')
    if effect.index >= len(root.deliveries):
        raise ValueError('Named continuation precedes its actual delivery')
    delivery = root.deliveries[effect.index]
    fact = delivery.entity
    if delivery.outcome != 'delivered' or (fact.entity_id, fact.entered_order) != (
            effect.beneficiary.entity_id, effect.beneficiary.presence_id):
        raise ValueError('Named continuation borrowed another delivery or residence')
    return delivery


def followup_record(state, registry, effect):
    from .summon_quantities import record
    registry.behavior(effect.behavior_id)
    root = record(state, effect.root_id)
    return root, for_root(root, effect)


def continue_named_minion(r, effect):
    from .summon_quantities import update
    root, delivery = followup_record(r.state, r.registry, effect)
    if root.status != 'active' or delivery.followup_started:
        raise ResolutionError('Named continuation already started or closed')
    rows = list(root.deliveries)
    rows[effect.index] = replace(delivery, followup_started=True)
    update(r.state, root, deliveries=tuple(rows))
    event = r.emit(EVENT, source_id=root.request.cause.source.entity_id,
        target_id=delivery.entity.entity_id, player_id=root.request.player_id,
        followup=json.dumps(asdict(effect), ensure_ascii=False, sort_keys=True, separators=(',', ':')),
        _capture=False)
    from .pool_summons import PoolSummonBasis
    basis = root.request.pool_basis
    original_delivery = type(basis) is PoolSummonBasis and basis.followup_policy == 'original_delivery'
    entity = resolve_board_presence(r.state, effect.beneficiary)
    if not original_delivery and (entity is None or not entity.active or entity.health <= 0 or entity.doomed or entity.controller != root.request.player_id):
        r.stale(effect, effect.beneficiary.entity_id)
        return ()
    return (r.call(effect.behavior_id, root.request.cause.source.entity_id, root.request.player_id,
        target_id=delivery.entity.entity_id, event=event),)


def original_named_reference(context):
    from .summon_quantities import record
    event = context.event
    if event is None or event.kind != EVENT or set(dict(event.data)) != {'followup'}:
        raise ValueError('Expected the original named continuation event')
    effect = decode(dict(event.data)['followup'])
    root = record(context.state, effect.root_id)
    delivery = for_root(root, effect)
    identity = (root.request.cause.source.entity_id, root.request.player_id, delivery.entity.entity_id)
    if (not delivery.followup_started or (context.source_id, context.player_id, context.target_id) != identity or
            (event.source_id, event.player_id, event.target_id) != identity):
        raise ValueError('Named callback changed its accepted caller or receiver')
    return effect.beneficiary


def original_pool_delivery(context):
    """The exact accepted main body, even if its later face/residence departed."""
    from .summon_quantities import record
    from .pool_summons import PoolSummonBasis
    original_named_reference(context)
    effect = decode(dict(context.event.data)['followup'])
    root = record(context.state, effect.root_id)
    basis = root.request.pool_basis
    if type(basis) is not PoolSummonBasis or basis.followup_policy != 'original_delivery':
        raise ValueError('Original pool delivery query requires its explicit accepted policy')
    return for_root(root, effect).entity


def validate_call(call):
    if call.context.event is not None and call.context.event.kind == EVENT:
        original_named_reference(call.context)
        if call.behavior_id != decode(dict(call.context.event.data)['followup']).behavior_id:
            raise ValueError('Named callback substituted its accepted behavior')


def validate_events(game, roots):
    from .summon_quantities import SummonEntryMaterial
    expected = {(root.id, d.index) for root in roots.values() if root.selected is not None and
        type(root.request.materials[root.selected]) is SummonEntryMaterial for d in root.deliveries if d.followup_started}
    events = tuple(event for event in game._events if event.kind == EVENT)
    if not expected and not events:
        return
    seen = set()
    closing = {dict(e.data)['root_id']: e.sequence for e in game._events if e.kind == 'card_summon_finished'}
    for event in events:
        if set(dict(event.data)) != {'followup'}:
            raise ValueError('Named continuation event requires its complete receipt')
        effect = decode(dict(event.data)['followup'])
        root = roots.get(effect.root_id)
        if root is None:
            raise ValueError('Named continuation lost its live or retired original root')
        delivery = for_root(root, effect)
        key = (root.id, effect.index)
        if (key in seen or not delivery.followup_started or root.event_cursor >= event.sequence or
                event.sequence >= closing.get(root.id, len(game._events)+1) or
                (event.source_id, event.player_id, event.target_id) !=
                (root.request.cause.source.entity_id, root.request.player_id, delivery.entity.entity_id)):
            raise ValueError('Named continuation duplicated, reordered or changed its original receipt')
        seen.add(key)
    if seen != expected:
        raise ValueError('Named continuation receipts differ from actual delivery starts')


def register(mechanics):
    mechanics.register(ContinueNamedMinion, continue_named_minion)
