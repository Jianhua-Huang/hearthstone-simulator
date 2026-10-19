"""One original supplied spell per continuous live minion presence.

The supply record survives the card leaving hand. Looking only at hand would
recreate the fixed duplicate-generation bug when that card enters the deck.
"""
from dataclasses import dataclass,replace
from .effects import AddToHand,_integer,_behavior
from .model import CardType,SpellSchool,Zone
from .sacrifice import MinionReference,live_minion
from .allocation_facts import SourceAllocationFact,validate_allocation,allocation_from_dict


@dataclass(frozen=True)
class LiveHandSpellProfile:
    card_id:str
    spell_card_id:str
    def __post_init__(self):
        _behavior(self.card_id);_behavior(self.spell_card_id)


def validate_profile(registry,profile):
    if type(profile) is not LiveHandSpellProfile:raise ValueError('Typed live hand spell profile required')
    profile.__post_init__();source=registry.card(profile.card_id);spell=registry.card(profile.spell_card_id)
    if (source.kind!=CardType.MINION or spell.kind!=CardType.SPELL or not spell.hand_playable or
            spell.choice_only or spell.cost!=2 or spell.spell_school!=SpellSchool.HOLY):
        raise ValueError('Live hand supply requires its real minion and2manaHoly spell')


@dataclass(frozen=True)
class LiveHandSpellLease:
    id:int
    source:MinionReference
    token:SourceAllocationFact
    created_turn:int
    created_action:int
    last_play_id:int=0
    retired:bool=False

    def __post_init__(self):
        if type(self.source) is not MinionReference:raise ValueError('Live supply requires its original minion presence')
        self.source.__post_init__()
        if type(self.token) is not SourceAllocationFact:raise ValueError('Live supply requires its original physical spell allocation')
        self.token.__post_init__()
        if self.token.kind!=CardType.SPELL or self.token.zone not in (Zone.HAND,Zone.GRAVEYARD):
            raise ValueError('Live supply requires its actual hand creation or overflow')
        for key,floor in (('id',1),('created_turn',1),('created_action',0),('last_play_id',0)):
            _integer(getattr(self,key),'live supply '+key,floor)
        if type(self.retired) is not bool:raise ValueError('Typed live supply retirement required')

    @property
    def token_id(self):return self.token.entity_id


def active_sources(state,registry):
    if state.status!='playing' or not registry.live_hand_spell_profiles:return ()
    return tuple(MinionReference.capture(e) for p in state.players.values() for i in p.board
        for e in (state.entities[i],) if e.card_id in registry.live_hand_spell_profiles and
        e.kind==CardType.MINION and e.active and e.health>0 and not e.doomed and not e.silenced)


def bind_created(r,entity,source):
    if source not in active_sources(r.state,r.registry):raise ValueError('Supply creation lost its original live source')
    profile=r.registry.live_hand_spell_profiles[source.card_id]
    if (entity.card_id,entity.controller,entity.origin_entity_id)!=(profile.spell_card_id,source.player_id,source.entity_id):
        raise ValueError('Supply creation borrowed another physical spell')
    if any(not x.retired and x.source==source for x in r.state.live_hand_spells):
        raise ValueError('A continuous source cannot supply a second original card')
    r.state.live_hand_spells.append(LiveHandSpellLease(len(r.state.live_hand_spells)+1,source,SourceAllocationFact.capture(r.state,entity),
        r.state.turn,r.state.action_number))


