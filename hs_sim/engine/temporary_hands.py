"""Private ordered hand preservation and same-owner-end replacement return.

The current policy replaces the whole current hand at expiry. Exact CN cleanup,
copy material and expiry priority remain provisional; other producers are open.
"""
from .hand_capacity import hand_capacity
from dataclasses import dataclass, fields, is_dataclass, replace

from .effects import Effect, _integer, _player
from .errors import ResolutionError
from .model import GameState, Zone
from .zones import CardReference, CopyCard, copy_physical_card, source_exists
from .starting_hands import ReplaceHandWithTemporaryStartingHand

POLICY='own-end-replace-current-v1'


@dataclass(frozen=True)
class ReplaceHandWithTemporaryCopy(Effect):
    player_id: int
    source_player_id: int
    source_id: int

    def __post_init__(self):
        _player(self.player_id);_player(self.source_player_id);_integer(self.source_id,'temporary hand source',1)
        if self.player_id==self.source_player_id:raise ValueError('Temporary copy requires the other hand')


@dataclass(frozen=True)
class SavedHandCard:
    entity_id: int
    card_id: str
    zone_epoch: int
    hand_entry_id: int

    def __post_init__(self):
        for name in ('entity_id','zone_epoch','hand_entry_id'):_integer(getattr(self,name),'saved hand '+name,1)
        if type(self.card_id)is not str or not self.card_id.strip():raise ValueError('Saved hand needs a card ID')


@dataclass(frozen=True)
class TemporaryHandReplacement:
    id: int
    request: ReplaceHandWithTemporaryCopy | ReplaceHandWithTemporaryStartingHand
    source_card_id: str
    turn: int
    action: int
    originals: tuple[SavedHandCard,...]
    copied_from: tuple[CardReference,...]
    introduced: tuple[int,...]
    phase: str='active'
    removed: tuple[int,...]=()
    returned: tuple[int,...]=()

    def __post_init__(self):
        for name in ('id','turn'):_integer(getattr(self,name),'temporary hand '+name,1)
        _integer(self.action,'temporary hand action',0)
        from .starting_hands import ReplaceHandWithTemporaryStartingHand
        if type(self.request)not in(ReplaceHandWithTemporaryCopy,ReplaceHandWithTemporaryStartingHand):raise ValueError('Typed temporary hand request required')
        self.request.__post_init__()
        if type(self.source_card_id)is not str or not self.source_card_id.strip():raise ValueError('Original hand source face required')
        if self.phase not in ('active','completed','ended'):raise ValueError('Unknown temporary hand phase')
        for name,cls in (('originals',SavedHandCard),('copied_from',CardReference)):
            values=getattr(self,name)
            if type(values)is not tuple or any(type(v)is not cls for v in values):raise ValueError('Typed original hand tuple required')
            for value in values:value.__post_init__()
            if len({v.entity_id for v in values})!=len(values):raise ValueError('Duplicate original hand body')
        for name in ('introduced','removed','returned'):
            values=getattr(self,name)
            if type(values)is not tuple or len(set(values))!=len(values):raise ValueError('Unique hand identities required')
            for value in values:_integer(value,'temporary hand identity',1)
        if len(self.copied_from)!=len(self.introduced):raise ValueError('Copy source and result counts differ')
        if self.phase!='completed'and(self.removed or self.returned):raise ValueError('Unfinished hand already returned')
        if self.phase=='completed'and self.returned!=tuple(v.entity_id for v in self.originals):raise ValueError('Returned hand changed original order')


@dataclass(frozen=True)
class ReturnTemporaryHand(Effect):
    replacement_id: int
    def __post_init__(self):_integer(self.replacement_id,'temporary hand return',1)


def record(state,identity):
    _integer(identity,'temporary hand ID',1)
    if identity>len(state.temporary_hands):raise ValueError('Unknown temporary hand replacement')
    return state.temporary_hands[identity-1]


def begin_data(root):
    if type(root) is not TemporaryHandReplacement:
        from .temporary_deck_hands import begin_data as deck_begin_data
        return deck_begin_data(root)
    from .starting_hands import ReplaceHandWithTemporaryStartingHand,TEMPORARY_POLICY,STARTING_POLICY
    if type(root.request)is ReplaceHandWithTemporaryStartingHand:
        return dict(hand_id=root.id,source_card_id=root.source_card_id,turn=root.turn,policy=TEMPORARY_POLICY,starting_policy=STARTING_POLICY,
            originals=tuple((v.entity_id,v.card_id,v.zone_epoch,v.hand_entry_id)for v in root.originals),
            copied_from=tuple((v.entity_id,v.player_id,v.zone.value,v.card_id,v.zone_epoch)for v in root.copied_from),introduced=root.introduced)
    return dict(hand_id=root.id,source_card_id=root.source_card_id,source_player_id=root.request.source_player_id,turn=root.turn,policy=POLICY,
        originals=tuple((v.entity_id,v.card_id,v.zone_epoch,v.hand_entry_id)for v in root.originals),
        copied_from=tuple((v.entity_id,v.player_id,v.zone.value,v.card_id,v.zone_epoch)for v in root.copied_from),introduced=root.introduced)


