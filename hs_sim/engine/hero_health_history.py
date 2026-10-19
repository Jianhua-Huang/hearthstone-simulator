"""Actual hero remaining-health transitions, independent of damage and prices.

Original mutators own health; this ledger records their committed facts. It
does not apply health, emit new events, scan host logs for price queries or
cache a mutable player count. Exact CN occurrence windows remain uncalibrated.
"""
from .model import CardType, HeroHealthChangeRecord, OwnerTurnRecord, Zone, _int, _name

TRANSITION = 'hero_health_transition'
CHANGE_ID = 'hero_health_change_id'


def snapshot(entity):
    if entity.kind != CardType.HERO or entity.zone != Zone.HERO:
        return None
    return (entity.controller, entity.id, entity.card_id, entity.health, entity.max_health)


def validate_transition(value):
    if type(value) is not tuple or len(value) != 9:
        raise ValueError('Hero transition requires its complete frozen before/after')
    player, old_id, old_card, before, old_max, new_id, new_card, after, new_max = value
    if type(player) is not int or player not in (1, 2):
        raise ValueError('Hero transition requires its actual player')
    for identity in (old_id, new_id): _int(identity, 'hero transition identity', 1)
    for card in (old_card, new_card): _name(card, 'hero transition card')
    for health in (before, after): _int(health, 'hero transition remaining health')
    for maximum in (old_max, new_max): _int(maximum, 'hero transition maximum')
    if before > old_max or after > new_max:
        raise ValueError('Hero transition exceeds its actual maximum')
    return value


def prepare_change(state, before, after, event_kind):
    """Pure actual-transition operand, also used by original payment projection."""
    if before is None: return None
    if after is None or before[0] != after[0]:
        raise ValueError('Hero transition lost its actual payer/controller')
    value = validate_transition((*before, *after[1:]))
    if before[3] == after[3]: return None
    owner = state.owner_turn_history[-1] if state.owner_turn_history else None
    if owner is not None and (owner.closed or (owner.turn, owner.player_id) != (state.turn, state.active_player)):
        raise ValueError('Hero transition has no genuine current owner interval')
    return HeroHealthChangeRecord(state.next_hero_health_change_id, value[0], state.active_player,
        state.turn, state.action_number, owner.id if owner is not None else 0, event_kind,
        before[1], before[2], after[1], after[2], before[3], before[4], after[3], after[4])


def event_data(before, after, row):
    if before is None: return {}
    value = validate_transition((*before, *after[1:]))
    if (row is None) != (value[3] == value[7]):
        raise ValueError('Hero event lost its actual change/no-change decision')
    if row is not None and row.transition() != value:
        raise ValueError('Hero event differs from its committed transition')
    return {TRANSITION: value, CHANGE_ID: None if row is None else row.id}


def commit(state, before, after, event_kind):
    """Resolver-only bookkeeping after the original numeric commit, no checkpoint."""
    row = prepare_change(state, before, after, event_kind)
    if row is not None:
        if state.next_hero_health_change_id != len(state.hero_health_change_history) + 1:
            raise ValueError('Hero transition lost its allocation cursor')
        state.hero_health_change_history.append(row)
        state.next_hero_health_change_id += 1
    return event_data(before, after, row)


