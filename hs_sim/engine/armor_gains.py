"""Committed armor grants, without maintaining a second armor balance."""
from dataclasses import dataclass, fields

from .effects import Effect, GainArmor, _player
from .model import CardType, TriggerSpec, Zone, _int, _name
from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation

EVENT = 'armor_gain_recorded'
ORIGINS = ('gain_armor', 'hero_card', 'replacement', 'generated_hero')


@dataclass(frozen=True)
class ArmorGainBonusProfile:
    card_id: str
    behavior_id: str
    amount: int = 2

    def __post_init__(self):
        _name(self.card_id,'extra armor source');_name(self.behavior_id,'extra armor body')
        if type(self.amount)is not int or self.amount!=2:
            raise ValueError('Only the reviewed independent two-Armor reward is declared')


def validate_profile(registry,profile):
    if type(profile)is not ArmorGainBonusProfile:raise ValueError('Typed extra armor profile required')
    profile.__post_init__();card=registry.card(profile.card_id)
    if card.kind!=CardType.MINION or card.triggers!=(TriggerSpec(EVENT,profile.behavior_id),):
        raise ValueError('Extra armor requires its original native gain listener')
    registry.behavior(profile.behavior_id)


@dataclass(frozen=True)
class ArmorGainRecord:
    id: int
    player_id: int
    hero_id: int
    active_player: int
    turn: int
    action: int
    owner_turn_id: int
    before: int
    amount: int
    after: int
    event_sequence: int
    origin: str
    bonus_parent_id: int | None = None
    bonus_source: SourceAllocationFact | None = None

    def __post_init__(self):
        _player(self.player_id); _player(self.active_player)
        for key in ('id', 'hero_id', 'event_sequence'):
            _int(getattr(self, key), 'armor grant '+key, 1)
        for key in ('turn', 'action', 'owner_turn_id', 'before', 'amount', 'after'):
            _int(getattr(self, key), 'armor grant '+key, 0)
        if type(self.origin) is not str or self.origin not in ORIGINS or self.after != self.before+self.amount:
            raise ValueError('Armor grant lost its original operation or committed delta')
        if (self.bonus_parent_id is None)!=(self.bonus_source is None):
            raise ValueError('Extra armor requires both original parent and source')
        if self.bonus_parent_id is not None:
            _int(self.bonus_parent_id,'original armor parent',1)
            if type(self.bonus_source)is not SourceAllocationFact or self.origin!='gain_armor':
                raise ValueError('Extra armor requires its original physical source and ordinary grant')
            self.bonus_source.__post_init__()

    def payload(self):
        return tuple((f.name,getattr(self,f.name).payload() if f.name=='bonus_source'and self.bonus_source is not None
            else getattr(self,f.name))for f in fields(self))


def record_from_dict(value):
    from .serialization import _row
    raw=dict(_row(value,ArmorGainRecord))
    raw['bonus_source']=allocation_from_dict(raw['bonus_source'])
    return ArmorGainRecord(**raw)


@dataclass(frozen=True)
class GainExtraArmor(Effect):
    parent_id: int
    source: SourceAllocationFact

    def __post_init__(self):
        _int(self.parent_id,'original extra armor parent',1)
        if type(self.source)is not SourceAllocationFact:raise ValueError('Extra armor requires its original actor')
        self.source.__post_init__()
        if (self.source.kind,self.source.zone)!=(CardType.MINION,Zone.BOARD):
            raise ValueError('Extra armor requires its original board minion')

    def validate_in_state(self,state):
        self.__post_init__();_bonus_parent(state,self.parent_id,self.source)