def finish_data(root):
    if type(root) is not TemporaryHandReplacement:
        from .temporary_deck_hands import finish_data as deck_finish_data
        return deck_finish_data(root)
    return dict(hand_id=root.id,removed=root.removed,returned=root.returned)


def event_prefix(root):
    if type(root)is not TemporaryHandReplacement:return 'temporary_deck_hand_'
    from .starting_hands import ReplaceHandWithTemporaryStartingHand
    return 'temporary_starting_hand_'if type(root.request)is ReplaceHandWithTemporaryStartingHand else 'temporary_hand_'


def hide(r,entity):
    r.move(entity,Zone.SETASIDE)
    if r.game._information is not None:r.game._information.conceal(entity.id)


def start(r,request):
    request.__post_init__();source_exists(r,request.source_id)
    if r.state.active_player!=request.player_id:raise ResolutionError('Same-owner-end hand copy requires the active player')
    original=tuple(r.state.entities[eid]for eid in r.player(request.player_id).hand)
    copied=tuple(CardReference.capture(r.state.entities[eid])for eid in r.player(request.source_player_id).hand)
    for entity in original:r.registry.card(entity.card_id)
    for ref in copied:r.registry.card(ref.card_id)
    saved=[]
    for entity in original:
        hide(r,entity);saved.append(SavedHandCard(entity.id,entity.card_id,entity.zone_epoch,entity.hand_entry_id))
    introduced=[]
    for ref in copied:
        body=copy_physical_card(r,CopyCard(ref,request.player_id,mode='current',source_id=request.source_id))
        if body is None:raise ResolutionError('Captured temporary hand source disappeared during materialization')
        introduced.append(body.id)
    root=TemporaryHandReplacement(len(r.state.temporary_hands)+1,request,r.state.entities[request.source_id].card_id,
        r.state.turn,r.state.action_number,tuple(saved),copied,tuple(introduced))
    r.state.temporary_hands.append(root)
    r.emit('temporary_hand_replaced',source_id=request.source_id,player_id=request.player_id,**begin_data(root))


def due(state,turn):
    return tuple(root.id for root in state.temporary_hands if type(root)is TemporaryHandReplacement and root.phase=='active'
        and root.turn==turn and root.request.player_id==state.active_player)


def return_hand(r,work):
    try:root=record(r.state,work.replacement_id)
    except ValueError as error:raise ResolutionError(str(error))from error
    if type(root) is not TemporaryHandReplacement:
        from .temporary_deck_hands import return_hand as return_deck_hand
        return return_deck_hand(r,root)
    request=root.request
    if not r.ending_turn or(root.turn,request.player_id)!=(r.state.turn,r.state.active_player):
        raise ResolutionError('Temporary hand return requires its genuine ending window')
    expected=due(r.state,r.state.turn)
    if not expected or expected[-1]!=root.id:raise ResolutionError('Temporary hands must return once in reverse replacement order')
    originals=[]
    for ref in root.originals:
        entity=r.state.entities.get(ref.entity_id)
        if entity is None or(entity.controller,entity.zone,entity.card_id,entity.zone_epoch,entity.hand_entry_id)!=(
            request.player_id,Zone.SETASIDE,ref.card_id,ref.zone_epoch,ref.hand_entry_id):
            raise ResolutionError('Saved original hand changed its private residence')
        originals.append(entity)
    if len(originals)>hand_capacity(r.player(request.player_id), r.rules):raise ResolutionError('Saved original hand exceeds capacity')
    removed=tuple(r.player(request.player_id).hand)
    for eid in removed:hide(r,r.state.entities[eid])
    for entity in originals:r.move(entity,Zone.HAND,hand_entry_source_id=request.source_id)
    root=replace(root,phase='completed',removed=removed,returned=tuple(v.id for v in originals))
    r.state.temporary_hands[root.id-1]=root
    # Commit the complete group before capturing reactions to any returned card.
    r.emit(event_prefix(root)+'restored',source_id=request.source_id,player_id=request.player_id,
        hand_id=root.id,removed=root.removed,returned=root.returned)
    for entity in originals:r.emit('card_moved_to_hand',source_id=request.source_id,target_id=entity.id,player_id=request.player_id)


