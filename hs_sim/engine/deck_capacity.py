"""Runtime deck admission shared by generated and original physical cards.

Scenario construction remains an experimental input. Runtime writers must not
grow even an oversized scenario deck, while reordering its own cards is legal.
Failed allocations are private outcomes, never successful shuffle witnesses.
"""
from .allocation_facts import SourceAllocationFact, allocation_from_payload, validate_allocation
from .errors import ResolutionError
from .model import Zone

MAX_DECK_SIZE = 99
FAILED = 'deck_entry_failed'


def room(state, player_id):
    return max(0, MAX_DECK_SIZE - len(state.players[player_id].deck))


def admits(state, player_id, entity=None):
    return bool(room(state, player_id) or entity is not None and
        entity.controller == player_id and entity.zone == Zone.DECK and
        entity.id in state.players[player_id].deck)


def require_room(state, player_id, entity=None):
    if not admits(state, player_id, entity):
        raise ResolutionError('Runtime deck writer bypassed full-deck admission')


def failure(r, player_id, card_id, source_id=None, *, original=None, temporary_hand_id=None):
    """Publish the actual denied entry, without allocation or random placement."""
    if room(r.state, player_id):
        raise ResolutionError('Deck failure requires an actually full recipient')
    if not r.registry.card(card_id).hand_playable:
        raise ResolutionError('Deck failure cannot hide an unknown or nonphysical card')
    if original is not None:
        validate_allocation(r.state, r.registry, original)
    extra = {} if temporary_hand_id is None else {'temporary_hand_id':temporary_hand_id}
    return r.emit(FAILED, source_id=source_id,
        target_id=None if original is None else original.entity_id, player_id=player_id,
        card_id=card_id, capacity=MAX_DECK_SIZE, deck_size=len(r.player(player_id).deck),
        original=None if original is None else original.payload(), _capture=False, **extra)


def validate_failure(state, registry, event):
    if event.kind != FAILED:
        raise ValueError('Actual deck-entry failure required')
    data = dict(event.data)
    if (set(data) - {'temporary_hand_id'} != {'card_id', 'capacity', 'deck_size', 'original'} or
            event.player_id not in (1, 2) or event.amount != 0 or
            data['capacity'] != MAX_DECK_SIZE or type(data['deck_size']) is not int or
            data['deck_size'] < MAX_DECK_SIZE or
            not registry.card(data['card_id']).hand_playable or
            event.source_id is not None and event.source_id not in state.entities):
        raise ValueError('Deck failure lost its original full recipient or registered face')
    original = allocation_from_payload(data['original'])
    if original is not None:
        validate_allocation(state, registry, original, closed=True)
    if (event.target_id != (None if original is None else original.entity_id) or
            original is not None and original.card_id != data['card_id']):
        raise ValueError('Deck failure changed its original physical card')
    if 'temporary_hand_id' in data:
        from .temporary_deck_hands import TemporaryDeckHandReplacement
        identity = data['temporary_hand_id']
        if type(identity) is not int or not 1 <= identity <= len(state.temporary_hands):
            raise ValueError('Deck overflow lost its original temporary hand group')
        root = state.temporary_hands[identity-1]
        if (type(root) is not TemporaryDeckHandReplacement or root.phase != 'completed' or
                (event.player_id,event.source_id) != (root.request.player_id,root.request.source_id) or
                original is None or original.zone != Zone.HAND or event.target_id not in root.deck_burned):
            raise ValueError('Deck overflow changed its original temporary return operand')
    return original


def validate_events(state, registry, events):
    from .hero_health_history import effective_events
    effective = effective_events(events); returns = {}; failures = {}
    for event in effective:
        if event.kind == 'temporary_deck_hand_restored':
            returns[dict(event.data)['hand_id']] = event
        if event.kind == FAILED:
            validate_failure(state, registry, event)
            identity = dict(event.data).get('temporary_hand_id')
            if identity is not None:
                restored = returns.get(identity)
                if restored is None or (restored.action,restored.source_id,restored.player_id) != (
                        event.action,event.source_id,event.player_id):
                    raise ValueError('Temporary deck failure has no original completed return window')
                failures.setdefault(identity,[]).append(event.target_id)
    from .temporary_deck_hands import TemporaryDeckHandReplacement
    for root in state.temporary_hands:
        if type(root) is TemporaryDeckHandReplacement and tuple(failures.get(root.id,())) != root.deck_burned:
            raise ValueError('Temporary deck return lost, duplicated or reordered original failed entries')