def _bonus_parent(state,parent_id,source,registry=None):
    _int(parent_id,'original extra armor parent',1)
    if parent_id>len(state.armor_gain_history):raise ValueError('Unknown original armor parent')
    row=state.armor_gain_history[parent_id-1]
    if (row.bonus_parent_id is not None or row.amount<=0 or row.player_id!=source.controller or
            source.entity_id not in state.entities or source.next_entity_id>state.next_entity_id or
            source.next_order>state.next_order):
        raise ValueError('Extra armor cannot recurse or substitute its original receiver/source')
    if registry is not None:
        validate_allocation(state,registry,source)
        profile=registry.armor_gain_bonus_profiles.get(source.card_id)
        if profile is None:raise ValueError('Undeclared original extra armor source')
        validate_profile(registry,profile)
    return row


def extra_from_context(context,registry):
    event=context.event
    if event is None or event.kind!=EVENT:raise ValueError('Extra armor requires its actual original gain window')
    raw=dict(dict(event.data)['record']);identity=raw['id']
    _int(identity,'actual armor occurrence',1)
    if identity>len(context.state.armor_gain_history):raise ValueError('Unknown actual armor occurrence')
    row=context.state.armor_gain_history[identity-1]
    if row.payload()!=dict(event.data)['record'] or (row.event_sequence,row.player_id)!=(event.sequence,event.player_id):
        raise ValueError('Extra armor lost its actual original grant')
    if row.player_id!=context.player_id or row.amount<=0 or row.bonus_parent_id is not None:return ()
    source=SourceAllocationFact.capture(context.state,context.source)
    _bonus_parent(context.state,row.id,source,registry)
    return (GainExtraArmor(row.id,source),)


def extra_armor(r,effect):
    effect.validate_in_state(r.state);_bonus_parent(r.state,effect.parent_id,effect.source,r.registry)
    if any(row.bonus_parent_id==effect.parent_id and row.bonus_source==effect.source for row in r.state.armor_gain_history):
        raise ValueError('Original extra armor reward was already delivered')
    from .resolver import armor
    return armor(r,GainArmor(effect.source.controller,r.registry.armor_gain_bonus_profiles[effect.source.card_id].amount),bonus=effect)


def commit(r, hero, before, amount, origin, *, bonus=None):
    """Original mutators call after assignment and just before their public event."""
    owner = r.state.owner_turn_history[-1] if r.state.owner_turn_history else None
    if owner is not None and (owner.closed or (owner.turn, owner.player_id) != (r.state.turn, r.state.active_player)):
        raise ValueError('Armor grant has no actual active owner interval')
    row = ArmorGainRecord(len(r.state.armor_gain_history)+1, hero.controller, hero.id,
        r.state.active_player, r.state.turn, r.state.action_number, owner.id if owner else 0,
        before, amount, hero.armor, len(r.game._events)+1, origin,
        bonus.parent_id if bonus is not None else None,bonus.source if bonus is not None else None)
    if hero.kind != CardType.HERO or r.state.players[row.player_id].hero_id != hero.id:
        raise ValueError('Armor grant must belong to the installed physical Hero')
    r.state.armor_gain_history.append(row)
    r.emit(EVENT, player_id=row.player_id, target_id=row.hero_id, amount=row.amount, record=row.payload())


