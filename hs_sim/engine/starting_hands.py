"""Frozen final starting faces and an own-end temporary starting-hand source.

Coin, special opening timing, printed material and expiry cleanup are explicit
local policies pending CN calibration. Scenarios do not invent starting hands.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, replace

from .effects import AddToHand, Effect, _integer, _player
from .errors import ResolutionError
from .model import StartingHandCard, Zone
from .zones import CardReference, source_exists

STARTING_POLICY = 'after-opening-before-first-draw-v1'
TEMPORARY_POLICY = 'own-end-starting-printed-v1'


@dataclass(frozen=True)
class ReplaceHandWithTemporaryStartingHand(Effect):
    player_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.source_id, 'starting hand source', 1)


def receipt(first_player, groups):
    return dict(policy=STARTING_POLICY, first_player=first_player,
        hands=tuple(tuple((v.entity_id, v.card_id, v.zone_epoch, v.hand_entry_id) for v in group) for group in groups))


def capture(r):
    opening = r.state.opening
    if opening is None or opening.stage != 'starting' or opening.starting_hands is not None:
        raise ResolutionError('Starting hand capture requires its final opening boundary')
    groups = tuple(tuple(StartingHandCard(entity.id, entity.card_id, entity.zone_epoch, entity.hand_entry_id)
        for eid in r.player(player_id).hand for entity in (r.state.entities[eid],)) for player_id in (1, 2))
    r.state.opening = replace(opening, stage='complete', starting_hands=groups)
    r.emit('starting_hands_captured', **receipt(opening.first_player, groups))


def starting_hand(state, player_id):
    _player(player_id)
    opening = state.opening
    if opening is None or opening.stage != 'complete' or opening.starting_hands is None:
        raise ResolutionError('A final constructed starting-hand record is required')
    return opening.starting_hands[player_id - 1]


def references(group, player_id):
    return tuple(CardReference(v.entity_id, player_id, Zone.HAND, v.card_id, v.zone_epoch) for v in group)


def start(r, request):
    request.__post_init__()
    source_exists(r, request.source_id)
    if r.state.active_player != request.player_id:
        raise ResolutionError('Temporary starting hand requires the active player')
    group = starting_hand(r.state, request.player_id)
    if len(group) > hand_capacity(r.player(request.player_id), r.rules):
        raise ResolutionError('Recorded starting hand exceeds current capacity')
    for card in group:
        if not r.registry.card(card.card_id).hand_playable:
            raise ResolutionError('Recorded starting face is not a playable hand card')
    from .temporary_hands import SavedHandCard, TemporaryHandReplacement, begin_data, event_prefix, hide
    from .opening import create_hand_card
    originals = tuple(r.state.entities[eid] for eid in r.player(request.player_id).hand)
    for entity in originals:
        r.registry.card(entity.card_id)
    saved = []
    for entity in originals:
        hide(r, entity)
        saved.append(SavedHandCard(entity.id, entity.card_id, entity.zone_epoch, entity.hand_entry_id))
    introduced = tuple(create_hand_card(r, AddToHand(request.player_id, card.card_id, source_id=request.source_id),
        origin_entity_id=card.entity_id).id for card in group)
    root = TemporaryHandReplacement(len(r.state.temporary_hands) + 1, request,
        r.state.entities[request.source_id].card_id, r.state.turn, r.state.action_number,
        tuple(saved), references(group, request.player_id), introduced)
    r.state.temporary_hands.append(root)
    r.emit(event_prefix(root) + 'replaced', source_id=request.source_id, player_id=request.player_id, **begin_data(root))


def validate_boundary(game):
    opening = game._state.opening
    events = [event for event in game._events if event.kind == 'starting_hands_captured']
    groups = None if opening is None else opening.starting_hands
    if groups is None:
        if events:
            raise ValueError('Starting hand receipt has no final opening record')
        return
    if len(events) != 1 or events[0].source_id is not None or events[0].player_id is not None:
        raise ValueError('Final starting hands require one private capture receipt')
    event = events[0]
    if dict(event.data) != receipt(opening.first_player, groups) or event.action > game._state.action_number:
        raise ValueError('Final starting hand changed its original capture receipt')
    mulligans = [e for e in game._events if e.kind == 'mulligan_completed']
    starts = [e for e in game._events if e.kind == 'game_started']
    if len(mulligans) != 1 or not mulligans[0].sequence < event.sequence or len(starts) != 1 or not event.sequence < starts[0].sequence:
        raise ValueError('Starting hand capture left its pre-first-turn boundary')
    for player_id, group in enumerate(groups, 1):
        for card in group:
            definition = game.registry.card(card.card_id)
            entity = game._state.entities.get(card.entity_id)
            if not definition.hand_playable or entity is None or entity.zone_epoch < card.zone_epoch:
                raise ValueError('Unknown starting hand face or physical origin')
            if not 1 <= card.hand_entry_id <= len(game._state.hand_entries):
                raise ValueError('Starting hand lacks its actual acquisition')
            entry = game._state.hand_entries[card.hand_entry_id - 1]
            if (entry.entity_id, entry.player_id) != (card.entity_id, player_id) or entry.zone_epoch > card.zone_epoch or entry.action > event.action:
                raise ValueError('Starting hand changed its original acquisition')


def register(mechanics):
    mechanics.register(ReplaceHandWithTemporaryStartingHand, start)
