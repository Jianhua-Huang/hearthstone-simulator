"""Physical deck cards borrowed until the next genuine owner start.

Entry leases distinguish temporary cards from copies and later reacquisitions.
Sampling, shuffle, startup priority and overflow order are explicit CN-pending
policies. Private original-hand storage is shared with temporary_hands.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, replace
from random import Random

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import Zone, validate_end_turn_rng
from .owner_turns import current_owner_turn, owner_turn_index
from .temporary_hands import SavedHandCard, hide, ReturnTemporaryHand
from .zones import CardReference, source_exists

POLICY = 'next-owner-start-borrowed-entry-v1'


@dataclass(frozen=True)
class ReplaceHandWithTemporaryDeckCards(Effect):
    player_id: int
    count: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id)
        _integer(self.count, 'temporary deck hand count', 0)
        _integer(self.source_id, 'temporary deck hand source', 1)


@dataclass(frozen=True)
class ExpireTemporaryDeckHands(Effect):
    pass


def _records(values, cls, name):
    if type(values) is not tuple or any(type(value) is not cls for value in values):
        raise ValueError('Typed ' + name + ' tuple required')
    for value in values:
        value.__post_init__()
    if len({value.entity_id for value in values}) != len(values):
        raise ValueError('Duplicate ' + name + ' entity')


def _ids(values):
    if type(values) is not tuple or len(set(values)) != len(values):
        raise ValueError('Unique physical hand identities required')
    for value in values:
        _integer(value, 'physical hand identity', 1)


@dataclass(frozen=True)
class TemporaryDeckHandReplacement:
    id: int
    request: ReplaceHandWithTemporaryDeckCards
    source_card_id: str
    turn: int
    action: int
    owner_turn_id: int
    originals: tuple[SavedHandCard, ...]
    deck_basis: tuple[CardReference, ...]
    selected: tuple[CardReference, ...]
    borrowed: tuple[SavedHandCard, ...]
    rng_before: tuple
    rng_after: tuple
    phase: str = 'active'
    removed: tuple[int, ...] = ()
    deck_burned: tuple[int, ...] = ()
    returned: tuple[int, ...] = ()
    burned: tuple[int, ...] = ()
    restored: tuple[SavedHandCard, ...] = ()
    return_deck_before: tuple[int, ...] = ()
    return_deck_after: tuple[int, ...] = ()
    return_rng_before: tuple | None = None
    return_rng_after: tuple | None = None

    def __post_init__(self):
        for name in ('id', 'turn', 'owner_turn_id'):
            _integer(getattr(self, name), 'temporary deck hand ' + name, 1)
        _integer(self.action, 'temporary deck hand action', 0)
        if type(self.request) is not ReplaceHandWithTemporaryDeckCards:
            raise ValueError('Typed physical deck hand request required')
        self.request.__post_init__()
        if type(self.source_card_id) is not str or not self.source_card_id.strip():
            raise ValueError('Original deck hand source face required')
        if self.phase not in ('active', 'completed', 'ended'):
            raise ValueError('Unknown temporary deck hand phase')
        for name in ('originals', 'borrowed', 'restored'):
            _records(getattr(self, name), SavedHandCard, name)
        for name in ('deck_basis', 'selected'):
            _records(getattr(self, name), CardReference, name)
        if any(ref.zone != Zone.DECK or ref.player_id != self.request.player_id for ref in self.deck_basis):
            raise ValueError('Temporary deck hand changed its physical candidate zone')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        rng = Random(); rng.setstate(self.rng_before)
        chosen = tuple(rng.sample(self.deck_basis, min(self.request.count, len(self.deck_basis)))) if self.deck_basis else ()
        if chosen != self.selected or rng.getstate() != self.rng_after:
            raise ValueError('Temporary deck hand changed its original sample')
        if tuple(ref.entity_id for ref in self.selected) != tuple(ref.entity_id for ref in self.borrowed):
            raise ValueError('Temporary deck hand replaced physical cards with copies')
        for name in ('removed', 'deck_burned', 'returned', 'burned', 'return_deck_before', 'return_deck_after'):
            _ids(getattr(self, name))
        if self.phase != 'completed':
            if any((self.removed, self.deck_burned, self.returned, self.burned, self.restored, self.return_deck_before,
                    self.return_deck_after, self.return_rng_before is not None, self.return_rng_after is not None)):
                raise ValueError('Unfinished deck hand already returned')
            return
        if self.returned + self.burned != tuple(ref.entity_id for ref in self.originals):
            raise ValueError('Temporary deck hand changed original return or overflow order')
        if tuple(ref.entity_id for ref in self.restored) != self.returned:
            raise ValueError('Temporary deck hand lost actual return acquisitions')
        if not set(self.removed) <= {ref.entity_id for ref in self.borrowed}:
            raise ValueError('Temporary deck hand removed an unrelated acquisition')
        from .deck_capacity import MAX_DECK_SIZE
        success = tuple(eid for eid in self.removed if eid not in self.deck_burned)
        initial_size = len(self.return_deck_before)-len(success)
        expected_count = min(len(self.removed),max(0,MAX_DECK_SIZE-initial_size))
        if (success != self.removed[:expected_count] or self.deck_burned != self.removed[expected_count:] or
                not set(success) <= set(self.return_deck_before) or
                set(self.deck_burned) & set(self.return_deck_before)):
            raise ValueError('Temporary deck hand lost returned physical deck bodies')
        validate_end_turn_rng(self.return_rng_before); validate_end_turn_rng(self.return_rng_after)
        rng.setstate(self.return_rng_before); deck = list(self.return_deck_before)
        if success:
            rng.shuffle(deck)
        if tuple(deck) != self.return_deck_after or rng.getstate() != self.return_rng_after:
            raise ValueError('Temporary deck hand changed its original return shuffle')


def _saved(entity):
    return SavedHandCard(entity.id, entity.card_id, entity.zone_epoch, entity.hand_entry_id)


def _saved_data(values):
    return tuple((ref.entity_id, ref.card_id, ref.zone_epoch, ref.hand_entry_id) for ref in values)


def _deck_data(values):
    return tuple((ref.entity_id, ref.player_id, ref.zone.value, ref.card_id, ref.zone_epoch) for ref in values)


def begin_data(root):
    return dict(hand_id=root.id, source_card_id=root.source_card_id, turn=root.turn, policy=POLICY,
                owner_turn_id=root.owner_turn_id, count=root.request.count, originals=_saved_data(root.originals),
                deck_basis=_deck_data(root.deck_basis), selected=_deck_data(root.selected), borrowed=_saved_data(root.borrowed),
                rng_before=root.rng_before, rng_after=root.rng_after)


def finish_data(root):
    return dict(hand_id=root.id, removed=root.removed, deck_burned=root.deck_burned, returned=root.returned, burned=root.burned,
                restored=_saved_data(root.restored), deck_before=root.return_deck_before, deck_after=root.return_deck_after,
                rng_before=root.return_rng_before, rng_after=root.return_rng_after)


def start(r, request):
    request.__post_init__(); source_exists(r, request.source_id)
    if request.player_id != r.state.active_player or request.count > hand_capacity(r.player(request.player_id), r.rules):
        raise ResolutionError('Temporary physical deck hand requires active player and hand capacity')
    owner = current_owner_turn(r.state)
    originals = tuple(r.state.entities[eid] for eid in r.player(request.player_id).hand)
    basis = tuple(CardReference.capture(r.state.entities[eid]) for eid in r.player(request.player_id).deck)
    for ref in basis:
        if not r.registry.card(ref.card_id).hand_playable:
            raise ResolutionError('Temporary deck hand candidate is not hand playable')
    before = r.game._rng.getstate()
    selected = tuple(r.game._rng.sample(basis, min(request.count, len(basis)))) if basis else ()
    saved = []
    for entity in originals:
        hide(r, entity); saved.append(_saved(entity))
    borrowed = []
    for ref in selected:
        entity = r.state.entities[ref.entity_id]
        r.move(entity, Zone.HAND); borrowed.append(_saved(entity))
    root = TemporaryDeckHandReplacement(len(r.state.temporary_hands) + 1, request,
        r.state.entities[request.source_id].card_id, r.state.turn, r.state.action_number, owner.id,
        tuple(saved), basis, selected, tuple(borrowed), before, r.game._rng.getstate())
    r.state.temporary_hands.append(root)
    r.emit('temporary_deck_hand_replaced', source_id=request.source_id, player_id=request.player_id, **begin_data(root))
    for ref in borrowed:
        r.emit('card_moved_to_hand', source_id=request.source_id, target_id=ref.entity_id, player_id=request.player_id)


def start_window(state):
    if not state.owner_turn_history or state.status != 'playing':
        return False
    owner = current_owner_turn(state)
    return owner.origin == 'actual' and owner.publication_event is None and owner.end_event is None


def due_start(state):
    if not start_window(state):
        return ()
    owner = current_owner_turn(state)
    return tuple(root.id for root in state.temporary_hands if type(root) is TemporaryDeckHandReplacement
                 and root.phase == 'active' and root.request.player_id == owner.player_id
                 and state.owner_turn_history[root.owner_turn_id - 1].owner_index + 1 == owner.owner_index)


def still_borrowed(state, root, ref):
    entity = state.entities[ref.entity_id]
    if (entity.controller, entity.zone) != (root.request.player_id, Zone.HAND):
        return False
    entry = entity.hand_entry_id
    visited = set()
    while entry != ref.hand_entry_id:
        if entry in visited:
            raise ValueError('Temporary hand acquisition alias cycle')
        visited.add(entry)
        child = next((row for row in reversed(state.temporary_hands)
            if type(row) is TemporaryDeckHandReplacement and row.id > root.id and row.phase == 'completed'
            and row.request.player_id == root.request.player_id
            and any(value.entity_id == entity.id and value.hand_entry_id == entry for value in row.restored)), None)
        if child is None:
            return False
        entry = next(value.hand_entry_id for value in child.originals if value.entity_id == entity.id)
    return True


def return_hand(r, root):
    expected = due_start(r.state)
    if r.ending_turn or not expected or root.id != expected[-1]:
        raise ResolutionError('Temporary deck hand return requires its genuine next owner start')
    player = r.player(root.request.player_id)
    originals = []
    for ref in root.originals:
        entity = r.state.entities[ref.entity_id]
        if (entity.controller, entity.zone, entity.card_id, entity.zone_epoch, entity.hand_entry_id) != (
                player.id, Zone.SETASIDE, ref.card_id, ref.zone_epoch, ref.hand_entry_id):
            raise ResolutionError('Original temporary deck hand changed its private residence')
        originals.append(entity)
    borrowed = {ref.entity_id: ref for ref in root.borrowed}
    removed = tuple(eid for eid in player.hand if eid in borrowed and still_borrowed(r.state, root, borrowed[eid]))
    from .deck_capacity import admits, failure
    from .allocation_facts import SourceAllocationFact
    deck_burned = {}; deck_returned = []
    for eid in removed:
        entity = r.state.entities[eid]
        if admits(r.state,player.id,entity):
            r.move(entity, Zone.DECK); deck_returned.append(eid)
        else:
            deck_burned[eid] = SourceAllocationFact.capture(r.state,entity)
            r.move(entity, Zone.GRAVEYARD)
    before = r.game._rng.getstate(); deck_before = tuple(player.deck)
    if deck_returned:
        r.game._rng.shuffle(player.deck)
        for eid in player.deck:
            r.game._information.conceal(eid)
    returned = []; burned = []; restored = []; burn_originals = {}
    for entity in originals:
        if len(player.hand) < hand_capacity(player, r.rules):
            r.move(entity, Zone.HAND); returned.append(entity.id); restored.append(_saved(entity))
        else:
            from .allocation_facts import SourceAllocationFact
            burn_originals[entity.id]=SourceAllocationFact.capture(r.state,entity)
            r.move(entity, Zone.GRAVEYARD); burned.append(entity.id)
    root = replace(root, phase='completed', removed=removed, deck_burned=tuple(deck_burned), returned=tuple(returned), burned=tuple(burned),
        restored=tuple(restored), return_deck_before=deck_before, return_deck_after=tuple(player.deck),
        return_rng_before=before, return_rng_after=r.game._rng.getstate())
    r.state.temporary_hands[root.id - 1] = root
    r.emit('temporary_deck_hand_restored', source_id=root.request.source_id, player_id=player.id, **finish_data(root))
    from .deck_shuffles import group
    with group(r,None,player.id,len(removed),root.request.source_id,profile='temporary_return'):
        for eid in deck_returned:
            r.emit('card_moved_to_deck', source_id=root.request.source_id, target_id=eid, player_id=player.id,_deck_insertion_mode='random')
    if deck_returned:
        r.emit('deck_shuffled', player_id=player.id)
    for eid,original in deck_burned.items():
        from .zones import emit_burn
        failure(r,player.id,original.card_id,root.request.source_id,original=original,temporary_hand_id=root.id)
        emit_burn(r,r.state.entities[eid],profile='deck_overflow',original=original,
            source_id=root.request.source_id,player_id=player.id,reason='temporary_deck_return_full')
    for eid in returned:
        r.emit('card_moved_to_hand', source_id=root.request.source_id, target_id=eid, player_id=player.id)
    for eid in burned:
        from .zones import emit_burn
        emit_burn(r,r.state.entities[eid],profile='setaside_overflow',original=burn_originals[eid],
            source_id=root.request.source_id,reason='temporary_hand_return_full')


def expire_start(r, effect):
    if r.ending_turn or not start_window(r.state):
        raise ResolutionError('Temporary deck hand expiry requires a genuine unpublished owner start')
    due = due_start(r.state)
    return [ReturnTemporaryHand(due[-1]), ExpireTemporaryDeckHands()] if due else []


def row_from_dict(raw):
    from .serialization import _row, _list, end_turn_rng_from_json
    row = _row(raw, TemporaryDeckHandReplacement)
    row['request'] = ReplaceHandWithTemporaryDeckCards(**_row(row['request'], ReplaceHandWithTemporaryDeckCards))
    for name in ('originals', 'borrowed', 'restored'):
        row[name] = tuple(SavedHandCard(**_row(value, SavedHandCard)) for value in _list(row[name], name))
    for name in ('deck_basis', 'selected'):
        refs = []
        for value in _list(row[name], name):
            value = _row(value, CardReference); value['zone'] = Zone(value['zone']); refs.append(CardReference(**value))
        row[name] = tuple(refs)
    for name in ('removed', 'deck_burned', 'returned', 'burned', 'return_deck_before', 'return_deck_after'):
        row[name] = tuple(_list(row[name], name))
    for name in ('rng_before', 'rng_after', 'return_rng_before', 'return_rng_after'):
        if row[name] is not None:
            row[name] = end_turn_rng_from_json(row[name])
    return TemporaryDeckHandReplacement(**row)


def validate_shape(state, root, registry, saved):
    root.__post_init__(); req = root.request; registry.card(root.source_card_id)
    if root.turn > state.turn or root.action > state.action_number or req.source_id not in state.entities:
        raise ValueError('Temporary deck hand changed original source or time')
    if root.owner_turn_id > len(state.owner_turn_history):
        raise ValueError('Temporary deck hand lost actual creation interval')
    owner = state.owner_turn_history[root.owner_turn_id - 1]
    if (owner.turn, owner.player_id) != (root.turn, req.player_id) or root.action < owner.start_action:
        raise ValueError('Temporary deck hand changed its owner clock origin')
    if root.phase == 'active':
        index = owner_turn_index(state, req.player_id)
        if state.status != 'playing' or index > owner.owner_index + 1 or (
                index == owner.owner_index + 1 and (not start_window(state) or state.active_player != req.player_id)):
            raise ValueError('Temporary deck hand outlived its actual owner start')
    if root.phase == 'ended' and state.status == 'playing':
        raise ValueError('Playing deck hand cannot claim terminal cleanup')
    for ref in (*root.originals, *root.borrowed, *root.restored):
        entity = state.entities.get(ref.entity_id); registry.card(ref.card_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch or not 1 <= ref.hand_entry_id <= len(state.hand_entries):
            raise ValueError('Unknown temporary deck hand acquisition')
        entry = state.hand_entries[ref.hand_entry_id - 1]
        if (entry.entity_id, entry.player_id) != (ref.entity_id, req.player_id):
            raise ValueError('Temporary deck hand changed its actual acquisition owner')
    for ref in root.originals:
        entry = state.hand_entries[ref.hand_entry_id - 1]
        if entry.zone_epoch >= ref.zone_epoch:
            raise ValueError('Saved deck hand lacks its previous hand acquisition')
        entity = state.entities[ref.entity_id]
        if root.phase in ('active', 'ended'):
            if ref.entity_id in saved or (entity.controller, entity.zone, entity.card_id, entity.zone_epoch, entity.hand_entry_id) != (
                    req.player_id, Zone.SETASIDE, ref.card_id, ref.zone_epoch, ref.hand_entry_id):
                raise ValueError('Saved deck hand changed its private residence')
            saved.add(ref.entity_id)
    for ref in (*root.deck_basis, *root.selected):
        entity = state.entities.get(ref.entity_id); registry.card(ref.card_id)
        if entity is None or ref.zone_epoch > entity.zone_epoch:
            raise ValueError('Temporary deck hand lost its actual physical deck candidate')
    for original, ref in zip(root.selected, root.borrowed):
        entry = state.hand_entries[ref.hand_entry_id - 1]
        if (entry.from_zone, entry.reason, entry.card_id, entry.zone_epoch, entry.turn, entry.action) != (
                Zone.DECK, 'move', original.card_id, original.zone_epoch + 1, root.turn, root.action):
            raise ValueError('Temporary deck hand replaced its accepted deck movement')
        if (ref.card_id, ref.zone_epoch) != (entry.card_id, entry.zone_epoch):
            raise ValueError('Temporary deck hand changed its original borrowed face or epoch')
    for ref in root.restored:
        entry = state.hand_entries[ref.hand_entry_id - 1]
        if (entry.from_zone, entry.reason, entry.card_id, entry.zone_epoch) != (Zone.SETASIDE, 'move', ref.card_id, ref.zone_epoch):
            raise ValueError('Temporary deck hand changed its internal return acquisition')
    if any(eid not in state.entities for eid in (*root.removed, *root.deck_burned, *root.return_deck_before, *root.return_deck_after, *root.burned)):
        raise ValueError('Temporary deck hand includes an unknown physical return body')


def register(mechanics):
    mechanics.register_payload_type(TemporaryDeckHandReplacement)
    mechanics.register(ReplaceHandWithTemporaryDeckCards, start)
    mechanics.register(ExpireTemporaryDeckHands, expire_start)
