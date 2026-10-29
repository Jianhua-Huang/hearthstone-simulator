"""One original played minion in a Sack; shared summons and movement own delivery."""
from dataclasses import asdict,dataclass,fields
import json
from .allocation_facts import SourceAllocationFact,allocation_from_dict,validate_allocation
from .board_presence import resolve_board_presence
from .effects import Effect,_integer,_player
from .errors import ResolutionError
from .model import BoardPresenceReference,CardType,DeathrattleMemory,NativeDeathrattleSpec,Zone
from .play_history import play_record
from .summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial

ROOT='REV_828'
SACK='REV_828t'
CAPTURED='sack_captive_stored'
RETURNED='sack_captive_returned'
SPEC=NativeDeathrattleSpec('custody_return')


@dataclass(frozen=True)
class StoredMinionCustody:
    source:SourceAllocationFact
    play_id:int
    reference:BoardPresenceReference
    before:SourceAllocationFact
    stored:SourceAllocationFact
    turn:int
    action:int

    def __post_init__(self):
        _integer(self.play_id,'original captive hand play',1)
        _integer(self.turn,'original captive turn',1);_integer(self.action,'original captive action',0)
        if type(self.reference)is not BoardPresenceReference:raise ValueError('Captive requires its original board residence')
        self.reference.__post_init__()
        for value in (self.source,self.before,self.stored):
            if type(value)is not SourceAllocationFact:raise ValueError('Captive requires complete original allocation facts')
            value.__post_init__()
        a,z=self.before,self.stored
        if (self.source.card_id!=ROOT or self.source.kind!=CardType.SPELL or self.source.zone!=Zone.GRAVEYARD or
                (a.kind,a.zone,z.kind,z.zone)!=(CardType.MINION,Zone.BOARD,CardType.MINION,Zone.SETASIDE) or
                (a.entity_id,a.card_id,a.owner,a.controller)!=(z.entity_id,z.card_id,z.owner,z.controller) or
                a.entity_id!=self.reference.entity_id or z.zone_epoch!=a.zone_epoch+1 or
                self.source.entity_id==a.entity_id):
            raise ValueError('Captive substituted its original source or silent physical storage')


def custody_from_dict(value):
    if type(value)is not dict or set(value)!={f.name for f in fields(StoredMinionCustody)}:
        raise ValueError('Malformed original captive memory')
    row=dict(value)
    for key in ('source','before','stored'):row[key]=allocation_from_dict(row[key])
    if type(row['reference'])is not dict or set(row['reference'])!={'entity_id','presence_id'}:
        raise ValueError('Malformed original captive residence')
    row['reference']=BoardPresenceReference(**row['reference'])
    return StoredMinionCustody(**row)


def validate_custody(state,registry,value,*,closed=False):
    if type(value)is not StoredMinionCustody:raise ValueError('Expected original typed captive memory')
    value.__post_init__()
    for allocation in (value.source,value.before,value.stored):validate_allocation(state,registry,allocation,closed=closed)
    if value.turn>state.turn or value.action>state.action_number or value.reference.presence_id>=state.next_order:
        raise ValueError('Captive borrowed future original chronology or residence')
    if not closed:
        play=play_record(state,value.play_id)
        if (play.kind!=CardType.MINION or not play.completed or play.countered or play.minion_entry is None or
                play.minion_entry.reference!=value.reference or play.player_id==value.source.controller or
                play.action>value.action or play.turn>value.turn):
            raise ValueError('Captive lost its original actual played-minion entry')


def validate_recipe(state,registry,request,material,*,closed=False):
    memory=material.deathrattle_memory
    if material.card_id!=SACK or memory.spec!=SPEC or memory.custody is None:
        raise ValueError('Captive summon requires its real plain Sack definition')
    link=memory.custody;validate_custody(state,registry,link,closed=closed)
    if (request.player_id!=link.source.controller or request.cause.source!=link.source or
            request.cause.player_id!=request.player_id or request.selection!='first' or len(request.materials)!=1):
        raise ValueError('Captive summon changed its exact original source or recipient')


