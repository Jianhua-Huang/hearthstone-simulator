"""Physical Aura duration attachments and the actual cast that installs them."""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace

from .effects import AddToHand, Effect
from .lifecycle import attachment_id
from .model import AbilityInstance, CardClass, CardType
from .pools import GenerateFromPool

KIND = 'aura_duration_bonus'
EVENT = 'aura_duration_accepted'
BIND_EVENT = 'aura_duration_bound'


def validate_grants(grants):
    if type(grants) is not tuple or any(type(a) is not AbilityInstance or a.kind != KIND for a in grants):
        raise ValueError('Aura duration requires its complete physical grant tuple')
    for ability in grants:
        ability.__post_init__()
    if len(grants) > 1:
        raise ValueError('This native duration recipe supports one extra turn per physical Aura')
    if len({a.id for a in grants}) != len(grants):
        raise ValueError('Aura duration cannot count an attachment twice')


def aura_spec(registry, card_id):
    card = registry.card(card_id)
    if (card.kind != CardType.SPELL or card.ongoing_effect_id is None or card.metadata is None or
            CardClass.PALADIN not in (card.metadata.classes or ())):
        raise ValueError('Additional Aura duration requires a native Paladin Aura spell')
    spec = registry.player_effect(card.ongoing_effect_id)
    if spec.kind != 'aura' or spec.card_id != card_id or spec.duration is None or spec.next_turn_end:
        raise ValueError('Additional duration requires the original timed Aura definition')
    return spec


def validate_carrier(state, registry, card_id, kind, abilities):
    grants = tuple(a for a in abilities if a.kind == KIND)
    if not grants:
        return
    if kind != CardType.SPELL:
        raise ValueError('Aura duration attachment lost its physical spell carrier')
    aura_spec(registry, card_id)
    validate_grants(grants)
    if any(a.source_id not in state.entities or a.id >= state.next_attachment_id for a in grants):
        raise ValueError('Aura duration lost its original grant source')


def install(state, registry, entity, source_id):
    aura_spec(registry, entity.card_id)
    if source_id not in state.entities:
        raise ValueError('Aura duration requires its existing creation source')
    entity.abilities.append(AbilityInstance(attachment_id(state), KIND, source_id=source_id))


def capture(r, record):
    if record.origin == 'repeat':
        first = next((c for c in r.state.cast_history if c.play_id == record.play_id and
                      c.origin == 'hand' and c.payload_started and c.failure is None), None)
        grants = () if first is None else first.aura_duration_grants
    else:
        grants = tuple(a for a in r.state.entities[record.source_id].abilities if a.kind == KIND)
    if not grants:
        return record
    validate_carrier(r.state, r.registry, record.card_id, CardType.SPELL, grants)
    record = replace(record, aura_duration_grants=deepcopy(tuple(grants)))
    r.state.cast_history[record.id-1] = record
    r.emit(EVENT, source_id=record.source_id, player_id=record.player_id,
           cast_id=record.id, grants_hash=grants_hash(record.aura_duration_grants))
    return record


def validate_record(state, registry, record):
    validate_grants(record.aura_duration_grants)
    if not record.aura_duration_grants:
        return
    if not record.payload_started or record.failure is not None:
        raise ValueError('Unaccepted cast cannot carry Aura duration')
    validate_carrier(state, registry, record.card_id, CardType.SPELL, record.aura_duration_grants)
    if record.origin == 'repeat':
        first = next((c for c in state.cast_history if c.play_id == record.play_id and c.origin == 'hand'), None)
        if first is None or first.aura_duration_grants != record.aura_duration_grants:
            raise ValueError('Repeated Aura lost its original hand-cast duration material')


def grants_hash(grants):
    from .serialization import canonical_hash
    return canonical_hash([asdict(a) for a in grants])


