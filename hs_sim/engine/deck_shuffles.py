"""Actual semantic shuffle operations over the existing physical zone handlers.

An immutable first insertion witnesses each operation. A synchronous producer
scope groups its publications; no unfinished batch is saved or run by a second
scheduler. Unclassified direct insertions retain an unknown issuer.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .effects import Effect,_integer,_player,_source
from .model import CardType,Zone,_int

INSERT_EVENTS=frozenset(('card_added_to_deck','card_moved_to_deck','card_shuffled'))
CONDITION='own_deck_shuffle_count'
HISTORY='deck.shuffle.operations-game-v1'


@dataclass(frozen=True)
class DeckShuffleRecord:
    id:int
    actor_id:int|None
    player_id:int
    turn:int
    action:int
    event_sequence:int
    first_card:SourceAllocationFact
    source:SourceAllocationFact|None
    declared_count:int
    profile:str

    def __post_init__(self):
        for name in('id','player_id','event_sequence','declared_count'):_int(getattr(self,name),'shuffle '+name,1)
        _player(self.player_id)
        if self.actor_id is not None:_player(self.actor_id)
        for name in('turn','action'):_int(getattr(self,name),'shuffle '+name,0)
        if self.profile not in('semantic','unclassified','temporary_return'):raise ValueError('Unknown shuffle operation profile')
        if self.profile=='unclassified'and(self.actor_id is not None or self.declared_count!=1):raise ValueError('Direct insertion cannot invent an issuer or batch')
        if type(self.first_card)is not SourceAllocationFact:raise ValueError('Shuffle needs its actual first insertion')
        self.first_card.__post_init__()
        if(self.first_card.zone,self.first_card.controller)!=(Zone.DECK,self.player_id):raise ValueError('Shuffle witness is not in the recipient deck')
        if self.source is not None:
            if type(self.source)is not SourceAllocationFact:raise ValueError('Shuffle source requires original allocation')
            self.source.__post_init__()


def row_from_dict(raw):
    expected=set(DeckShuffleRecord.__dataclass_fields__)
    if type(raw)is not dict or set(raw)!=expected:raise ValueError('Invalid shuffle record fields')
    row=dict(raw);row['first_card']=allocation_from_dict(row['first_card'])
    row['source']=None if row['source']is None else allocation_from_dict(row['source'])
    result=DeckShuffleRecord(**row);result.__post_init__();return result


def validate_records(records,*,turn=None,action=None,next_entity_id=None):
    if type(records)not in(tuple,list)or any(type(r)is not DeckShuffleRecord for r in records):raise ValueError('Shuffle history needs original typed operations')
    last_turn=last_action=last_event=0
    for index,row in enumerate(records,1):
        row.__post_init__()
        if(row.id!=index or row.turn<last_turn or row.action<last_action or row.event_sequence<=last_event
                or turn is not None and row.turn>turn or action is not None and row.action>action):raise ValueError('Shuffle history changed its original chronology')
        if next_entity_id is not None and any(f is not None and f.next_entity_id>next_entity_id for f in(row.first_card,row.source)):
            raise ValueError('Shuffle record borrowed a future allocation')
        last_turn,last_action,last_event=row.turn,row.action,row.event_sequence


def validate_state(state,registry=None):
    if type(state.deck_shuffle_history)is not list:raise ValueError('Shuffle history must be a list')
    validate_records(state.deck_shuffle_history,turn=state.turn,action=state.action_number,next_entity_id=state.next_entity_id)
    for row in state.deck_shuffle_history:
        for fact in(row.first_card,row.source):
            if fact is not None and registry is not None:validate_allocation(state,registry,fact)


@contextmanager
def group(r,actor_id,player_id,count,source_id=None,*,profile='semantic'):
    if actor_id is not None:_player(actor_id)
    _player(player_id);_integer(count,'declared shuffle entries',0);_source(source_id)
    if profile not in('semantic','temporary_return'):raise ValueError('Unknown semantic shuffle scope')
    if source_id is not None and source_id not in r.state.entities:raise ValueError('Shuffle issuer does not exist')
    stack=getattr(r,'_deck_shuffle_scopes',None)
    if stack is None:stack=[];r._deck_shuffle_scopes=stack
    scope=dict(actor_id=actor_id,player_id=player_id,count=count,source=None if source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[source_id]),profile=profile,record_id=None)
    stack.append(scope)
    try:yield
    finally:
        if stack.pop()is not scope:raise ValueError('Shuffle producer scope changed its original LIFO')


def publication(r,kind,target_id,player_id,source_id,mode):
    """Commit before ordinary insertion listeners capture their original state."""
    if kind not in INSERT_EVENTS:raise ValueError('Shuffle publication has another event kind')
    entity=r.state.entities.get(target_id)
    if entity is None or(entity.zone,entity.controller)!=(Zone.DECK,player_id):raise ValueError('Insertion publication lost its physical deck entry')
    if mode not in('random','top','bottom','index','reorder'):raise ValueError('Unknown deck insertion placement')
    if mode!='random':return(mode,None,None,0,'placement',None)
    stack=getattr(r,'_deck_shuffle_scopes',())
    scope=stack[-1]if stack else None
    if scope is not None and scope['player_id']!=player_id:raise ValueError('Shuffle batch inserted into another deck')
    if scope is not None and scope['record_id']is not None:
        old=r.state.deck_shuffle_history[scope['record_id']-1]
        return('random',old.id,old.actor_id,old.declared_count,old.profile,None if old.source is None else old.source.entity_id)
    source=(scope['source']if scope else None if source_id is None else SourceAllocationFact.capture(r.state,r.state.entities[source_id]))
    row=DeckShuffleRecord(len(r.state.deck_shuffle_history)+1,None if scope is None else scope['actor_id'],player_id,r.state.turn,r.state.action_number,
        len(r.game._events)+1,SourceAllocationFact.capture(r.state,entity),source,1 if scope is None else scope['count'],'unclassified'if scope is None else scope['profile'])
    row.__post_init__();r.state.deck_shuffle_history.append(row)
    if scope is not None:scope['record_id']=row.id
    return('random',row.id,row.actor_id,row.declared_count,row.profile,None if row.source is None else row.source.entity_id)


def validate_boundary(game):
    from .hero_health_history import effective_events
    state=game._state;validate_state(state,game.registry);members={r.id:[]for r in state.deck_shuffle_history}
    # Rewind restores State facts, but keeps the attempted diagnostic suffix.
    # Only the committed timeline can witness the restored operation inventory.
    for event in effective_events(game._events):
        marker=dict(event.data).get('deck_insertion')
        if event.kind not in INSERT_EVENTS:
            if marker is not None:raise ValueError('Non-insertion invented a shuffle marker')
            continue
        if type(marker)is not tuple or len(marker)!=6 or marker[0]not in('random','top','bottom','index','reorder'):raise ValueError('Deck insertion lost its original placement policy')
        mode,rid,actor,count,profile,source_id=marker
        if mode!='random':
            if marker!=(mode,None,None,0,'placement',None):raise ValueError('A positional placement cannot claim a shuffle')
            continue
        if type(rid)is not int or rid not in members:raise ValueError('Insertion names an unknown shuffle operation')
        row=state.deck_shuffle_history[rid-1]
        if(actor,count,profile,source_id)!=(row.actor_id,row.declared_count,row.profile,None if row.source is None else row.source.entity_id):raise ValueError('Shuffle member rewrote its original issuer or batch')
        if event.player_id!=row.player_id or event.sequence<row.event_sequence or event.action!=row.action:raise ValueError('Shuffle member changed its original recipient/window')
        members[rid].append(event)
    for row in state.deck_shuffle_history:
        events=members[row.id]
        if not events or len(events)>row.declared_count:raise ValueError('Shuffle lost its actual witness or exceeded its declared batch')
        first=events[0]
        if(first.sequence,first.target_id,first.player_id)!=(row.event_sequence,row.first_card.entity_id,row.player_id):raise ValueError('Shuffle first insertion differs from its original publication')


@dataclass(frozen=True)
class ShuffleDeckCards(Effect):
    player_id:int
    actor_id:int
    entries:tuple[Effect,...]
    source_id:int|None=None
    def __post_init__(self):
        from .effects import ShuffleIntoDeck
        from .zones import AddToDeck,MoveCard,CopyCard
        _player(self.player_id);_player(self.actor_id);_source(self.source_id)
        if type(self.entries)is not tuple:raise ValueError('Shuffle entries must be immutable')
        for entry in self.entries:
            if type(entry)not in(AddToDeck,MoveCard,CopyCard,ShuffleIntoDeck):raise ValueError('Shuffle supports only original physical deck insertion primitives')
            entry.__post_init__()
            owner=entry.player_id
            if type(entry)is ShuffleIntoDeck:
                if owner is None:raise ValueError('Grouped physical shuffle requires an explicit recipient')
            elif type(entry)in(MoveCard,CopyCard)and(entry.destination!=Zone.DECK or entry.position!='random'):
                raise ValueError('Shuffle group requires random deck insertions')
            elif type(entry)is AddToDeck and entry.position!='random':raise ValueError('Shuffle group cannot hide a positional insertion')
            if owner!=self.player_id:raise ValueError('Shuffle group changed its declared recipient')


def execute(r,effect):
    effect.__post_init__()
    if len(effect.entries)>r.rules.max_resolution_steps:raise ValueError('Shuffle group exceeds resolution budget')
    with group(r,effect.actor_id,effect.player_id,len(effect.entries),effect.source_id):
        for entry in effect.entries:
            r.charge();result=r.game.mechanics.handler(entry)(r,entry)
            # These existing handlers mutate synchronously. A future asynchronous
            # primitive must not silently escape the accepted producer scope.
            if isinstance(result,(tuple,list,Effect))or r._choice_request is not None:raise ValueError('Shuffle primitive returned asynchronous work')
    return()


def shuffled(ctx,entries,*,player_id=None):
    entries=tuple(entries)
    return(ShuffleDeckCards(ctx.player_id if player_id is None else player_id,ctx.player_id,entries,ctx.source_id),)if entries else()


def capture_cost(state,player_id):
    from .model import DeckShuffleCostMatch
    from .registry import UnsupportedDefinitionError
    validate_state(state)
    if any(r.player_id==player_id and r.actor_id is None for r in state.deck_shuffle_history):
        raise UnsupportedDefinitionError('Shuffle price requires the original issuer of every operation into this deck')
    selected=tuple(r.id for r in state.deck_shuffle_history if r.actor_id==r.player_id==player_id)
    return DeckShuffleCostMatch(player_id,state.turn,state.action_number,state.next_entity_id,tuple(state.deck_shuffle_history),selected,len(selected),bool(selected))


def validate_cost_match(value):
    _player(value.player_id)
    for name in('turn','action','quantity'):_int(getattr(value,name),'shuffle cost '+name,0)
    _int(value.next_entity_id,'shuffle cost allocation',1)
    if type(value.records)is not tuple or type(value.selected_ids)is not tuple or type(value.matched)is not bool:raise ValueError('Shuffle price needs its complete immutable prefix')
    validate_records(value.records,turn=value.turn,action=value.action,next_entity_id=value.next_entity_id)
    if any(r.player_id==value.player_id and r.actor_id is None for r in value.records):raise ValueError('Shuffle price cannot omit an unknown issuer')
    expected=tuple(r.id for r in value.records if r.actor_id==r.player_id==value.player_id)
    if value.selected_ids!=expected or value.quantity!=len(expected)or value.matched!=bool(expected):raise ValueError('Shuffle price changed its original selected operation count')


def validate_cost_prefix(value,state,registry):
    value.__post_init__();validate_state(state,registry)
    if(value.turn>state.turn or value.action>state.action_number or value.next_entity_id>state.next_entity_id
            or tuple(state.deck_shuffle_history[:len(value.records)])!=value.records):raise ValueError('Shuffle price changed or shortened its original complete history prefix')


def intrinsic_amount(amount,rule,condition):
    from .costs import apply_cost
    quantity=condition.quantity if rule.condition==CONDITION else 1
    return apply_cost(amount,rule.delta*quantity,rule.set_to,rule.minimum)


def register(mechanics):
    mechanics.register_payload_type(DeckShuffleRecord)
    mechanics.register(ShuffleDeckCards,execute)