@dataclass(frozen=True)
class KidnapPlayedMinion(Effect):
    play_id:int
    cause:SummonCause

    def __post_init__(self):
        _integer(self.play_id,'original kidnapped play',1)
        if type(self.cause)is not SummonCause:raise ValueError('Kidnap requires its actual attributed summon cause')
        self.cause.__post_init__()
        if (self.cause.source.card_id,self.cause.source.kind,self.cause.source.zone)!=(ROOT,CardType.SPELL,Zone.GRAVEYARD):
            raise ValueError('Kidnap requires its actual revealed Secret source')

    def validate_in_state(self,state,registry):
        from .summon_quantities import validate_cause
        self.__post_init__();validate_cause(state,registry,self.cause)
        play=play_record(state,self.play_id)
        if not play.completed or play.kind!=CardType.MINION or play.countered or play.minion_entry is None or play.player_id==self.cause.player_id:
            raise ValueError('Kidnap substituted its original opposite physical minion play')


def kidnap(r,effect):
    from .summon_quantities import accept,deliver,record
    effect.validate_in_state(r.state,r.registry);play=play_record(r.state,effect.play_id)
    validate_reveal(r.game,effect.play_id,effect.cause.source)
    target=resolve_board_presence(r.state,play.minion_entry.reference)
    if (target is None or not target.active or target.health<=0 or target.doomed or
            len(r.player(effect.cause.player_id).board)>=r.rules.max_board):return ()
    card=r.registry.card(SACK)
    if card.kind!=CardType.MINION or card.native_deathrattle!=SPEC:raise ResolutionError('Missing actual Sack return definition')
    before=SourceAllocationFact.capture(r.state,target)
    r.move(target,Zone.SETASIDE)
    link=StoredMinionCustody(effect.cause.source,play.id,play.minion_entry.reference,before,
        SourceAllocationFact.capture(r.state,target),r.state.turn,r.state.action_number)
    validate_custody(r.state,r.registry,link)
    r.emit(CAPTURED,source_id=link.source.entity_id,target_id=target.id,player_id=effect.cause.player_id,
        _custody=json.dumps(asdict(link),sort_keys=True,separators=(',',':')),_capture=False)
    request=SummonByCard(effect.cause.player_id,(SummonEntryMaterial(SACK,deathrattle_memory=DeathrattleMemory(SPEC,custody=link)),),effect.cause)
    first,*finish=accept(r,request)
    # Silent departure and the actual first Sack are one handler transaction.
    # Delegate the existing first delivery before an aura/death checkpoint can
    # fill the slot. All entry reactions, extra copies and Finish remain shared.
    continuation=deliver(r,first)
    actual=record(r.state,first.root_id)
    if not actual.deliveries or actual.deliveries[0].outcome!='delivered':
        raise ResolutionError('Accepted original captivity did not create its actual Sack')
    return (*continuation,*finish)


@dataclass(frozen=True)
class ReturnSackCaptive(Effect):
    source_id:int
    deathrattle_id:int

    def __post_init__(self):
        _integer(self.source_id,'original Sack source',1);_integer(self.deathrattle_id,'original Sack Deathrattle',1)

    def validate_in_state(self,state,registry):
        self.__post_init__()
        if self.deathrattle_id>len(state.deathrattle_history):raise ValueError('Unknown original Sack Deathrattle')
        row=state.deathrattle_history[self.deathrattle_id-1];memory=row.capture.ability.deathrattle_memory
        if (row.capture.carrier_id!=self.source_id or row.execution_order is None or row.completed or row.interrupted or
                memory is None or memory.spec!=SPEC or memory.custody is None):
            raise ValueError('Sack return lost its actual active Deathrattle memory')
        validate_custody(state,registry,memory.custody)
        return row,memory.custody


