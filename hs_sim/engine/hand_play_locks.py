"""Finite hand play prohibition; no price manipulation or second turn clock."""
from dataclasses import dataclass
from .effects import Effect, _integer, _player
from .lifecycle import attachment_id
from .model import CardType, Enchantment, HandPlayLock, OtherCardPlayLock, Zone
from .owner_turns import owner_turn_index
from .timed_keywords import owner_deadline, validate_deadline
from .zones import CardReference, reference_entity, reference_value, source_exists


@dataclass(frozen=True)
class LockHandCard(Effect):
    card: CardReference
    owner_starts: int
    source_id: int

    def __post_init__(self):
        reference_value(self.card); _integer(self.owner_starts,'hand lock owner starts',1); _integer(self.source_id,'hand lock source',1)
        if self.card.zone != Zone.HAND: raise ValueError('Hand play lock requires an original hand arrival')


def validate_clock(state, lock):
    if type(lock) is OtherCardPlayLock:
        lock.__post_init__()
        if lock.created_turn > state.turn or lock.after_play_id > len(state.play_history):
            raise ValueError('Hand play gate borrowed a future creation or hand play')
        return
    if type(lock) is not HandPlayLock: raise ValueError('Hand play lock requires its typed original deadline')
    lock.__post_init__(); validate_deadline(state,lock.deadline,lock.owner_starts)


def play_error(state, source):
    if source.zone != Zone.HAND: return None
    for attachment in source.enchantments:
        lock=attachment.hand_play_lock
        if lock is None: continue
        validate_clock(state,lock)
        if type(lock) is OtherCardPlayLock:
            if not any(p.id > lock.after_play_id and p.player_id == lock.player_id and
                    p.completed and p.source_id != source.id for p in state.play_history):
                return 'This card is locked until another card is played'
            continue
        if owner_turn_index(state,lock.deadline.player_id)<lock.deadline.owner_turn_index:
            return 'This card is temporarily prohibited from being played'
    return None


def attach_after_other_play(state, entity, source_id):
    _integer(source_id, 'original hand gate source', 1)
    if source_id not in state.entities or entity.kind != CardType.MINION:
        raise ValueError('Created hand gate requires its real source and fresh minion')
    # Include already allocated in-flight plays: the card whose body creates
    # this carrier is not a later other card merely because it finishes later.
    lock = OtherCardPlayLock(entity.controller, len(state.play_history), state.turn)
    validate_clock(state, lock)
    entity.enchantments.append(Enchantment(attachment_id(state), source_id=source_id,
        label='hand_play_lock', hand_play_lock=lock))


def lock_hand_card(r, effect):
    validate_request(r.state,r.registry,effect); source_exists(r,effect.source_id)
    entity=reference_entity(r,effect.card)
    if entity is None: return ()
    lock=HandPlayLock(owner_deadline(r.state,effect.card.player_id,occurrences=effect.owner_starts),effect.owner_starts)
    entity.enchantments.append(Enchantment(attachment_id(r.state),source_id=effect.source_id,label='hand_play_lock',hand_play_lock=lock))
    # The typed zero-stat marker is retained after expiry, like other consumed
    # local material. Its gate becomes inert on the original clock; ordinary
    # current copies preserve it, resets remove it. No public hidden-card event.


def validate_request(state,registry,effect):
    effect.__post_init__();registry.card(effect.card.card_id)
    entity=state.entities.get(effect.card.entity_id)
    if effect.source_id not in state.entities or entity is None or effect.card.zone_epoch>entity.zone_epoch:
        raise ValueError('Hand play lock requires existing original allocations and a known hand residency')


@dataclass(frozen=True)
class TrapRandomHandCards(Effect):
    player_id: int
    count: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id);_integer(self.count,'random trapped hand count',1)
        _integer(self.source_id,'random hand trap source',1)


def validate_random_request(state,effect):
    effect.__post_init__()
    if effect.source_id not in state.entities:
        raise ValueError('Random hand trap requires an existing original source')


def trap_random_hand_cards(r,effect):
    validate_random_request(r.state,effect)
    cards=tuple(CardReference.capture(r.state.entities[i])for i in r.player(effect.player_id).hand)
    if not cards:return ()
    selected=set(r.game._rng.sample(range(len(cards)),effect.count))if len(cards)>effect.count else set(range(len(cards)))
    # One current/upcoming actual target turn. Other players' or skipped turns
    # cannot expire the existing owner-clock gates. Keep physical hand order.
    starts=1 if r.state.active_player==effect.player_id else 2
    for index,card in enumerate(cards):
        if index in selected:lock_hand_card(r,LockHandCard(card,starts,effect.source_id))
    return ()


def register(mechanics):
    mechanics.register_payload_type(OtherCardPlayLock)
    mechanics.register(LockHandCard,lock_hand_card)
    mechanics.register(TrapRandomHandCards,trap_random_hand_cards)