def validate_state(state, registry=None):
    rows = state.armor_gain_history
    if type(rows) is not list:
        raise ValueError('Armor gain history requires its complete immutable facts')
    previous_event = previous_action = previous_turn = 0
    bonuses=set()
    for index, row in enumerate(rows, 1):
        if type(row) is not ArmorGainRecord:
            raise ValueError('Armor gain history requires ArmorGainRecord')
        row.__post_init__()
        if row.bonus_parent_id is not None:
            parent=_bonus_parent(state,row.bonus_parent_id,row.bonus_source,registry)
            key=(row.bonus_parent_id,row.bonus_source.entity_id,row.bonus_source.entered_order)
            if (key in bonuses or parent.event_sequence>=row.event_sequence or
                    parent.turn!=row.turn or parent.action>row.action or row.amount!=2):
                raise ValueError('Extra armor lost its unique original positive gain')
            bonuses.add(key)
        if (row.id != index or row.event_sequence <= previous_event or
                not previous_action <= row.action <= state.action_number or
                not previous_turn <= row.turn <= state.turn):
            raise ValueError('Armor gain history changed its original chronology')
        hero = state.entities.get(row.hero_id)
        if (hero is None or hero.id >= state.next_entity_id or
                (hero.kind, hero.owner, hero.controller) != (CardType.HERO, row.player_id, row.player_id) or
                registry is not None and registry.card(hero.card_id).kind != CardType.HERO):
            raise ValueError('Armor gain history changed its original physical Hero')
        if row.owner_turn_id:
            if row.owner_turn_id > len(state.owner_turn_history):
                raise ValueError('Armor grant borrowed an unknown owner interval')
            owner = state.owner_turn_history[row.owner_turn_id-1]
            if ((owner.turn, owner.player_id) != (row.turn, row.active_player) or
                    row.action < owner.start_action or row.event_sequence <= owner.start_event or
                    owner.closed_action is not None and row.action > owner.closed_action or
                    owner.closed_event is not None and row.event_sequence > owner.closed_event):
                raise ValueError('Armor grant is outside its original owner interval')
        elif (row.turn != 1 or state.owner_turn_history and
                (row.event_sequence > state.owner_turn_history[0].start_event or
                 row.action > state.owner_turn_history[0].start_action)):
            raise ValueError('Pre-first armor grant borrowed a later actual turn')
        previous_event, previous_action, previous_turn = row.event_sequence, row.action, row.turn


def gained_this_turn(state, player_id):
    """Pure native predicate; does not read host logs, current armor or a cache."""
    _player(player_id)
    validate_state(state)
    return any(row.player_id == player_id and row.turn == state.turn and row.amount > 0
        for row in state.armor_gain_history)


def validate_boundary(game):
    validate_state(game._state, game.registry)
    from .hero_health_history import effective_events
    timeline = tuple(effective_events(game._events))
    recorded = tuple(e for e in timeline if e.kind == EVENT)
    if len(recorded) != len(game._state.armor_gain_history):
        raise ValueError('Armor gain history lost its complete original event inventory')
    by_sequence = {e.sequence: e for e in timeline}
    paired = set()
    for row, event in zip(game._state.armor_gain_history, recorded):
        if (len(event.data) != 1 or dict(event.data).get('record') != row.payload() or
                (event.sequence, event.action, event.source_id, event.target_id, event.player_id, event.amount) !=
                (row.event_sequence, row.action, None, row.hero_id, row.player_id, row.amount)):
            raise ValueError('Armor grant differs from its complete original event')
        following = by_sequence.get(event.sequence+1)
        kind = 'armor_gained' if row.origin == 'gain_armor' else 'hero_replaced'
        if (following is None or following.kind != kind or
                (following.action, following.player_id, following.target_id) != (row.action, row.player_id, row.hero_id) or
                kind == 'armor_gained' and following.amount != row.amount):
            raise ValueError('Armor grant lost its original public operation')
        paired.add(following.sequence)
    if paired != {e.sequence for e in timeline if e.kind in ('armor_gained', 'hero_replaced')}:
        raise ValueError('Armor gain history omitted an actual gain or Hero installation')
    if game._frame is not None:
        pending=set()
        committed={(r.bonus_parent_id,r.bonus_source.entity_id,r.bonus_source.entered_order)
            for r in game._state.armor_gain_history if r.bonus_source is not None}
        for work in (*game._frame.prefix,*game._frame.continuation):
            if type(work)is not GainExtraArmor:continue
            work.validate_in_state(game._state);_bonus_parent(game._state,work.parent_id,work.source,game.registry)
            key=(work.parent_id,work.source.entity_id,work.source.entered_order)
            if key in pending or key in committed:raise ValueError('Duplicate original queued extra armor reward')
            pending.add(key)


def register(mechanics):
    mechanics.register_payload_type(ArmorGainRecord)
    mechanics.register(GainExtraArmor,extra_armor)