def return_captive(r,effect):
    from .zones import SetAsideCardReference,MoveCard,move_physical_card
    row,link=effect.validate_in_state(r.state,r.registry);fact=link.stored
    entity=r.state.entities[fact.entity_id]
    if (entity.zone,entity.zone_epoch,entity.card_id,entity.controller)!=(Zone.SETASIDE,fact.zone_epoch,fact.card_id,fact.controller):return ()
    recipient=3-row.capture.player_id
    actual=move_physical_card(r,MoveCard(SetAsideCardReference(fact.entity_id,fact.controller,fact.card_id,fact.zone_epoch),
        recipient,Zone.HAND,source_id=effect.source_id))
    if actual is None:raise ResolutionError('Accepted original captive failed shared physical hand delivery')
    r.emit(RETURNED,source_id=effect.source_id,target_id=fact.entity_id,player_id=recipient,
        _custody=json.dumps(asdict(link),sort_keys=True,separators=(',',':')),deathrattle_id=effect.deathrattle_id,
        _after=json.dumps(asdict(SourceAllocationFact.capture(r.state,actual)),sort_keys=True,separators=(',',':')),_capture=False)
    return ()


def validate_reveal(game,play_id,source):
    from .hero_health_history import effective_events
    events=effective_events(game.events)
    play=play_record(game._state,play_id)
    played=[e for e in events if e.kind=='card_played' and dict(e.data).get('play_id')==play_id
        and (e.source_id,e.player_id)==(play.source_id,play.player_id)]
    if len(played)!=1 or not any(e.kind=='secret_revealed' and e.source_id==source.entity_id
            and e.player_id==source.controller and e.sequence>played[0].sequence for e in events):
        raise ValueError('Kidnap lost its actual Secret reveal after the original played minion')


def validate_boundary(game):
    from .hero_health_history import effective_events
    captured=[];returned=[]
    for event in effective_events(game.events):
        if event.kind not in (CAPTURED,RETURNED):continue
        data=dict(event.data);link=custody_from_dict(json.loads(data['_custody']))
        validate_custody(game._state,game.registry,link)
        validate_reveal(game,link.play_id,link.source)
        if event.kind==CAPTURED:
            if (event.source_id,event.target_id,event.player_id,event.action)!=(link.source.entity_id,link.stored.entity_id,link.source.controller,link.action):
                raise ValueError('Original captivity event differs from its actual source or subject')
            if link in captured:raise ValueError('Original captivity duplicated its single physical storage')
            captured.append(link)
        else:
            if link not in captured or link in returned:raise ValueError('Captive return has no unique original physical custody')
            did=data.get('deathrattle_id')
            if type(did)is not int or not 1<=did<=len(game._state.deathrattle_history):raise ValueError('Captive return lost its actual Deathrattle')
            row=game._state.deathrattle_history[did-1];memory=row.capture.ability.deathrattle_memory
            if memory is None or memory.custody!=link or (event.source_id,event.target_id,event.player_id)!=(row.capture.carrier_id,link.stored.entity_id,3-row.capture.player_id):
                raise ValueError('Captive return borrowed another Deathrattle or recipient')
            after=allocation_from_dict(json.loads(data['_after']));validate_allocation(game._state,game.registry,after)
            if (after.entity_id,after.card_id,after.owner,after.controller,after.zone_epoch)!=(link.stored.entity_id,link.stored.card_id,link.stored.owner,event.player_id,link.stored.zone_epoch+1) or after.zone not in (Zone.HAND,Zone.GRAVEYARD):
                raise ValueError('Captive return substituted its physical hand or overflow result')
            returned.append(link)
    recipes=[]
    for root in game._state.card_summon_history:
        for material in root.request.materials:
            memory=getattr(material,'deathrattle_memory',None)
            if memory is not None and memory.custody is not None:
                validate_recipe(game._state,game.registry,root.request,material)
                recipes.append(memory.custody)
    if len(recipes)!=len(captured) or set(recipes)!=set(captured):
        raise ValueError('Original custody lost its complete unique attributed Sack recipe')
    if game._frame is not None:
        for work in (*game._frame.prefix,*game._frame.continuation):
            if type(work)is KidnapPlayedMinion:
                validate_reveal(game,work.play_id,work.cause.source)


def register(mechanics):
    mechanics.register(KidnapPlayedMinion,kidnap)
    mechanics.register(ReturnSackCaptive,return_captive)
    mechanics.register_payload_type(StoredMinionCustody)
