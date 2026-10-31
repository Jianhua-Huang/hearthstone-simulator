"""Immutable actual positive Hero Attack transitions from the original resolver."""
from dataclasses import dataclass,fields
from .model import CardType,_int

EVENT='hero_attack_gain_recorded'


@dataclass(frozen=True)
class HeroAttackGainRecord:
    id:int
    player_id:int
    hero_id:int
    active_player:int
    turn:int
    action:int
    owner_turn_id:int
    before:int
    amount:int
    after:int
    event_sequence:int

    def __post_init__(self):
        for key in('id','hero_id','amount','event_sequence'):_int(getattr(self,key),'Hero Attack gain '+key,1)
        for key in('turn','action','owner_turn_id','before','after'):_int(getattr(self,key),'Hero Attack gain '+key,0)
        if(type(self.player_id)is not int or self.player_id not in(1,2)or
                type(self.active_player)is not int or self.active_player not in(1,2)or self.after!=self.before+self.amount):
            raise ValueError('Hero Attack gain lost its actual positive transition')

    def payload(self):return tuple((f.name,getattr(self,f.name))for f in fields(self))


def record_from_dict(value):
    from .serialization import _row
    return HeroAttackGainRecord(**_row(value,HeroAttackGainRecord))


def commit(r,player_id,before,after):
    owner=r.state.owner_turn_history[-1]if r.state.owner_turn_history else None
    if owner is not None and(owner.closed or(owner.turn,owner.player_id)!=(r.state.turn,r.state.active_player)):
        raise ValueError('Hero Attack gain has no actual current owner interval')
    row=HeroAttackGainRecord(len(r.state.hero_attack_gain_history)+1,player_id,r.state.players[player_id].hero_id,
        r.state.active_player,r.state.turn,r.state.action_number,owner.id if owner else 0,
        before,after-before,after,len(r.game._events)+1)
    r.state.hero_attack_gain_history.append(row)
    r.emit(EVENT,target_id=row.hero_id,player_id=player_id,amount=row.amount,record=row.payload())
    r.emit('hero_attack_gained',target_id=row.hero_id,player_id=player_id,amount=row.amount)


def validate_state(state,registry=None):
    if type(state.hero_attack_gain_history)is not list:raise ValueError('Hero Attack gains require their complete original list')
    previous_event=previous_action=previous_turn=0
    for index,row in enumerate(state.hero_attack_gain_history,1):
        if type(row)is not HeroAttackGainRecord:raise ValueError('Hero Attack gain requires an immutable typed original fact')
        row.__post_init__()
        if(row.id!=index or row.event_sequence<=previous_event or not previous_action<=row.action<=state.action_number or
                not previous_turn<=row.turn<=state.turn):raise ValueError('Hero Attack gains changed original chronology')
        hero=state.entities.get(row.hero_id)
        if(hero is None or hero.id>=state.next_entity_id or(hero.kind,hero.owner,hero.controller)!=(CardType.HERO,row.player_id,row.player_id)or
                registry is not None and registry.card(hero.card_id).kind!=CardType.HERO):raise ValueError('Hero Attack gain changed its original physical Hero')
        if row.owner_turn_id:
            if row.owner_turn_id>len(state.owner_turn_history):raise ValueError('Hero Attack gain borrowed an unknown interval')
            owner=state.owner_turn_history[row.owner_turn_id-1]
            if((owner.turn,owner.player_id)!=(row.turn,row.active_player)or row.action<owner.start_action or
                    row.event_sequence<=owner.start_event or owner.closed_action is not None and row.action>owner.closed_action or
                    owner.closed_event is not None and row.event_sequence>owner.closed_event):raise ValueError('Hero Attack gain is outside its original interval')
        elif(row.turn!=1 or state.owner_turn_history and(row.event_sequence>state.owner_turn_history[0].start_event or
                row.action>state.owner_turn_history[0].start_action)):raise ValueError('Pre-first Hero Attack gain borrowed a later interval')
        previous_event,previous_action,previous_turn=row.event_sequence,row.action,row.turn


def gained_this_turn(state,player_id):
    from .effects import _player
    from .owner_turns import current_owner_turn
    _player(player_id);validate_state(state);interval=current_owner_turn(state)
    return sum(row.amount for row in state.hero_attack_gain_history if row.player_id==player_id and
        row.turn==state.turn and row.event_sequence>interval.start_event)


def validate_boundary(game):
    from .hero_health_history import effective_events
    validate_state(game._state,game.registry);timeline=tuple(effective_events(game._events))
    records=tuple(e for e in timeline if e.kind==EVENT);by_sequence={e.sequence:e for e in timeline};paired=set()
    if len(records)!=len(game._state.hero_attack_gain_history):raise ValueError('Hero Attack gains lost their full original event inventory')
    for row,event in zip(game._state.hero_attack_gain_history,records):
        if(len(event.data)!=1 or dict(event.data).get('record')!=row.payload()or
                (event.sequence,event.action,event.source_id,event.target_id,event.player_id,event.amount)!=
                (row.event_sequence,row.action,None,row.hero_id,row.player_id,row.amount)):raise ValueError('Hero Attack gain differs from its complete original event')
        public=by_sequence.get(event.sequence+1)
        if(public is None or public.kind!='hero_attack_gained'or public.data or
                (public.action,public.source_id,public.target_id,public.player_id,public.amount)!=
                (row.action,None,row.hero_id,row.player_id,row.amount)):raise ValueError('Hero Attack gain lost its original public notification')
        paired.add(public.sequence)
    if paired!={e.sequence for e in timeline if e.kind=='hero_attack_gained'}:raise ValueError('Hero Attack gains omitted a real original transition')


def register(mechanics):mechanics.register_payload_type(HeroAttackGainRecord)