def validate_state(state, registry=None):
    _int(state.next_hero_health_change_id, 'next_hero_health_change_id', 1)
    rows = state.hero_health_change_history
    if type(rows) is not list or state.next_hero_health_change_id != len(rows) + 1:
        raise ValueError('Hero health history lost its complete allocation')
    previous_turn = previous_action = previous_owner = 0
    for index, row in enumerate(rows, 1):
        if type(row) is not HeroHealthChangeRecord:
            raise ValueError('Hero health history requires immutable actual transitions')
        row.__post_init__()
        if (row.id != index or not previous_turn <= row.turn <= state.turn or
                not previous_action <= row.action <= state.action_number or
                not previous_owner <= row.owner_turn_id <= len(state.owner_turn_history)):
            raise ValueError('Hero health history changed its original chronology')
        for identity, card in ((row.old_hero_id, row.old_hero_card_id), (row.hero_id, row.hero_card_id)):
            hero = state.entities.get(identity)
            if (hero is None or identity >= state.next_entity_id or
                    (hero.kind, hero.owner, hero.controller, hero.card_id) !=
                    (CardType.HERO, row.player_id, row.player_id, card)):
                raise ValueError('Hero health history changed its physical hero identity')
            if registry is not None and registry.card(card).kind != CardType.HERO:
                raise ValueError('Hero health history requires a supported hero face')
        if row.owner_turn_id:
            owner = state.owner_turn_history[row.owner_turn_id - 1]
            if type(owner) is not OwnerTurnRecord:
                raise ValueError('Hero health history lost its genuine owner interval')
            owner.__post_init__()
            if ((owner.turn, owner.player_id) != (row.turn, row.active_player) or
                    row.action < owner.start_action or
                    owner.closed_action is not None and row.action > owner.closed_action):
                raise ValueError('Hero change is outside its original owner interval')
        elif (row.turn != 1 or state.owner_turn_history and row.action > state.owner_turn_history[0].start_action):
            raise ValueError('Pre-first hero change borrowed a later genuine turn')
        previous_turn, previous_action, previous_owner = row.turn, row.action, row.owner_turn_id


def health_change_count(state, player_id):
    """Pure SCH_140 operand: changes of this hero during genuinely started own turns."""
    if type(player_id) is not int or player_id not in (1, 2):
        raise ValueError('Hero health count requires an actual player')
    validate_state(state)
    return sum(row.player_id == player_id == row.active_player and row.owner_turn_id > 0
               for row in state.hero_health_change_history)


def validate_health_set_event(event):
    """Validate the direct assignment envelope without authenticating past states."""
    data=dict(event.data)
    expected={'requested','old_health','health','max_health',TRANSITION,CHANGE_ID}
    if len(data)!=len(event.data) or set(data)!=expected:
        raise ValueError('Hero health assignment lost its complete original envelope')
    value=validate_transition(data[TRANSITION])
    if type(event.player_id) is not int or event.player_id not in (1,2):
        raise ValueError('Hero assignment requires its actual player header')
    _int(event.target_id,'Hero assignment physical target',1)
    for key in ('requested','health','max_health'): _int(data[key],'Hero health assignment '+key,0)
    _int(data['old_health'],'Hero assignment original health',1)
    _int(event.amount,'Hero assignment actual delta')
    if (value[1:3]!=value[5:7] or value[4]!=value[8]
            or (data['old_health'],data['max_health'])!=value[3:5]
            or (data['health'],data['max_health'])!=value[7:]
            or data['health']!=min(data['requested'],data['max_health'])
            or (event.player_id,event.target_id,event.amount)!=(value[0],value[5],value[7]-value[3])):
        raise ValueError('Hero health assignment changed original target/account operands')
    if event.source_id is not None: _int(event.source_id,'Hero assignment source',1)
    return value