def ended(r):
    for root in tuple(r.state.temporary_hands):
        if root.phase=='active':r.state.temporary_hands[root.id-1]=replace(root,phase='ended')


def rows_from_dict(value):
    from .serialization import _row,_list
    rows=[]
    for raw in _list(value['temporary_hands'],'temporary hand history'):
        if type(raw) is dict and type(raw.get('request')) is dict and set(raw['request'])=={'player_id','count','source_id'}:
            from .temporary_deck_hands import row_from_dict
            rows.append(row_from_dict(raw));continue
        row=_row(raw,TemporaryHandReplacement)
        if type(row['request'])is dict and set(row['request'])=={'player_id','source_id'}:
            from .starting_hands import ReplaceHandWithTemporaryStartingHand
            row['request']=ReplaceHandWithTemporaryStartingHand(**_row(row['request'],ReplaceHandWithTemporaryStartingHand))
        else:row['request']=ReplaceHandWithTemporaryCopy(**_row(row['request'],ReplaceHandWithTemporaryCopy))
        row['originals']=tuple(SavedHandCard(**_row(v,SavedHandCard))for v in _list(row['originals'],'saved hand'))
        refs=[]
        for raw_ref in _list(row['copied_from'],'original copy hand'):
            ref=_row(raw_ref,CardReference);ref['zone']=Zone(ref['zone']);refs.append(CardReference(**ref))
        row['copied_from']=tuple(refs)
        for name in ('introduced','removed','returned'):row[name]=tuple(_list(row[name],'temporary hand '+name))
        rows.append(TemporaryHandReplacement(**row))
    value['temporary_hands']=rows


def validate_shape(state,registry):
    if type(state.temporary_hands)is not list:raise ValueError('Typed temporary hand history required')
    saved=set()
    for identity,root in enumerate(state.temporary_hands,1):
        from .temporary_deck_hands import TemporaryDeckHandReplacement,validate_shape as validate_deck_shape
        if type(root) is TemporaryDeckHandReplacement:
            if root.id!=identity:raise ValueError('Temporary deck hand changed its allocation order')
            validate_deck_shape(state,root,registry,saved);continue
        if type(root)is not TemporaryHandReplacement:raise ValueError('Typed temporary hand record required')
        root.__post_init__();req=root.request;registry.card(root.source_card_id)
        if root.id!=identity or root.turn>state.turn or root.action>state.action_number or req.source_id not in state.entities:
            raise ValueError('Temporary hand history changed its allocation or source')
        if root.phase=='active'and(state.status!='playing'or(root.turn,req.player_id)!=(state.turn,state.active_player)):
            raise ValueError('Active temporary hand outlived its ending window')
        if root.phase=='ended'and state.status=='playing':raise ValueError('Playing hand cannot claim terminal cleanup')
        for ref in root.originals:
            entity=state.entities.get(ref.entity_id);registry.card(ref.card_id)
            if entity is None or ref.zone_epoch>entity.zone_epoch or not 1<=ref.hand_entry_id<=len(state.hand_entries):
                raise ValueError('Unknown saved original hand identity')
            entry=state.hand_entries[ref.hand_entry_id-1]
            if(entry.entity_id,entry.player_id)!=(ref.entity_id,req.player_id)or entry.zone_epoch>=ref.zone_epoch:
                raise ValueError('Saved original hand lost its actual acquisition')
            if root.phase in ('active','ended'):
                if ref.entity_id in saved or(entity.controller,entity.zone,entity.card_id,entity.zone_epoch,entity.hand_entry_id)!=(
                    req.player_id,Zone.SETASIDE,ref.card_id,ref.zone_epoch,ref.hand_entry_id):raise ValueError('Saved original hand changed its private residence')
                saved.add(ref.entity_id)
        from .starting_hands import ReplaceHandWithTemporaryStartingHand,starting_hand,references
        is_starting=type(req)is ReplaceHandWithTemporaryStartingHand
        if is_starting and root.copied_from!=references(starting_hand(state,req.player_id),req.player_id):
            raise ValueError('Temporary starting hand changed its frozen final basis')
        source_player=req.player_id if is_starting else req.source_player_id
        for ref,eid in zip(root.copied_from,root.introduced):
            registry.card(ref.card_id);original=state.entities.get(ref.entity_id);body=state.entities.get(eid)
            if ref.zone!=Zone.HAND or ref.player_id!=source_player or original is None or ref.zone_epoch>original.zone_epoch:
                raise ValueError('Temporary hand changed its original copy basis')
            if body is None or body.origin_entity_id!=ref.entity_id or body.owner!=req.player_id:
                raise ValueError('Temporary hand lost its actual copied body')
        if any(eid not in state.entities for eid in root.removed):raise ValueError('Unknown removed temporary hand body')


