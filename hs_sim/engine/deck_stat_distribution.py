"""Balanced stored stat pairs, shared buffs, and one original random remainder."""
from dataclasses import asdict, dataclass
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer, _player, _source
from .hand_upgrades import BuffStoredCard, buff_stored_card
from .model import CardType, Zone, validate_end_turn_rng
from .zones import CardReference, source_exists

EVENT = 'deck_stat_pairs_distributed'


def integers(values, label):
    if type(values) is not tuple:
        raise ValueError(label + ' must be an immutable tuple')
    for value in values:
        _integer(value, label, 1)
    if len(set(values)) != len(values):
        raise ValueError(label + ' cannot contain duplicates')


@dataclass(frozen=True)
class DeckStatDistributionFact:
    player_id: int
    source: SourceAllocationFact | None
    pairs: int
    candidates: tuple[SourceAllocationFact, ...]
    selected: tuple[int, ...]
    enchantment_ids: tuple[int, ...]
    buff_offsets: tuple[int, ...]
    rng_before: tuple
    rng_after: tuple

    @property
    def amounts(self):
        if not self.candidates:
            return ()
        base = self.pairs // len(self.candidates)
        selected = set(self.selected)
        return tuple(base + int(f.entity_id in selected) for f in self.candidates)

    def __post_init__(self):
        _player(self.player_id); _integer(self.pairs, 'stat pairs', 0)
        if self.source is not None:
            if type(self.source) is not SourceAllocationFact:
                raise ValueError('Stat distribution requires its complete original source')
            self.source.__post_init__()
        if type(self.candidates) is not tuple or any(type(f) is not SourceAllocationFact for f in self.candidates):
            raise ValueError('Stat distribution requires its complete original physical deck inventory')
        for fact in self.candidates:
            fact.__post_init__()
            if (fact.kind, fact.zone, fact.controller) != (CardType.MINION, Zone.DECK, self.player_id):
                raise ValueError('Distribution candidate is not an original controlled deck minion')
        ids = tuple(f.entity_id for f in self.candidates)
        integers(ids, 'original deck identities'); integers(self.selected, 'random remainder identities')
        integers(self.enchantment_ids, 'stat attachments'); integers(self.buff_offsets, 'stat notification offsets')
        remainder = self.pairs % len(ids) if ids else 0
        if len(self.selected) != remainder or not set(self.selected).issubset(ids):
            raise ValueError('Distribution changed its original balanced remainder')
        if len(self.enchantment_ids) != len(self.buff_offsets) or len(self.buff_offsets) != sum(v > 0 for v in self.amounts):
            raise ValueError('Distribution omitted or duplicated an actual positive buff')
        if any(a <= b for a,b in zip(self.buff_offsets,self.buff_offsets[1:])):
            raise ValueError('Distribution changed its original notification order')
        validate_end_turn_rng(self.rng_before); validate_end_turn_rng(self.rng_after)
        local = Random(); local.setstate(self.rng_before)
        selected = tuple(local.sample(ids, remainder)) if remainder else ()
        if selected != self.selected or local.getstate() != self.rng_after:
            raise ValueError('Distribution changed its original random remainder or RNG state')


@dataclass(frozen=True)
class DistributeDeckStatPairs(Effect):
    player_id: int
    pairs: int
    source_id: int | None = None

    def __post_init__(self):
        _player(self.player_id); _integer(self.pairs, 'stat pairs', 0); _source(self.source_id)


def distribute(r, effect):
    effect.__post_init__(); source_exists(r, effect.source_id)
    source = SourceAllocationFact.capture(r.state, r.state.entities.get(effect.source_id))
    candidates = tuple(SourceAllocationFact.capture(r.state, r.state.entities[eid])
        for eid in r.state.players[effect.player_id].deck
        if r.registry.card(r.state.entities[eid].card_id).kind == CardType.MINION)
    ids = tuple(f.entity_id for f in candidates)
    base,remainder = divmod(effect.pairs, len(ids)) if ids else (0,0)
    before = r.game._rng.getstate()
    selected = tuple(r.game._rng.sample(ids,remainder)) if remainder else ()
    after = r.game._rng.getstate(); chosen = set(selected)
    pending = []; attachments = []
    # Ordinary stat application and lifecycle rules are shared. All accepted
    # recipients are changed before the first acquisition/buff reaction runs.
    for fact in candidates:
        amount = base + int(fact.entity_id in chosen)
        if not amount:
            continue
        ref = CardReference(fact.entity_id,effect.player_id,Zone.DECK,fact.card_id,fact.zone_epoch)
        buff_stored_card(r, BuffStoredCard(ref,amount,amount,effect.source_id), pending_events=pending)
        attachments.append(r.state.entities[fact.entity_id].enchantments[-1].id)
    cursors = tuple(r.emit(kind,**data).sequence for kind,data in pending)
    cursor = len(r.game._events) + 1
    fact = DeckStatDistributionFact(effect.player_id,source,effect.pairs,candidates,selected,
        tuple(attachments),tuple(cursor-c for c in cursors),before,after)
    r.emit(EVENT,source_id=effect.source_id,player_id=effect.player_id,
        fact=json.dumps(asdict(fact),sort_keys=True,separators=(',',':')))
    return ()


def from_dict(value):
    from .serialization import _list, _row, end_turn_rng_from_json
    row = _row(value,DeckStatDistributionFact)
    row['source'] = allocation_from_dict(row['source'])
    row['candidates'] = tuple(allocation_from_dict(f) for f in _list(row['candidates'],'original deck minions'))
    for name in ('selected','enchantment_ids','buff_offsets'):
        row[name] = tuple(_list(row[name],name))
    for name in ('rng_before','rng_after'):
        row[name] = end_turn_rng_from_json(row[name])
    return DeckStatDistributionFact(**row)


def validate_events(game):
    from .hero_health_history import effective_events
    events = tuple(effective_events(game._events)); by_sequence = {e.sequence:e for e in events}
    seen_buffs = set(); seen_attachments = set()
    for event in events:
        if event.kind != EVENT:
            continue
        if set(dict(event.data)) != {'fact'} or type(dict(event.data)['fact']) is not str:
            raise ValueError('Distribution requires its complete private original fact')
        fact = from_dict(json.loads(dict(event.data)['fact']))
        source_id = None if fact.source is None else fact.source.entity_id
        if (event.source_id,event.player_id,event.target_id) != (source_id,fact.player_id,None):
            raise ValueError('Distribution changed its original source or receiving player')
        for allocation in (*fact.candidates, *((fact.source,) if fact.source is not None else ())):
            validate_allocation(game._state,game.registry,allocation,closed=True)
        if any(i >= game._state.next_attachment_id or i in seen_attachments for i in fact.enchantment_ids):
            raise ValueError('Distribution borrowed a future or already allocated stat attachment')
        seen_attachments.update(fact.enchantment_ids)
        recipients = tuple((f,amount) for f,amount in zip(fact.candidates,fact.amounts) if amount)
        for (candidate,amount),offset in zip(recipients,fact.buff_offsets):
            cursor = event.sequence-offset; buff = by_sequence.get(cursor)
            if (cursor in seen_buffs or buff is None or buff.kind != 'stored_card_buffed' or
                    (buff.source_id,buff.player_id,buff.target_id,buff.action) !=
                        (source_id,fact.player_id,candidate.entity_id,event.action) or
                    dict(buff.data) != {'attack_delta':amount,'health_delta':amount}):
                raise ValueError('Distribution differs from its actual original stat notifications')
            seen_buffs.add(cursor)


def register(mechanics):
    mechanics.register(DistributeDeckStatPairs,distribute)