def validate_event(state, event):
    data = dict(event.data)
    if len(data) != len(event.data):
        raise ValueError('Hero event contains duplicate fields')
    if (TRANSITION in data) != (CHANGE_ID in data):
        raise ValueError('Hero event lost its complete transition envelope')
    if event.kind=='hero_health_set':
        validate_health_set_event(event)
        if event.source_id is not None and event.source_id not in state.entities:
            raise ValueError('Hero assignment borrowed an unknown physical source')
    if TRANSITION not in data: return None
    value = validate_transition(data[TRANSITION])
    if event.kind not in ('health_resolved', 'health_lost', 'health_loss_floor_resolved',
            'max_health_gained', 'max_health_lost', 'health_spent', 'opponent_health_spent', 'stats_changed',
            'enchantment_removed', 'attachments_expired', 'hero_replaced', 'hero_recovered', 'hero_health_set'):
        raise ValueError('Hero envelope borrowed an unrelated original event')
    for entity_id, card in ((value[1], value[2]), (value[5], value[6])):
        hero = state.entities.get(entity_id)
        if hero is None or (hero.kind, hero.owner, hero.controller, hero.card_id) != (
                CardType.HERO, value[0], value[0], card):
            raise ValueError('Hero envelope changed its actual physical identity')
    if event.kind in ('health_spent','opponent_health_spent'):
        actor=value[0] if event.kind=='health_spent' else 3-value[0]
        if event.target_id is not None or event.player_id != actor:
            raise ValueError('Health payment transition changed its actual payer')
    elif event.target_id != value[5]:
        raise ValueError('Hero transition changed its actual physical event target')
    if event.kind == 'hero_replaced':
        if event.source_id != value[1]:
            raise ValueError('Hero replacement lost its original physical predecessor')
    elif value[1:3] != value[5:7]:
        raise ValueError('Ordinary hero transition changed its physical identity')
    result = None
    if event.kind == 'health_resolved':
        from .health_outcomes import health_result
        result = health_result(event)
    if event.kind in ('max_health_gained', 'max_health_lost') or event.kind == 'stats_changed' and 'old_health' in data:
        if value[3:5] != (data['old_health'], data['old_max_health']) or value[7:] != (data['health'], data['max_health']):
            raise ValueError('Hero envelope changed its original stat operands')
    if event.kind == 'health_lost' and value[3] - value[7] != event.amount:
        raise ValueError('Hero envelope changed its original actual health debit')
    identity = data[CHANGE_ID]
    if value[3] == value[7]:
        if identity is not None: raise ValueError('Unchanged hero health invented an occurrence')
        return None
    _int(identity, 'hero event actual change identity', 1)
    if identity >= state.next_hero_health_change_id:
        raise ValueError('Hero event borrowed an uncommitted occurrence')
    row = state.hero_health_change_history[identity - 1]
    if (type(row) is not HeroHealthChangeRecord or row.transition() != value or
            (row.event_kind, row.action) != (event.kind, event.action)):
        raise ValueError('Hero event differs from its complete committed occurrence')
    if result is not None:
        if (row.turn, row.active_player) != (result.turn, result.active_player):
            raise ValueError('Hero transition changed its original settled packet')
    return identity


def validate_boundary(game):
    state = game._state
    validate_state(state, game.registry)
    identities = []
    for event in effective_events(game._events):
        data = dict(event.data)
        if event.kind == 'health_resolved' and dict(data['result'])['target_kind'] == CardType.HERO.value:
            if TRANSITION not in data:
                raise ValueError('Hero packet lost its original transition envelope')
        if identity := validate_event(state, event):
            identities.append(identity)
            row = state.hero_health_change_history[identity - 1]
            if row.owner_turn_id:
                owner = state.owner_turn_history[row.owner_turn_id - 1]
                if (event.sequence <= owner.start_event or
                        owner.closed_event is not None and event.sequence > owner.closed_event):
                    raise ValueError('Hero event is outside its genuine owner interval')
            elif state.owner_turn_history and event.sequence > state.owner_turn_history[0].start_event:
                raise ValueError('Pre-first hero change crossed a later owner entrance')
    if identities != list(range(1, state.next_hero_health_change_id)):
        raise ValueError('Hero health history lost its complete original event inventory')


def effective_events(events):
    """Boundary validation only: original Rewind restores the pre-attempt ledger.

    Host diagnostic events remain append-only. A genuine original reset marker
    retires the attempted suffix from this validator, including its old marker.
    Price/count queries never read this log; they use the restored State facts.
    """
    effective = []
    for event in events:
        if event.kind == 'timeline_rewound':
            data = dict(event.data)
            start = data.get('event_start')
            _int(start, 'hero timeline original event cursor', 0)
            if start >= event.sequence:
                raise ValueError('Hero timeline reset borrowed a future event cursor')
            effective = [e for e in effective if e.sequence <= start]
        effective.append(event)
    return effective