def settle(r):
    if not r.registry.live_hand_spell_profiles or getattr(r,'_settling_live_hand_spells',False):return
    from .opening import create_hand_card,announce_hand_card
    from .spent_spells import ReturnSpentSpell,return_spell
    from .allocation_facts import SourceAllocationFact
    from .temporary_hands import hide
    r._settling_live_hand_spells=True
    try:
        sources=active_sources(r.state,r.registry)
        for index,row in enumerate(tuple(r.state.live_hand_spells)):
            if row.retired:continue
            token=r.state.entities[row.token_id];profile=r.registry.live_hand_spell_profiles[row.source.card_id]
            if row.source not in sources:
                r.state.live_hand_spells[index]=replace(row,retired=True)
                if (token.zone,token.card_id,token.controller)==(Zone.HAND,profile.spell_card_id,row.source.player_id):hide(r,token)
        current={x.source for x in r.state.live_hand_spells if not x.retired}
        created=[]
        for source in sources:
            if source in current:continue
            profile=r.registry.live_hand_spell_profiles[source.card_id]
            request=AddToHand(source.player_id,profile.spell_card_id,source.entity_id)
            entity=create_hand_card(r,request,origin_entity_id=source.entity_id,live_hand_source=source,defer_publication=True)
            created.append((request,entity))
        for index,row in enumerate(tuple(r.state.live_hand_spells)):
            if row.retired:continue
            token=r.state.entities[row.token_id];profile=r.registry.live_hand_spell_profiles[row.source.card_id]
            plays=[p for p in r.state.play_history if p.id>row.last_play_id and p.source_id==row.token_id and
                p.player_id==row.source.player_id and p.card_id==profile.spell_card_id and p.kind==CardType.SPELL and
                p.completed and not p.interrupted]
            if plays:
                played=plays[-1];r.state.live_hand_spells[index]=replace(row,last_play_id=played.id)
                if (token.zone,token.card_id,token.controller)==(Zone.GRAVEYARD,profile.spell_card_id,row.source.player_id):
                    return_spell(r,ReturnSpentSpell(SourceAllocationFact.capture(r.state,token),row.source.player_id))
        for request,entity in created:announce_hand_card(r,request,entity)
    finally:r._settling_live_hand_spells=False


def validate_shape(state,registry):
    rows=state.live_hand_spells
    if type(rows) is not list:raise ValueError('Complete ordered live supply ledger required')
    current=[];tokens=[]
    for index,row in enumerate(rows,1):
        if type(row) is not LiveHandSpellLease:raise ValueError('Typed live supply record required')
        row.__post_init__()
        if row.id!=index or row.created_turn>state.turn or row.created_action>state.action_number:
            raise ValueError('Live supply changed its original order or acceptance window')
        profile=registry.live_hand_spell_profiles.get(row.source.card_id)
        if profile is None or row.source.entity_id not in state.entities or row.token_id not in state.entities:
            raise ValueError('Live supply lost its declared source or original card')
        validate_allocation(state,registry,row.token)
        if (row.token.card_id,row.token.owner,row.token.controller)!=(profile.spell_card_id,row.source.player_id,row.source.player_id):
            raise ValueError('Live supply lost its original creation face or owner')
        if row.last_play_id:
            from .play_history import play_record
            play=play_record(state,row.last_play_id)
            if (play.source_id,play.player_id,play.card_id,play.kind)!=(row.token_id,row.source.player_id,profile.spell_card_id,CardType.SPELL) or not play.completed or play.interrupted:
                raise ValueError('Live supply return lost its actual completed original spell play')
        if not row.retired:current.append(row.source)
        tokens.append(row.token_id)
    if len(tokens)!=len(set(tokens)) or len(current)!=len(set(current)):
        raise ValueError('Live supply duplicated an original source or supplied card')
    if set(current)!=set(active_sources(state,registry)):
        raise ValueError('Live supply lost its complete current source inventory')


def rows_from_dict(value):
    from .serialization import _row,_list
    result=[]
    for item in _list(value['live_hand_spells'],'live hand spell ledger'):
        row=_row(item,LiveHandSpellLease);row['source']=MinionReference(**_row(row['source'],MinionReference))
        row['token']=allocation_from_dict(row['token'])
        result.append(LiveHandSpellLease(**row))
    value['live_hand_spells']=result


def validate_boundary(game):
    for row in game._state.live_hand_spells:
        if row.retired:continue
        profile=game.registry.live_hand_spell_profiles[row.source.card_id]
        if any(p.id>row.last_play_id and p.source_id==row.token_id and p.player_id==row.source.player_id and
                p.card_id==profile.spell_card_id and p.kind==CardType.SPELL and p.completed and not p.interrupted
                for p in game._state.play_history):
            raise ValueError('Live supply lost its completed original hand-play settlement')


def register(mechanics):mechanics.register_payload_type(LiveHandSpellLease)
