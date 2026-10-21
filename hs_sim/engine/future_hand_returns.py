"""Original hand minions disappear until the second genuine future start.

This finite native request implements Runi; startup ordering is CN-pending.
"""
from dataclasses import dataclass,fields,is_dataclass,replace
from .effects import Buff,Effect,_integer,_player
from .errors import ResolutionError
from .hand_capacity import hand_capacity
from .model import CardType,GameState,Zone
from .temporary_hands import SavedHandCard,hide
from .temporary_deck_hands import start_window


@dataclass(frozen=True)
class SendHandMinionsFuture(Effect):
    player_id:int
    source_id:int

    def __post_init__(self):
        _player(self.player_id);_integer(self.source_id,'future hand source',1)


@dataclass(frozen=True)
class FutureHandReturn:
    id:int
    request:SendHandMinionsFuture
    source_card_id:str
    turn:int
    action:int
    originals:tuple[SavedHandCard,...]
    phase:str='active'
    returned:tuple[int,...]=()
    burned:tuple[int,...]=()
    restored:tuple[SavedHandCard,...]=()

    @property
    def due_turn(self):return self.turn+2

    def __post_init__(self):
        for key in ('id','turn'):_integer(getattr(self,key),'future hand '+key,1)
        _integer(self.action,'future hand action',0)
        if type(self.request)is not SendHandMinionsFuture:raise ValueError('Typed future hand request required')
        self.request.__post_init__()
        if type(self.source_card_id)is not str or not self.source_card_id:raise ValueError('Original future source face required')
        if self.phase not in ('active','completed','ended'):raise ValueError('Unknown future hand phase')
        for key in ('originals','restored'):
            rows=getattr(self,key)
            if type(rows)is not tuple or any(type(r)is not SavedHandCard for r in rows):raise ValueError('Original future hand tuple required')
            for row in rows:row.__post_init__()
            if len({r.entity_id for r in rows})!=len(rows):raise ValueError('Duplicate future hand identity')
        for key in ('returned','burned'):
            rows=getattr(self,key)
            if type(rows)is not tuple or len(set(rows))!=len(rows):raise ValueError('Unique future delivery identities required')
            for eid in rows:_integer(eid,'future delivery identity',1)
        original=tuple(r.entity_id for r in self.originals)
        if self.phase!='completed' and(self.returned or self.burned or self.restored):raise ValueError('Unfinished future hand has delivery results')
        if self.phase=='completed' and(set(self.returned)&set(self.burned) or set(self.returned)|set(self.burned)!=set(original)
                or tuple(i for i in original if i in self.returned)!=self.returned
                or tuple(i for i in original if i in self.burned)!=self.burned
                or tuple(r.entity_id for r in self.restored)!=self.returned):raise ValueError('Future return changed its complete original group')


@dataclass(frozen=True)
class ReturnFutureHands(Effect):pass


def saved(entity):return SavedHandCard(entity.id,entity.card_id,entity.zone_epoch,entity.hand_entry_id)
def material(rows):return tuple((r.entity_id,r.card_id,r.zone_epoch,r.hand_entry_id)for r in rows)
def begin_data(root):return dict(future_id=root.id,turn=root.turn,due_turn=root.due_turn,source_card_id=root.source_card_id,originals=material(root.originals))
def finish_data(root):return dict(future_id=root.id,returned=root.returned,burned=root.burned,restored=material(root.restored))


def send(r,request):
    request.__post_init__()
    source=r.state.entities.get(request.source_id)
    if source is None or source.kind!=CardType.MINION:raise ResolutionError('Future hand requires its original minion source')
    originals=[r.state.entities[i]for i in tuple(r.player(request.player_id).hand)if r.state.entities[i].kind==CardType.MINION]
    for entity in originals:r.registry.card(entity.card_id)
    for entity in originals:hide(r,entity)
    root=FutureHandReturn(len(r.state.future_hands)+1,request,source.card_id,r.state.turn,r.state.action_number,tuple(saved(e)for e in originals))
    r.state.future_hands.append(root)
    r.emit('future_hand_saved',source_id=request.source_id,player_id=request.player_id,**begin_data(root))