def validate_events(game):
    from .hero_health_history import effective_events
    events = tuple(effective_events(game._events))
    bound = tuple(e for e in events if e.kind == EVENT)
    records = tuple(c for c in game._state.cast_history if c.aura_duration_grants)
    ids = [dict(e.data).get('cast_id') for e in bound]
    if (any(type(i) is not int or i < 1 for i in ids) or
            len(ids) != len(set(ids)) or set(ids) != {c.id for c in records}):
        raise ValueError('Aura duration lost its complete accepted cast event inventory')
    by_id = {c.id:c for c in records}
    for event in bound:
        record = by_id[dict(event.data)['cast_id']]
        if ((event.source_id, event.player_id, event.target_id) != (record.source_id, record.player_id, None) or
                dict(event.data) != {'cast_id':record.id, 'grants_hash':grants_hash(record.aura_duration_grants)} or
                event.sequence <= record.recorded_event):
            raise ValueError('Aura duration differs from its actual original cast receipt')
    accepted = {dict(e.data)['cast_id']:e.sequence for e in bound}
    added = {}
    for event in events:
        if event.kind != 'player_effect_added':
            continue
        data = dict(event.data); spec = game.registry.player_effect(data['effect_key'])
        if (spec.kind == 'aura' and spec.duration is not None and
                data['remaining_turns'] > spec.duration):
            added[event.sequence] = event
    bindings = tuple(e for e in events if e.kind == BIND_EVENT)
    if any(set(dict(e.data)) != {'instance_id','cast_id','added_event'} or
            any(type(v) is not int or v < 1 for v in dict(e.data).values()) for e in bindings):
        raise ValueError('Aura instance requires its exact original duration receipt')
    cursors = [dict(e.data)['added_event'] for e in bindings]
    instance_ids = [dict(e.data)['instance_id'] for e in bindings]
    if (len(cursors) != len(set(cursors)) or set(cursors) != set(added) or
            len(instance_ids) != len(set(instance_ids))):
        raise ValueError('Aura instances lost their complete original installation receipts')
    by_instance = {}
    for event in bindings:
        data = dict(event.data); record = by_id.get(data['cast_id'])
        if record is None:
            raise ValueError('Aura instance lost its original accepted duration cast')
        original = added[data['added_event']]; material = dict(original.data)
        spec = aura_spec(game.registry, record.card_id)
        if ((event.source_id,event.player_id,event.target_id) != (record.source_id,record.player_id,None) or
                (original.source_id,original.player_id) != (record.source_id,record.player_id) or
                (material['effect_key'],material['card_id'],material['remaining_turns']) !=
                    (spec.id,record.card_id,spec.duration+len(record.aura_duration_grants)) or
                not accepted[record.id] < original.sequence < event.sequence):
            raise ValueError('Aura installation differs from its original duration cast')
        by_instance[data['instance_id']] = (data['cast_id'],record.player_id,record.source_id,spec.id)
    for player in game._state.players.values():
        for instance in player.player_effects:
            expected = by_instance.get(instance.id)
            if expected is not None or instance.aura_duration_cast_id is not None:
                if expected != (instance.aura_duration_cast_id,player.id,instance.source_id,instance.spec_id):
                    raise ValueError('Live Aura lost or changed its original duration installation binding')


def duration(state, registry, spec, source_id, player_id, cast_id):
    if cast_id is None:
        return spec.duration
    from .spell_casts import cast_record
    record = cast_record(state, cast_id)
    validate_record(state, registry, record)
    if (not record.aura_duration_grants or spec.kind != 'aura' or spec.duration is None or
            (record.source_id, record.player_id, record.card_id) != (source_id, player_id, spec.card_id)):
        raise ValueError('Aura duration borrowed another spell cast or timed program')
    return spec.duration + len(record.aura_duration_grants)


def maximum_duration(registry, instance, state=None, player_id=None):
    """The same finite bound for live and already captured player programs.

    Pure producer declarations lack State; their frozen inventory receives the
    structural bound. State-aware consumers also verify the original cast.
    """
    spec = registry.player_effect(instance.spec_id)
    if instance.aura_duration_cast_id is None:
        return spec.duration
    if spec.kind != 'aura' or spec.duration is None or spec.next_turn_end:
        raise ValueError('Additional duration belongs only to its native Aura')
    if state is None:
        return spec.duration + 1
    from .spell_casts import cast_record
    record = cast_record(state, instance.aura_duration_cast_id)
    return duration(state, registry, spec, instance.source_id,
        record.player_id if player_id is None else player_id, instance.aura_duration_cast_id)


@dataclass(frozen=True)
class GenerateAuraWithExtraTurn(Effect):
    request: GenerateFromPool

    def __post_init__(self):
        q = self.request
        if type(q) is not GenerateFromPool:
            raise ValueError('Aura duration generation requires its ordinary complete pool request')
        q.__post_init__()
        if (q.source_id is None or q.count != 1 or not q.replacement or q.destination != 'hand' or
                q.query.kinds != (CardType.SPELL,) or q.query.collectible is not True or not q.query.card_ids or
                q.combined_shatter or any(v is not None for v in (q.cost, q.expires_turn, q.spell_repeat,
                    q.cause, q.producer_profile_id, q.temporary_until_turn, q.board_position, q.minion_stats,
                    q.shuffle_actor_id, q.entry_grant, q.minion_grant))):
            raise ValueError('Aura duration generation supports one plain source-bound named Aura selection')


def generate(r, effect):
    from .opening import create_hand_card
    from .pools import generate_from_pool, resolve_candidates
    effect.__post_init__()
    q = effect.request
    source = r.state.entities.get(q.source_id)
    if source is None:
        raise ValueError('Aura duration generation lost its source')
    # Check every eligible native definition before the ordinary generator
    # samples. An unsupported eligible Aura cannot disappear from the pool.
    members = resolve_candidates(r.registry, r.game._generation_context, q.pool_id, q.query,
        current_class=r.state.players[q.player_id].hero_class, source_card_id=source.card_id,
        policy=q.policy, player_id=q.player_id)
    for member in members:
        aura_spec(r.registry, member.card_id)
    work = generate_from_pool(r, q)
    if len(work) > 1 or any(type(w) is not AddToHand for w in work):
        raise ValueError('Aura duration generator returned another delivery protocol')
    for item in work:
        create_hand_card(r, item, aura_duration_source=q.source_id)
    return ()


def register(mechanics):
    mechanics.register(GenerateAuraWithExtraTurn, generate)
