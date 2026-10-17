"""Original unselected discovery recipes and one native semantic deck shuffle.

Current committed events witness the one owed continuation, including through
acquisition waits. This establishes consistency, not unsigned origin authority.
"""
from dataclasses import asdict, dataclass
import json

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .discovery import ResolvePoolDiscovery, validate_selection
from .effects import AddToHand, Effect
from .model import Zone
from .pools import GenerationContext

ACCEPTED = 'discovery_remainder_accepted'
FINISHED = 'discovery_remainder_finished'


@dataclass(frozen=True)
class ShuffleDiscoveryRemainder(Effect):
    discovery: ResolvePoolDiscovery
    context: GenerationContext
    created: SourceAllocationFact

    def __post_init__(self):
        if (type(self.discovery) is not ResolvePoolDiscovery or type(self.context) is not GenerationContext or
                type(self.created) is not SourceAllocationFact):
            raise ValueError('Discovery remainder requires its original selection, context and actual creation')
        self.discovery.__post_init__(); self.context.__post_init__(); self.created.__post_init__()
        spec = self.discovery.batch.spec
        if not spec.shuffle_unselected_into_deck or self.discovery.choice_result is None:
            raise ValueError('Discovery remainder requires its declared actual ChoiceResult')
        if (self.created.owner != spec.player_id or self.created.controller != spec.player_id or
                self.created.zone not in (Zone.HAND, Zone.GRAVEYARD)):
            raise ValueError('Discovery remainder lost its actual original hand creation or overflow')


def remainder(work):
    return tuple(cid for cid in work.discovery.offered_card_ids if cid != work.discovery.selection.card_id)


def validate_work(game, work, *, closed=False):
    work.__post_init__()
    validate_selection(game.registry, work.context, work.discovery)
    if work.context != game._generation_context:
        raise ValueError('Discovery remainder changed its original generation context')
    spec = work.discovery.batch.spec
    if spec.source_id not in game._state.entities:
        raise ValueError('Discovery remainder lost its original source')
    if work.discovery.choice_result.choice.id >= game._state.next_choice_id:
        raise ValueError('Discovery remainder borrowed a future choice')
    validate_allocation(game._state, game.registry, work.created, closed=closed)


def emit(r, kind, work, **extra):
    from .continuations import FrameCodec
    spec = work.discovery.batch.spec
    r.emit(kind, source_id=spec.source_id, target_id=work.created.entity_id, player_id=spec.player_id,
        amount=len(remainder(work)), choice_id=work.discovery.choice_result.choice.id,
        receipt=json.dumps(FrameCodec(r.game.mechanics, r.registry).encode(work), ensure_ascii=False,
            sort_keys=True, separators=(',', ':')), _capture=False, **extra)


def begin(r, discovery):
    from .opening import create_hand_card
    spec = discovery.batch.spec
    if discovery.choice_result is None:
        raise ValueError('Unselected shuffle requires the actual complete discovery result')
    # The ordinary creator publishes first; acquisition reactions run before
    # the returned shuffle continuation. Never find a later same-face card.
    entity = create_hand_card(r, AddToHand(spec.player_id, discovery.selection.card_id, spec.source_id))
    work = ShuffleDiscoveryRemainder(discovery, r.game._generation_context,
                                    SourceAllocationFact.capture(r.state, entity))
    emit(r, ACCEPTED, work)
    return (work,)


