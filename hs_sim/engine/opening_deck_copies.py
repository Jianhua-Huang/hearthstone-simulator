"""Finite native pre-opening copies of the opponent's submitted physical deck.

Construction and original-deck provenance remain immutable. Copies participate
in opening hooks without recursively repeating deck construction. Sampling and
copied sideboard qualification remain explicit CN-pending policies.
"""
from dataclasses import asdict,dataclass,replace
import json
from random import Random

from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .deck_size_rules import DeckSizeRule
from .errors import ResolutionError
from .model import Zone,validate_end_turn_rng

SOURCE='JAIL_430'
COUNT=20
POLICY='pre-opening-original-opponent-v1'
EVENT='opening_deck_copied'


@dataclass(frozen=True)
class OpeningDeckCopy:
    source: SourceAllocationFact
    candidates: tuple[SourceAllocationFact,...]
    selected: tuple[SourceAllocationFact,...]
    deliveries: tuple[SourceAllocationFact,...]
    rng_before: tuple
    rng_after: tuple
    policy: str = POLICY

    def __post_init__(self):
        if type(self.source) is not SourceAllocationFact:raise ValueError('Opening copy requires its original native source')
        self.source.__post_init__()
        if self.policy!=POLICY or self.source.card_id!=SOURCE or self.source.zone!=Zone.DECK:
            raise ValueError('Unreviewed native opening deck-copy profile')
        for name in ('candidates','selected','deliveries'):
            values=getattr(self,name)
            if type(values)is not tuple or any(type(f)is not SourceAllocationFact for f in values):
                raise ValueError('Opening deck-copy facts must be complete immutable tuples')
            for fact in values:fact.__post_init__()
            if len({f.entity_id for f in values})!=len(values):raise ValueError('Opening deck-copy reused a physical slot')
        if len(self.candidates)<COUNT or len(self.selected)!=COUNT or len(self.deliveries)!=COUNT:
            raise ValueError('Opening copy requires twenty actual opponent slots and deliveries')
        validate_end_turn_rng(self.rng_before);validate_end_turn_rng(self.rng_after)
        rng=Random();rng.setstate(self.rng_before)
        if tuple(rng.sample(self.candidates,COUNT))!=self.selected or rng.getstate()!=self.rng_after:
            raise ValueError('Opening deck-copy changed its actual original sample')


def from_dict(raw):
    from .serialization import _row,_list,end_turn_rng_from_json
    values=_row(raw,OpeningDeckCopy)
    values['source']=allocation_from_dict(values['source'])
    for name in ('candidates','selected','deliveries'):
        values[name]=tuple(allocation_from_dict(f)for f in _list(values[name],name))
    for name in ('rng_before','rng_after'):values[name]=end_turn_rng_from_json(values[name])
    return OpeningDeckCopy(**values)


