"""Private player-owned deck cards, distinct from other SETASIDE residents.

The finite current policy keeps one random physical deck card. Acquisitions
consume an original stored card and use ordinary hand movement/burning. Exact
selection, material and turn priority remain provisional until CN calibration.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass

from .effects import Effect, _integer, _player, _source
from .model import CardType, Zone
from .zones import HAND_TYPES, source_exists

POLICY = 'void-original-keep-one-v1'


@dataclass(frozen=True)
class VoidCard:
    entity_id: int
    card_id: str
    zone_epoch: int

    def __post_init__(self):
        _integer(self.entity_id, 'void entity', 1)
        _integer(self.zone_epoch, 'void residence', 1)
        if type(self.card_id) is not str or not self.card_id.strip():
            raise ValueError('Void residence needs its original card face')

    @property
    def row(self):
        return self.entity_id, self.card_id, self.zone_epoch


@dataclass(frozen=True)
class SendDeckToVoid(Effect):
    player_id: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)


@dataclass(frozen=True)
class GetFromVoid(Effect):
    player_id: int
    count: int = 1
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _source(self.source_id)
        _integer(self.count, 'void acquisition count', 0)


def playable(registry, card_id):
    card = registry.card(card_id)
    if card.kind not in HAND_TYPES or card.kind == CardType.HERO and not card.hero_card:
        raise ValueError('Void stores ordinary playable cards')


def validate_player(state, player, registry):
    if type(player.void_cards) is not tuple or any(type(v) is not VoidCard for v in player.void_cards):
        raise ValueError('Void cards require exact immutable residence records')
    ids = set()
    for card in player.void_cards:
        card.__post_init__(); playable(registry, card.card_id)
        entity = state.entities.get(card.entity_id)
        if (entity is None or card.entity_id in ids or card.entity_id not in player.setaside or
                (entity.controller, entity.zone, entity.card_id, entity.zone_epoch) !=
                (player.id, Zone.SETASIDE, card.card_id, card.zone_epoch)):
            raise ValueError('Void member changed its original private residence')
        ids.add(card.entity_id)


def send(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    player = r.player(effect.player_id)
    validate_player(r.state, player, r.registry)
    originals = tuple(r.state.entities[eid] for eid in player.deck)
    for entity in originals:
        playable(r.registry, entity.card_id)
    before = tuple((e.id, e.card_id, e.zone_epoch) for e in originals)
    kept = (originals[r.game._rng.randrange(len(originals))].id if len(originals) > 1 else
            originals[0].id if originals else None)
    stored = []
    for entity in originals:
        if entity.id == kept:
            continue
        r.move(entity, Zone.SETASIDE)
        if r.game._information is not None:
            r.game._information.conceal(entity.id)
        stored.append(VoidCard(entity.id, entity.card_id, entity.zone_epoch))
    player.void_cards += tuple(stored)
    # Internal consistency facts do not create extra card triggers or expose
    # original faces, physical identities or a new player observation field.
    r.emit('void_deck_stored', player_id=player.id, source_id=effect.source_id,
        amount=len(stored), policy=POLICY, original=before, kept_id=kept,
        stored=tuple(v.row for v in stored), _capture=False)


def acquire(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    player = r.player(effect.player_id)
    validate_player(r.state, player, r.registry)
    if not effect.count or not player.void_cards:
        return
    slot = r.game._rng.randrange(len(player.void_cards)) if len(player.void_cards) > 1 else 0
    card = player.void_cards[slot]
    player.void_cards = player.void_cards[:slot] + player.void_cards[slot + 1:]
    entity = r.state.entities[card.entity_id]
    from .allocation_facts import SourceAllocationFact
    original=SourceAllocationFact.capture(r.state,entity)
    destination = Zone.GRAVEYARD if len(player.hand) >= hand_capacity(player, r.rules) else Zone.HAND
    r.move(entity, destination)
    r.emit('void_card_taken', player_id=player.id, source_id=effect.source_id,
        target_id=entity.id, amount=1, policy=POLICY, card=card.row, _capture=False)
    if destination==Zone.GRAVEYARD:
        from .zones import emit_burn
        emit_burn(r,entity,profile='setaside_overflow',original=original,source_id=effect.source_id)
    else:
        r.emit('card_moved_to_hand',player_id=player.id,source_id=effect.source_id,target_id=entity.id)
    # Reactions and choices to this acquisition precede the next fresh query.
    return [GetFromVoid(player.id, effect.count - 1, effect.source_id)] if effect.count > 1 else None


def _record_row(value, registry, minimum=1):
    if type(value) not in (tuple, list) or len(value) != 3:
        raise ValueError('Invalid private void card receipt')
    eid, cid, epoch = value
    _integer(eid, 'void receipt entity', 1); _integer(epoch, 'void receipt residence', minimum)
    if type(cid) is not str or not cid.strip():
        raise ValueError('Void receipt requires a card face')
    playable(registry, cid)
    return eid, cid, epoch


def validate_boundary(game):
    expected = {1: [], 2: []}
    for event in game._events:
        if event.kind not in ('void_deck_stored', 'void_card_taken'):
            continue
        _player(event.player_id)
        _source(event.source_id)
        data = dict(event.data)
        if event.source_id is not None and event.source_id not in game._state.entities:
            raise ValueError('Private void receipt has an unknown source')
        if event.kind == 'void_deck_stored':
            if (len(event.data) != 4 or set(data) != {'policy', 'original', 'kept_id', 'stored'} or
                    data['policy'] != POLICY or type(data['original']) not in (tuple, list) or
                    type(data['stored']) not in (tuple, list) or event.target_id is not None):
                raise ValueError('Invalid original void deck receipt')
            original = tuple(_record_row(v, game.registry, 0) for v in data['original'])
            stored = tuple(_record_row(v, game.registry) for v in data['stored'])
            ids = tuple(v[0] for v in original)
            if any(eid not in game._state.entities for eid in ids):
                raise ValueError('Void storage refers to an unknown original physical card')
            kept = data['kept_id']
            if (len(set(ids)) != len(ids) or
                    (kept is not None and (type(kept) is not int or kept not in ids)) or
                    (bool(original) != (kept is not None)) or
                    stored != tuple((eid, cid, epoch + 1) for eid, cid, epoch in original if eid != kept) or
                    type(event.amount) is not int or event.amount != len(stored)):
                raise ValueError('Void storage changed its original all-but-one deck')
            if any(v[0] in {old[0] for old in expected[event.player_id]} for v in stored):
                raise ValueError('Void cannot store an already resident physical card')
            expected[event.player_id].extend(stored)
        else:
            if (len(event.data) != 2 or set(data) != {'policy', 'card'} or data['policy'] != POLICY or
                    type(event.amount) is not int or event.amount != 1):
                raise ValueError('Invalid void acquisition receipt')
            card = _record_row(data['card'], game.registry)
            if type(event.target_id) is not int or event.target_id != card[0] or card not in expected[event.player_id]:
                raise ValueError('Void acquisition did not consume an original available member')
            expected[event.player_id].remove(card)
    for pid, player in game._state.players.items():
        validate_player(game._state, player, game.registry)
        if tuple(v.row for v in player.void_cards) != tuple(expected[pid]):
            raise ValueError('Void residence differs from original storage and consumption history')


def register(mechanics):
    mechanics.register(SendDeckToVoid, send)
    mechanics.register(GetFromVoid, acquire)