def ledger(game):
    if not any(e.kind in (ACCEPTED, FINISHED) for e in game._events): return {}
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    events = effective_events(game._events)
    codec = FrameCodec(game.mechanics, game.registry)
    pending, finished = {}, set()
    created_events = {e.target_id:e for e in events if e.kind == 'card_created'}
    insertions = {}
    for event in events:
        marker = dict(event.data).get('deck_insertion')
        if type(marker) is tuple and len(marker) == 6 and marker[0] == 'random':
            insertions.setdefault(marker[1], []).append(event)
        if event.kind not in (ACCEPTED, FINISHED): continue
        data = dict(event.data)
        expected = {'choice_id', 'receipt'} if event.kind == ACCEPTED else {'choice_id', 'receipt', 'shuffle_id', 'cards'}
        if set(data) != expected or type(data['receipt']) is not str:
            raise ValueError('Complete original discovery remainder event required')
        work = codec.decode(json.loads(data['receipt']))
        if type(work) is not ShuffleDiscoveryRemainder:
            raise ValueError('Discovery remainder event has another work type')
        validate_work(game, work, closed=True)
        spec = work.discovery.batch.spec; key = work.discovery.choice_result.choice.id
        if (data['choice_id'] != key or (event.source_id, event.target_id, event.player_id, event.amount) !=
                (spec.source_id, work.created.entity_id, spec.player_id, len(remainder(work)))):
            raise ValueError('Discovery remainder event changed its original domain')
        if event.kind == ACCEPTED:
            creation = created_events.get(work.created.entity_id)
            if (key in pending or key in finished or creation is None or creation.sequence >= event.sequence or
                    creation.action != event.action or (creation.source_id, creation.player_id) != (spec.source_id, spec.player_id)):
                raise ValueError('Discovery remainder lost its actual unique original creation')
            pending[key] = (work, event.sequence)
        else:
            if type(data['cards']) is not str:
                raise ValueError('Discovery remainder requires complete actual deck allocations')
            if key not in pending or pending[key][0] != work or key in finished:
                raise ValueError('Discovery remainder shuffled without its original accepted result')
            original, accepted_at = pending.pop(key)
            cards = tuple(allocation_from_dict(x) for x in json.loads(data['cards']))
            expected_ids = remainder(work)
            if tuple(f.card_id for f in cards) != expected_ids or len({f.entity_id for f in cards}) != len(cards):
                raise ValueError('Discovery remainder changed its original unselected recipe order')
            if not cards:
                if data['shuffle_id'] is not None: raise ValueError('Empty remainder invented a shuffle')
            else:
                sid = data['shuffle_id']
                if type(sid) is not int or not 1 <= sid <= len(game._state.deck_shuffle_history):
                    raise ValueError('Discovery remainder lost its actual semantic shuffle')
                row = game._state.deck_shuffle_history[sid-1]
                members = insertions.get(sid, ())
                if ((row.actor_id, row.player_id, row.declared_count, row.profile) !=
                        (spec.player_id, spec.player_id, len(cards), 'semantic') or
                        row.source is None or row.source.entity_id != spec.source_id or len(members) != len(cards)):
                    raise ValueError('Discovery remainder borrowed another shuffle producer')
                for fact, member in zip(cards, members):
                    validate_allocation(game._state, game.registry, fact, closed=True)
                    if ((fact.owner, fact.controller, fact.zone) != (spec.player_id, spec.player_id, Zone.DECK) or
                            member.kind != 'card_added_to_deck' or member.target_id != fact.entity_id or
                            member.source_id != spec.source_id or member.action != event.action or
                            not accepted_at < member.sequence < event.sequence):
                        raise ValueError('Discovery remainder lost an actual original new deck entry')
            finished.add(key)
    return {key:work for key,(work, _) in pending.items()}


def shuffle(r, work):
    from .deck_shuffles import ShuffleDeckCards, execute
    from .zones import AddToDeck
    validate_work(r.game, work)
    key = work.discovery.choice_result.choice.id
    if ledger(r.game).get(key) != work:
        raise ValueError('Stale or foreign original discovery remainder')
    spec = work.discovery.batch.spec; before = len(r.state.deck_shuffle_history)
    cursor = len(r.game._events)
    entries = tuple(AddToDeck(spec.player_id, cid, 'random', spec.source_id) for cid in remainder(work))
    execute(r, ShuffleDeckCards(spec.player_id, spec.player_id, entries, spec.source_id))
    sid = r.state.deck_shuffle_history[-1].id if len(r.state.deck_shuffle_history) > before else None
    cards = tuple(SourceAllocationFact.capture(r.state, r.state.entities[e.target_id])
        for e in r.game._events[cursor:] if e.kind == 'card_added_to_deck')
    emit(r, FINISHED, work, shuffle_id=sid,
         cards=json.dumps([asdict(f) for f in cards], ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    return ()


def validate_boundary(game):
    from .summon_quantities import walk_work
    pending = ledger(game)
    frame = game._frame
    queue = (*frame.prefix, *frame.continuation) if frame else ()
    controls = tuple(w for w in queue if type(w) is ShuffleDiscoveryRemainder)
    if frame and any(type(w) is ShuffleDiscoveryRemainder for w in walk_work(frame.options)):
        raise ValueError('Choice cannot inject discovery remainder control')
    if len(controls) != len({w.discovery.choice_result.choice.id for w in controls}):
        raise ValueError('Discovery remainder queued twice')
    actual = {w.discovery.choice_result.choice.id:w for w in controls}
    if actual != pending and (frame is not None or game._state.status == 'playing'):
        raise ValueError('Discovery remainder lost its original owed shuffle continuation')
    if actual and actual != pending: raise ValueError('Discovery remainder retains foreign terminal work')
    for work in controls: validate_work(game, work)
    if frame:
        original = tuple(w for w in frame.paid_hand_choice_boundary.work if type(w) is ShuffleDiscoveryRemainder)
        if controls != original:
            raise ValueError('Discovery remainder differs from its original complete choice boundary')


def register(mechanics):
    mechanics.register(ShuffleDiscoveryRemainder, shuffle)