def due(state):
    return tuple(root.id for root in state.future_hands if root.phase=='active'and root.due_turn==state.turn)if start_window(state)else()


def restore(r,work):
    pending=due(r.state)
    if r.ending_turn or not pending:raise ResolutionError('Future hand return requires its original unpublished future start')
    root=r.state.future_hands[pending[0]-1];player=r.player(root.request.player_id)
    originals=[]
    for ref in root.originals:
        entity=r.state.entities.get(ref.entity_id)
        if entity is None or(entity.controller,entity.zone,entity.card_id,entity.zone_epoch,entity.hand_entry_id)!=(player.id,Zone.SETASIDE,ref.card_id,ref.zone_epoch,ref.hand_entry_id):
            raise ResolutionError('Future hand lost its original physical residence')
        originals.append(entity)
    from .resolver import _buff_to
    from .allocation_facts import SourceAllocationFact
    returned=[];burned=[];restored=[];burn_material={}
    for entity in originals:
        _buff_to(r,Buff(entity.id,5,5,root.request.source_id),entity,notify=False)
        if len(player.hand)<hand_capacity(player,r.rules):
            r.move(entity,Zone.HAND,hand_entry_source_id=root.request.source_id);returned.append(entity.id);restored.append(saved(entity))
        else:
            burn_material[entity.id]=SourceAllocationFact.capture(r.state,entity)
            r.move(entity,Zone.GRAVEYARD);burned.append(entity.id)
    root=replace(root,phase='completed',returned=tuple(returned),burned=tuple(burned),restored=tuple(restored))
    r.state.future_hands[root.id-1]=root
    # Commit the whole original group before any observer can react.
    r.emit('future_hand_returned',source_id=root.request.source_id,player_id=player.id,**finish_data(root))
    for eid in returned:
        r.emit('stored_card_buffed',source_id=root.request.source_id,target_id=eid,player_id=player.id,attack_delta=5,health_delta=5)
        r.emit('card_moved_to_hand',source_id=root.request.source_id,target_id=eid,player_id=player.id)
        from .hand_history import publish as publish_hand_entry
        publish_hand_entry(r, r.state.entities[eid].hand_entry_id)
    for eid in burned:
        from .zones import emit_burn
        emit_burn(r,r.state.entities[eid],profile='setaside_overflow',original=burn_material[eid],source_id=root.request.source_id,reason='future_hand_return_full')
    return (ReturnFutureHands(),)if due(r.state)else()


def ended(r):
    for root in tuple(r.state.future_hands):
        if root.phase=='active':r.state.future_hands[root.id-1]=replace(root,phase='ended')


def rows_from_dict(value):
    from .serialization import _row,_list
    rows=[]
    for raw in _list(value['future_hands'],'future hand history'):
        row=_row(raw,FutureHandReturn)
        row['request']=SendHandMinionsFuture(**_row(row['request'],SendHandMinionsFuture))
        for key in ('originals','restored'):row[key]=tuple(SavedHandCard(**_row(r,SavedHandCard))for r in _list(row[key],'future hand '+key))
        for key in ('returned','burned'):row[key]=tuple(_list(row[key],'future hand '+key))
        rows.append(FutureHandReturn(**row))
    value['future_hands']=rows