def payload(row):return json.dumps(asdict(row),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def hook_pairs(state,player_id):
    opening=state.opening
    if opening is None:return ()
    original=tuple(zip(opening.original_entities[player_id-1],state.players[player_id].original_deck))
    copied=tuple((f.entity_id,f.card_id)for row in opening.deck_copies if row.source.controller==player_id for f in row.deliveries)
    return (*original,*copied)


def is_hook_source(state,source_id,player_id,card_id):
    return state.opening is not None and state.opening.stage=='dealing' and (source_id,card_id)in hook_pairs(state,player_id)


def is_copied_source(state,source_id,player_id):
    return state.opening is not None and any(f.entity_id==source_id
        for row in state.opening.deck_copies if row.source.controller==player_id for f in row.deliveries)


def prepare(r):
    """One synchronous preparation before shuffle, hooks, dealing or choices."""
    opening=r.state.opening
    if opening is None or opening.stage!='dealing' or opening.deck_copies:
        raise ResolutionError('Opening deck composition requires its genuine unprepared beginning')
    sources=tuple((pid,eid)for pid in (1,2)for eid,cid in zip(opening.original_entities[pid-1],r.player(pid).original_deck)if cid==SOURCE)
    if not sources:return
    if r.registry.deck_size_rules.get(SOURCE)!=DeckSizeRule(SOURCE,COUNT):
        raise ResolutionError('Native opening copy lacks its original twenty-card construction rule')
    domains={pid:tuple(SourceAllocationFact.capture(r.state,r.state.entities[eid])for eid in opening.original_entities[pid-1])for pid in (1,2)}
    for pid,eid in sources:
        if len(domains[pid])!=COUNT or len(domains[3-pid])<COUNT:
            raise ResolutionError('Azalina requires twenty original own cards and at least twenty original opponent slots')
    from .zones import CardReference,CopyCard,copy_physical_card,announce_copied_card
    records=[];notifications=[]
    for pid,eid in sources:
        before=r.game._rng.getstate();candidates=domains[3-pid]
        selected=tuple(r.game._rng.sample(candidates,COUNT));after=r.game._rng.getstate()
        delivered=[]
        for fact in selected:
            r.charge()
            request=CopyCard(CardReference(fact.entity_id,fact.controller,Zone.DECK,fact.card_id,fact.zone_epoch),
                pid,mode='base',destination=Zone.DECK,position='bottom',source_id=eid)
            entity=copy_physical_card(r,request,publish=False)
            if entity is None:raise ResolutionError('Original opening copy did not allocate its accepted physical slot')
            delivered.append(SourceAllocationFact.capture(r.state,entity));notifications.append((entity,request,fact.entity_id))
        source=next(f for f in domains[pid]if f.entity_id==eid)
        records.append(OpeningDeckCopy(source,candidates,selected,tuple(delivered),before,after))
    # Every origin and completed delivery exists before any observer captures
    # state. This also preserves immutable origins in suspended RuleContexts.
    r.state.opening=replace(opening,deck_copies=tuple(records))
    for row in records:
        r.emit(EVENT,source_id=row.source.entity_id,player_id=row.source.controller,amount=COUNT,receipt=payload(row),_capture=False)
    for entity,request,origin in notifications:announce_copied_card(r,entity,request,origin)


def validate_boundary(game):
    opening=game._state.opening
    if opening is None:return
    from .opening import original_deck_entities
    from .hero_health_history import effective_events
    setup=game._match_setup
    if setup is None:raise ValueError('Prepared opening copies require the original constructed match')
    groups=original_deck_entities(setup)
    expected=tuple((pid,eid)for pid in (1,2)for eid,cid in zip(groups[pid-1],setup.decks[pid-1].cards)if cid==SOURCE)
    if tuple((row.source.controller,row.source.entity_id)for row in opening.deck_copies)!=expected:
        raise ValueError('Opening composition lost its complete original native sources')
    if not expected:return
    if game.registry.deck_size_rules.get(SOURCE)!=DeckSizeRule(SOURCE,COUNT):raise ValueError('Opening copy lacks original construction qualification')
    initial_next=1+sum(2+len(d.cards)for d in setup.decks)
    cursor=initial_next;rng=Random(setup.seed)
    if setup.first_player is None and rng.choice((1,2))!=opening.first_player:raise ValueError('Opening copy changed the genuine first-player draw')
    events=effective_events(game._events)
    receipts=[e for e in events if e.kind==EVENT]
    if len(receipts)!=len(expected):raise ValueError('Opening copy lost its complete accepted receipts')
    for row,event in zip(opening.deck_copies,receipts):
        row.__post_init__();pid=row.source.controller
        if row.rng_before!=rng.getstate():raise ValueError('Opening copy changed its original RNG prefix')
        rng.setstate(row.rng_after)
        expected_candidates=tuple(zip(groups[2-pid],setup.decks[2-pid].cards))
        if tuple((f.entity_id,f.card_id)for f in row.candidates)!=expected_candidates:
            raise ValueError('Opening copy cropped or replaced the original opponent domain')
        for f in (row.source,*row.candidates):
            validate_allocation(game._state,game.registry,f)
            owner=pid if f is row.source else 3-pid
            if (f.owner,f.controller,f.zone,f.zone_epoch,f.next_entity_id)!=(owner,owner,Zone.DECK,0,initial_next):
                raise ValueError('Opening copy borrowed a later, foreign or nonoriginal physical slot')
        if (event.source_id,event.player_id,event.amount,dict(event.data))!=(row.source.entity_id,pid,COUNT,{'receipt':payload(row)}):
            raise ValueError('Opening copy receipt differs from its complete accepted material')
        for origin,fact in zip(row.selected,row.deliveries):
            validate_allocation(game._state,game.registry,fact)
            if (fact.entity_id,fact.card_id,fact.kind,fact.owner,fact.controller,fact.zone,fact.zone_epoch,fact.next_entity_id)!=(
                    cursor,origin.card_id,origin.kind,pid,pid,Zone.DECK,0,cursor+1):
                raise ValueError('Opening copy lost its actual independent ordered allocation')
            created=[e for e in events if e.kind=='card_created'and e.target_id==fact.entity_id]
            inserted=[e for e in events if e.kind=='card_added_to_deck'and e.target_id==fact.entity_id]
            if len(created)!=1 or len(inserted)!=1:raise ValueError('Opening copy lost its actual unique physical producer')
            creation,insertion=created[0],inserted[0]
            if ((creation.source_id,creation.player_id,dict(creation.data))!=(row.source.entity_id,pid,{'copied_from':origin.entity_id,'copy_mode':'base'})or
                    (insertion.source_id,insertion.player_id)!=(row.source.entity_id,pid)or
                    not event.sequence<creation.sequence<insertion.sequence or
                    dict(insertion.data).get('deck_insertion')!=('bottom',None,None,0,'placement',None)):
                raise ValueError('Opening copy changed its original accepted base-copy publication')
            cursor+=1
