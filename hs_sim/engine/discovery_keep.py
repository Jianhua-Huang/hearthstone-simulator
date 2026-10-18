"""An owned original Discover/Corpse branch; existing resource/creation executors."""
from dataclasses import dataclass, replace
import json

from .allocation_facts import SourceAllocationFact, validate_allocation
from .discovery import ResolvePoolDiscovery, pick_requests, validate_selection
from .effects import AddToHand, Effect, SpendResource, _integer
from .model import Resource, Zone
from .pools import GenerationContext

ACCEPTED = 'discovery_keep_accepted'
PROGRESSED = 'discovery_keep_progressed'
FINISHED = 'discovery_keep_finished'


@dataclass(frozen=True)
class KeepPoolDiscovery(Effect):
    discovery: ResolvePoolDiscovery
    context: GenerationContext
    payment: str = 'pending'
    bank_before: int | None = None
    spend_id: int | None = None
    created: tuple[SourceAllocationFact, ...] = ()

    def __post_init__(self):
        if type(self.discovery) is not ResolvePoolDiscovery or type(self.context) is not GenerationContext:
            raise ValueError('Keep requires its complete original discovery and context')
        self.discovery.__post_init__(); self.context.__post_init__()
        spec = self.discovery.batch.spec
        if spec.keep_all_corpse_cost is None or self.discovery.choice_result is None:
            raise ValueError('Keep requires its declared actual original choice')
        if self.payment not in ('pending','paid','insufficient'):
            raise ValueError('Unknown original discovery payment stage')
        if type(self.created) is not tuple or any(type(f) is not SourceAllocationFact for f in self.created):
            raise ValueError('Keep requires complete actual creation allocations')
        for fact in self.created: fact.__post_init__()
        if len({f.entity_id for f in self.created}) != len(self.created):
            raise ValueError('Keep reused an original creation allocation')
        if self.payment == 'pending':
            if self.bank_before is not None or self.spend_id is not None or self.created:
                raise ValueError('Unpaid original keep cannot preclaim payment or delivery')
        else:
            _integer(self.bank_before,'original keep Corpse bank',0)
            if self.payment == 'paid': _integer(self.spend_id,'original keep debit',1)
            if ((self.payment == 'paid') != (self.bank_before >= spec.keep_all_corpse_cost) or
                    self.payment == 'insufficient' and self.spend_id is not None):
                raise ValueError('Keep changed its original Corpse branch')
        expected = cards_for(self)
        if tuple(f.card_id for f in self.created) != expected[:len(self.created)] or len(self.created) > len(expected):
            raise ValueError('Keep changed the original ordered card delivery prefix')
        if any((f.owner,f.controller) != (spec.player_id,spec.player_id) or
                f.zone not in (Zone.HAND,Zone.GRAVEYARD) for f in self.created):
            raise ValueError('Keep lost an original hand creation or overflow')


def key(work): return work.discovery.choice_result.choice.id


def cards_for(work):
    d = work.discovery
    if work.payment == 'pending': return ()
    return (d.selection.card_id,) + (tuple(cid for cid in d.offered_card_ids if cid != d.selection.card_id)
        if work.payment == 'paid' else ())


def validate_work(game, work):
    work.__post_init__()
    validate_selection(game.registry,work.context,work.discovery)
    if work.context != game._generation_context:
        raise ValueError('Keep changed its original generation context')
    from .discovery_offers import offer_for_result
    offer = offer_for_result(game,work.discovery.choice_result)
    option = next(o for o in offer.options if o.id in work.discovery.choice_result.selected_ids)
    if (len(option.effects) != 1 or type(option.effects[0]) is not ResolvePoolDiscovery or
            replace(option.effects[0],choice_result=work.discovery.choice_result) != work.discovery):
        raise ValueError('Keep borrowed another original offered recipe')
    spec = work.discovery.batch.spec
    if work.spend_id is not None:
        rows = game._state.corpse_spend_history
        if work.spend_id > len(rows): raise ValueError('Keep borrowed a future Corpse debit')
        row = rows[work.spend_id-1]
        if (row.player_id,row.amount,row.balance_before,row.origin) != (
                spec.player_id,spec.keep_all_corpse_cost,work.bank_before,'fixed'):
            raise ValueError('Keep differs from its original actual Corpse debit')
    for fact in work.created: validate_allocation(game._state,game.registry,fact,closed=True)


def emit(r, kind, work):
    from .continuations import FrameCodec
    spec = work.discovery.batch.spec
    r.emit(kind,source_id=spec.source_id,player_id=spec.player_id,amount=len(work.created),
        choice_id=key(work),receipt=json.dumps(FrameCodec(r.game.mechanics,r.registry).encode(work),
            ensure_ascii=False,sort_keys=True,separators=(',',':')),_capture=False)


def begin(r, discovery):
    work = KeepPoolDiscovery(discovery,r.game._generation_context)
    validate_work(r.game,work); emit(r,ACCEPTED,work)
    return (work,)