def validate_shape(state,registry):
    if type(state.future_hands)is not list:raise ValueError('Future hand history requires a list')
    held=set();last_turn=last_action=0
    for identity,root in enumerate(state.future_hands,1):
        if type(root)is not FutureHandReturn:raise ValueError('Typed future hand record required')
        root.__post_init__();req=root.request
        if(root.id!=identity or not last_turn<=root.turn<=state.turn or not last_action<=root.action<=state.action_number or
                req.source_id not in state.entities or registry.card(root.source_card_id).kind!=CardType.MINION):raise ValueError('Future hand source or chronology changed')
        last_turn,last_action=root.turn,root.action
        if root.phase=='active'and(state.status!='playing'or root.due_turn<state.turn):raise ValueError('Future hand outlived its original return')
        if root.phase=='ended'and state.status=='playing':raise ValueError('Playing future hand cannot claim terminal cleanup')
        if root.phase=='completed'and root.due_turn>state.turn:raise ValueError('Future hand returned before its original start')
        for ref in root.originals:
            entity=state.entities.get(ref.entity_id)
            if(entity is None or ref.zone_epoch>entity.zone_epoch or registry.card(ref.card_id).kind!=CardType.MINION
                    or not 1<=ref.hand_entry_id<=len(state.hand_entries)):raise ValueError('Unknown original future card')
            entry=state.hand_entries[ref.hand_entry_id-1]
            if(entry.entity_id,entry.player_id)!=(ref.entity_id,req.player_id)or entry.zone_epoch>=ref.zone_epoch:raise ValueError('Future card lost its original hand acquisition')
            if root.phase in ('active','ended'):
                if ref.entity_id in held or(entity.controller,entity.zone,entity.card_id,entity.zone_epoch,entity.hand_entry_id)!=(req.player_id,Zone.SETASIDE,ref.card_id,ref.zone_epoch,ref.hand_entry_id):raise ValueError('Future card changed its private residence')
                held.add(ref.entity_id)
        for ref in root.restored:
            original=next(r for r in root.originals if r.entity_id==ref.entity_id)
            if ref.card_id!=original.card_id or ref.zone_epoch!=original.zone_epoch+1 or not 1<=ref.hand_entry_id<=len(state.hand_entries):raise ValueError('Future return changed original delivery')
            entry=state.hand_entries[ref.hand_entry_id-1]
            if(entry.entity_id,entry.player_id,entry.card_id,entry.zone_epoch,entry.from_zone,entry.turn)!=(ref.entity_id,req.player_id,ref.card_id,ref.zone_epoch,Zone.SETASIDE,root.due_turn):raise ValueError('Future return lost actual hand delivery')


def validate_boundary(game):
    state=game._state;validate_shape(state,game.registry)
    from .hero_health_history import effective_events
    events=[e for e in effective_events(game._events)if e.kind in('future_hand_saved','future_hand_returned')]
    starts=[e for e in events if e.kind=='future_hand_saved'];finishes=[e for e in events if e.kind=='future_hand_returned']
    if len(starts)!=len(state.future_hands):raise ValueError('Future hand lost its complete original event inventory')
    for root,event in zip(state.future_hands,starts):
        if(event.source_id,event.player_id,event.action,dict(event.data))!=(root.request.source_id,root.request.player_id,root.action,begin_data(root)):raise ValueError('Future hand changed its original save receipt')
        matched=[e for e in finishes if dict(e.data).get('future_id')==root.id]
        if len(matched)!=(root.phase=='completed'):raise ValueError('Future hand return receipt differs from its phase')
        if matched and(matched[0].source_id,matched[0].player_id,dict(matched[0].data))!=(root.request.source_id,root.request.player_id,finish_data(root)):raise ValueError('Future hand changed its actual return receipt')
    if any(dict(e.data).get('future_id')not in range(1,len(starts)+1)for e in finishes):raise ValueError('Unknown future return receipt')
    returns=[];starts_work=[];seen=set()
    from .resolver import BeginTurnEvents
    def visit(value):
        if type(value)is ReturnFutureHands:returns.append(value)
        if type(value)is BeginTurnEvents:starts_work.append(value)
        if value is None or type(value)is GameState or id(value)in seen:return
        if is_dataclass(value):
            seen.add(id(value))
            for field in fields(value):visit(getattr(value,field.name))
        elif type(value)in(tuple,list):
            seen.add(id(value))
            for item in value:visit(item)
    if game._frame is not None:
        visit(game._frame.prefix);visit(game._frame.continuation)
        count=len(returns);visit(game._frame.options)
        if len(returns)!=count:raise ValueError('Future return cannot be an unaccepted choice branch')
    pending=due(state)
    if returns and(not pending or len(returns)!=1):raise ValueError('Unaccepted future return work')
    if pending and(len(returns)!=1 or len(starts_work)!=1):raise ValueError('Future startup lost original return work or publication')


def register(mechanics):
    mechanics.register_payload_type(FutureHandReturn)
    mechanics.register(SendHandMinionsFuture,send);mechanics.register(ReturnFutureHands,restore)