def validate_boundary(game):
    state=game._state;validate_shape(state,game.registry)
    kinds=('temporary_hand_replaced','temporary_hand_restored','temporary_deck_hand_replaced','temporary_deck_hand_restored',
        'temporary_starting_hand_replaced','temporary_starting_hand_restored')
    if not state.temporary_hands and not any(e.kind in kinds for e in game._events):return
    # Use the existing Retry checkpoint semantics. Attempt logs survive while
    # state/history are restored; their superseded receipts are not live facts.
    effective=[];restored_after=None
    for event in reversed(game._events):
        if event.kind=='timeline_rewound':
            start=dict(event.data).get('event_start');_integer(start,'actual Retry event checkpoint',0)
            if start>=event.sequence:raise ValueError('Retry checkpoint exceeds its original window')
            restored_after=start if restored_after is None else min(restored_after,start)
        if event.kind in kinds and(restored_after is None or event.sequence<=restored_after):effective.append(event)
    effective.reverse()
    starts=[e for e in effective if e.kind in ('temporary_hand_replaced','temporary_deck_hand_replaced','temporary_starting_hand_replaced')]
    finishes=[e for e in effective if e.kind in ('temporary_hand_restored','temporary_deck_hand_restored','temporary_starting_hand_restored')]
    if len(starts)!=len(state.temporary_hands):raise ValueError('Temporary hand lacks original acceptance receipts')
    for root,event in zip(state.temporary_hands,starts):
        prefix=event_prefix(root)
        if event.kind!=prefix+'replaced':raise ValueError('Temporary hand changed its original producer')
        if(event.source_id,event.player_id,event.action,dict(event.data))!=(root.request.source_id,root.request.player_id,root.action,begin_data(root)):
            raise ValueError('Temporary hand changed its original acceptance receipt')
        matched=[e for e in finishes if dict(e.data).get('hand_id')==root.id]
        if len(matched)!=(root.phase=='completed'):raise ValueError('Temporary hand return receipts differ from its phase')
        if matched:
            event=matched[0]
            if event.kind!=prefix+'restored':raise ValueError('Temporary hand changed its return producer')
            if(event.source_id,event.player_id,dict(event.data))!=(root.request.source_id,root.request.player_id,
                finish_data(root)):raise ValueError('Temporary hand changed its original return receipt')
    if any(dict(e.data).get('hand_id')not in range(1,len(starts)+1)for e in finishes):raise ValueError('Unknown temporary hand finish')
    if game._frame is None:return
    from .resolver import ExpireTurn,BeginTurnEvents
    from .temporary_deck_hands import ExpireTemporaryDeckHands,due_start
    returns=[];expiry=[];deck_expiry=[];starts=[];seen=set()
    def visit(value):
        if type(value)is ReturnTemporaryHand:returns.append(value.replacement_id)
        if type(value)is ExpireTurn:expiry.append(value.turn)
        if type(value)is ExpireTemporaryDeckHands:deck_expiry.append(value)
        if type(value)is BeginTurnEvents:starts.append(value)
        if value is None or type(value)is GameState or id(value)in seen:return
        if is_dataclass(value):
            seen.add(id(value))
            for field in fields(value):visit(getattr(value,field.name))
        elif type(value)in(tuple,list):
            seen.add(id(value))
            for item in value:visit(item)
    # Acceptance proofs may contain earlier work copies. Only executable
    # prefix/continuation may prove that the live expiry is still scheduled.
    visit(game._frame.prefix);visit(game._frame.continuation)
    before=(len(returns),len(deck_expiry));visit(game._frame.options)
    if(len(returns),len(deck_expiry))!=before:raise ValueError('Private temporary hand return cannot be a choice branch')
    active=due(state,state.turn)
    deck_active=due_start(state)
    expected=active if game._frame.ending_turn else deck_active
    if returns and(not expected or returns!=[expected[-1]]):raise ValueError('Unaccepted temporary hand return in continuation')
    if game._frame.ending_turn and active and state.turn not in expiry:raise ValueError('Ending continuation lost temporary hand expiry')
    if deck_active and(not deck_expiry or len(starts)!=1):raise ValueError('Owner-start continuation lost temporary deck hand expiry or start publication')


def register(mechanics):
    for cls in(SavedHandCard,TemporaryHandReplacement):mechanics.register_payload_type(cls)
    mechanics.register(ReplaceHandWithTemporaryCopy,start);mechanics.register(ReturnTemporaryHand,return_hand)