def ledger(game):
    if not any(e.kind in (ACCEPTED,PROGRESSED,FINISHED) for e in game._events): return {}
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    from .resources import corpse_spend_from_event
    events = effective_events(game._events)
    codec = FrameCodec(game.mechanics,game.registry)
    creations = {e.target_id:e for e in events if e.kind == 'card_created'}
    debits = {row.id:e for e in events if (row:=corpse_spend_from_event(e)) is not None}
    skipped = [e for e in events if e.kind == 'resource_payment_skipped']
    pending, finished, used_debits, used_creations = {}, set(), set(), set()
    for event in events:
        if event.kind not in (ACCEPTED,PROGRESSED,FINISHED): continue
        data = dict(event.data)
        if set(data) != {'choice_id','receipt'} or type(data['receipt']) is not str:
            raise ValueError('Keep lost its complete original progress receipt')
        work = codec.decode(json.loads(data['receipt']))
        if type(work) is not KeepPoolDiscovery: raise ValueError('Keep progress has another work type')
        validate_work(game,work); spec = work.discovery.batch.spec; identity = key(work)
        if (data['choice_id'] != identity or (event.source_id,event.player_id,event.amount) !=
                (spec.source_id,spec.player_id,len(work.created))):
            raise ValueError('Keep progress changed its original domain')
        if event.kind == ACCEPTED:
            from .card_discoveries import require_original_result
            origin = require_original_result(game._state,work.discovery.choice_result)
            if (identity in pending or identity in finished or work.payment != 'pending' or
                    event.sequence <= origin.publication_event):
                raise ValueError('Keep accepted twice or preclaimed delivery')
            pending[identity] = (work,event.sequence)
            continue
        if identity not in pending: raise ValueError('Keep progressed without its original acceptance')
        old, cursor = pending[identity]
        if (old.discovery,old.context) != (work.discovery,work.context):
            raise ValueError('Keep progress borrowed another original offer')
        if event.kind == FINISHED:
            if old != work or work.payment == 'pending' or len(work.created) != len(cards_for(work)):
                raise ValueError('Keep finished before its complete original delivery')
            pending.pop(identity); finished.add(identity); continue
        if old.payment == 'pending':
            if work.payment == 'pending' or work.created:
                raise ValueError('Keep lost its one actual payment transition')
            if work.payment == 'paid':
                debit = debits.get(work.spend_id)
                if debit is None or not cursor < debit.sequence < event.sequence or debit.action != event.action:
                    raise ValueError('Keep borrowed a debit outside its original payment window')
                if work.spend_id in used_debits: raise ValueError('Independent keep groups shared one actual Corpse debit')
                used_debits.add(work.spend_id)
            elif not any(cursor < e.sequence < event.sequence and e.action == event.action and
                    e.player_id == spec.player_id and dict(e.data).get('resource') == Resource.CORPSES.value and
                    dict(e.data).get('required') == spec.keep_all_corpse_cost for e in skipped):
                raise ValueError('Keep lost its original insufficient-resource branch')
        else:
            if ((old.payment,old.bank_before,old.spend_id) != (work.payment,work.bank_before,work.spend_id) or
                    len(work.created) != len(old.created)+1 or work.created[:-1] != old.created):
                raise ValueError('Keep shortened/reordered its original delivery progress')
            fact = work.created[-1]; creation = creations.get(fact.entity_id)
            if fact.entity_id in used_creations: raise ValueError('Independent keep groups shared one actual creation')
            used_creations.add(fact.entity_id)
            if (creation is None or not cursor < creation.sequence < event.sequence or creation.action != event.action or
                    (creation.source_id,creation.player_id) != (spec.source_id,spec.player_id)):
                raise ValueError('Keep lost its actual original card creation')
        pending[identity] = (work,event.sequence)
    return {identity:work for identity,(work,_) in pending.items()}


def advance(r, work):
    validate_work(r.game,work)
    if ledger(r.game).get(key(work)) != work: raise ValueError('Stale original discovery keep continuation')
    spec = work.discovery.batch.spec
    if work.payment == 'pending':
        from .resources import resource_effect
        before = r.player(spec.player_id).resources[Resource.CORPSES]
        count = len(r.state.corpse_spend_history)
        resource_effect(r,SpendResource(spec.player_id,Resource.CORPSES,spec.keep_all_corpse_cost))
        spent = r.state.corpse_spend_history[count:]
        if len(spent) > 1: raise ValueError('One original keep cannot perform multiple Corpse debits')
        new = replace(work,payment='paid' if spent else 'insufficient',bank_before=before,
            spend_id=spent[0].id if spent else None)
        emit(r,PROGRESSED,new); return (new,)
    cards = cards_for(work)
    if len(work.created) == len(cards): emit(r,FINISHED,work); return ()
    index = len(work.created)
    request = (pick_requests(spec,work.discovery.selection)[0] if index == 0 else
        AddToHand(spec.player_id,cards[index],spec.source_id))
    from .opening import create_hand_card
    cursor = len(r.game._events); entity = create_hand_card(r,request)
    new = replace(work,created=(*work.created,SourceAllocationFact.capture(r.state,entity)))
    emit(r,PROGRESSED,new)
    if index == 0:
        from .discovery_delivery import finish_for_entity
        return (finish_for_entity(r,work.discovery.choice_result,entity,request,cursor),new)
    return (new,)


def validate_boundary(game):
    from .summon_quantities import walk_work
    pending = ledger(game); frame = game._frame
    queue = (*frame.prefix,*frame.continuation) if frame else ()
    controls = tuple(w for w in queue if type(w) is KeepPoolDiscovery)
    if frame and any(type(w) is KeepPoolDiscovery for w in walk_work(frame.options)):
        raise ValueError('Choice cannot inject original discovery keep control')
    if len(controls) != len({key(w) for w in controls}): raise ValueError('Keep continuation queued twice')
    actual = {key(w):w for w in controls}
    if actual != pending and (frame is not None or game._state.status == 'playing'):
        raise ValueError('Keep lost/changed its complete original owed continuation')
    if actual and actual != pending: raise ValueError('Keep retained foreign terminal continuation')
    if frame and controls != tuple(w for w in frame.paid_hand_choice_boundary.work if type(w) is KeepPoolDiscovery):
        raise ValueError('Keep differs from its original complete choice boundary')


def register(mechanics): mechanics.register(KeepPoolDiscovery,advance)
