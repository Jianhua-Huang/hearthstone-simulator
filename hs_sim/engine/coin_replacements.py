"""Permanent, latest-choice Coin replacement through ordinary stored transforms."""
from dataclasses import asdict,dataclass
import json

from .model import CardType,PlayerEffectSpec,Zone
from .allocation_facts import SourceAllocationFact,allocation_from_dict

ACCEPTED='coin_replacement_accepted'
CHANGED='coin_replacement_applied'
RETIRED='coin_replacement_retired'
ENTRY_EVENTS=frozenset(('card_created','card_added_to_hand','card_added_to_deck','card_drawn',
    'card_moved_to_hand','card_moved_to_deck','stored_card_transformed'))


@dataclass(frozen=True)
class CoinReplacementChoice:
    program_id:str
    card_id:str


@dataclass(frozen=True)
class CoinReplacementProfile:
    battlecry_card_id:str
    coin_card_ids:tuple[str,...]
    choices:tuple[CoinReplacementChoice,...]


def validate_profile(registry,p):
    if (type(p)is not CoinReplacementProfile or type(p.coin_card_ids)is not tuple or
            len(p.coin_card_ids)!=68 or len(set(p.coin_card_ids))!=68 or tuple(sorted(p.coin_card_ids))!=p.coin_card_ids or
            type(p.choices)is not tuple or len(p.choices)!=3 or any(type(c)is not CoinReplacementChoice for c in p.choices)or
            len({c.program_id for c in p.choices})!=3 or len({c.card_id for c in p.choices})!=3):
        raise ValueError('Coin replacement requires the complete reviewed Coin family and three actual counterfeits')
    card=registry.card(p.battlecry_card_id)
    if card.kind!=CardType.MINION or card.battlecry is None:raise ValueError('Coin replacement requires its original Battlecry')
    for c in p.choices:
        face=registry.card(c.card_id)
        if (c.card_id not in p.coin_card_ids or face.kind!=CardType.SPELL or face.cost!=0 or not face.manual_playable or
                registry.player_effect(c.program_id)!=PlayerEffectSpec(c.program_id,p.battlecry_card_id)):
            raise ValueError('Coin replacement requires an ordinary original zero-cost Coin and permanent program')


def pack(v):return json.dumps(v,sort_keys=True,separators=(',',':'))


def is_program(registry,spec_id):return spec_id in registry.coin_replacement_programs


def active_program(state,registry,player_id):
    rows=[e for e in state.players[player_id].player_effects if is_program(registry,e.spec_id)]
    if len(rows)>1:raise ValueError('Coin replacement has more than one active selected program')
    return rows[0]if rows else None


def change(r,entity,instance):
    p,c=r.registry.coin_replacement_programs[instance.spec_id]
    if entity.card_id not in p.coin_card_ids or entity.card_id==c.card_id:return None
    old=SourceAllocationFact.capture(r.state,entity)
    if entity.zone==Zone.GRAVEYARD:
        # Overflow is still a newborn materialization. Keep its allocation
        # epoch so the common created-overflow destruction proof stays valid.
        if entity.zone_epoch!=0 or entity.id!=r.state.next_entity_id-1:
            raise ValueError('Coin overflow replacement requires its actual newborn allocation')
        from .lifecycle import reset_to_definition
        reset_to_definition(r.state,entity,r.registry.card(c.card_id),r.registry,components=())
        entity.face_replaced=True
    else:
        from .cross_zone import reset_stored_entity
        reset_stored_entity(r,entity,r.registry.card(c.card_id))
    return old


def announce(r,entity,old,instance,trigger_event):
    from .cross_zone import announce_stored_transform
    p,c=r.registry.coin_replacement_programs[instance.spec_id]
    r.emit(CHANGED,source_id=instance.source_id,target_id=entity.id,player_id=entity.controller,
        instance_id=instance.id,program_id=instance.spec_id,original=pack(asdict(old)),
        card_id=c.card_id,trigger_event=trigger_event,_capture=False)
    announce_stored_transform(r,entity,old.card_id,source_id=instance.source_id)


def install(r,player_id,instance):
    binding=r.registry.coin_replacement_programs.get(instance.spec_id)
    if binding is None:return
    p,c=binding
    from .battlecries import active_battlecry
    origin=active_battlecry(r.state,instance.source_id,player_id)
    if origin is None or not origin.payload_started or origin.payload.card_id!=p.battlecry_card_id:
        raise ValueError('Coin upgrade requires its actual original accepted Battlecry')
    from .player_effects import RemovePlayerEffect,remove
    previous=[e for e in r.player(player_id).player_effects if e.id!=instance.id and is_program(r.registry,e.spec_id)]
    # Common removal performs all ordinary retirement and publications. Its
    # captured reactions run after this complete stat-free installation step.
    for old in previous:remove(r,RemovePlayerEffect(player_id,old.id))
    entities=[r.state.entities[i]for zone in(Zone.HAND,Zone.DECK)for i in tuple(getattr(r.player(player_id),zone.value))
        if r.state.entities[i].card_id in p.coin_card_ids]
    inventory=[asdict(SourceAllocationFact.capture(r.state,e))for e in entities]
    changed=[(e,old)for e in entities if(old:=change(r,e,instance))is not None]
    r.emit(ACCEPTED,source_id=instance.source_id,player_id=player_id,instance_json=pack(asdict(instance)),
        battlecry_id=origin.id,inventory=pack(inventory),previous_instances=tuple(e.id for e in previous),_capture=False)
    for entity,old in changed:announce(r,entity,old,instance,None)


def note_remove(r,player_id,instance):
    if is_program(r.registry,instance.spec_id):r.emit(RETIRED,source_id=instance.source_id,player_id=player_id,
        instance_id=instance.id,program_id=instance.spec_id,_capture=False)


def synchronize(r,event):
    if event.kind not in ENTRY_EVENTS or not r.registry.coin_replacement_programs:return
    entity=r.state.entities.get(event.target_id)
    if entity is None or entity.kind!=CardType.SPELL or entity.zone not in(Zone.HAND,Zone.DECK)and not(
            event.kind=='card_created'and entity.zone==Zone.GRAVEYARD):return
    instance=active_program(r.state,r.registry,entity.controller)
    if instance is None:return
    old=change(r,entity,instance)
    if old is not None:announce(r,entity,old,instance,event.sequence)


def ref(raw):
    return allocation_from_dict(raw)


def validate_boundary(game):
    if not game.registry.coin_replacement_programs:return
    from .hero_health_history import effective_events
    from .battlecries import battlecry_record
    accepted={};retired=set();changed=[];timeline=effective_events(game._events)
    for event in timeline:
        data=dict(event.data)
        if event.kind==ACCEPTED:
            if set(data)!={'instance_json','battlecry_id','inventory','previous_instances'}:
                raise ValueError('Coin acceptance lost its exact complete original material')
            material=json.loads(data['instance_json']);iid=material['id']
            if type(iid)is not int or not 0<iid<game._state.next_attachment_id or iid in accepted or not is_program(game.registry,material['spec_id']):raise ValueError('Coin program acceptance duplicated or unknown')
            p,c=game.registry.coin_replacement_programs[material['spec_id']]
            origin=battlecry_record(game._state,data['battlecry_id'])
            if (not origin.payload_started or origin.payload.card_id!=p.battlecry_card_id or
                    (event.source_id,event.player_id)!=(origin.source_id,origin.player_id)or
                    material['source_id']!=event.source_id or material['remaining_turns']is not None):
                raise ValueError('Coin program lost its genuine Battlecry or permanent lifetime')
            inventory=json.loads(data['inventory']);refs=[ref(x)for x in inventory]
            if len({x.entity_id for x in refs})!=len(refs)or any(x.controller!=event.player_id or
                    x.zone not in(Zone.HAND,Zone.DECK)or x.card_id not in p.coin_card_ids for x in refs):
                raise ValueError('Coin program lost its complete distinct original stored inventory')
            if any(i not in retired for i in data['previous_instances']):raise ValueError('Previous Coin selection did not retire normally')
            accepted[iid]=(event,material,refs)
        elif event.kind==RETIRED:
            iid=data['instance_id']
            # Replacements retire before the next acceptance, so the old
            # instance must already have its own earlier full origin.
            if (set(data)!={'instance_id','program_id'}or iid not in accepted or iid in retired or data['program_id']!=accepted[iid][1]['spec_id']or
                    (event.source_id,event.player_id)!=(accepted[iid][0].source_id,accepted[iid][0].player_id)):
                raise ValueError('Coin retirement borrowed or duplicated a program')
            retired.add(iid)
        elif event.kind==CHANGED:
            iid=data['instance_id']
            if set(data)!={'instance_id','program_id','original','card_id','trigger_event'}or iid not in accepted or iid in retired:raise ValueError('Coin transform borrowed an inactive program')
            origin,material,_=accepted[iid];p,c=game.registry.coin_replacement_programs[material['spec_id']]
            old=ref(json.loads(data['original']))
            if (data['program_id']!=material['spec_id']or data['card_id']!=c.card_id or old.card_id not in p.coin_card_ids or
                    old.card_id==c.card_id or old.controller!=event.player_id or old.entity_id!=event.target_id or
                    event.source_id!=material['source_id']or event.player_id!=origin.player_id or
                    event.target_id not in game._state.entities or old.zone_epoch>game._state.entities[event.target_id].zone_epoch or
                    old.zone_epoch==game._state.entities[event.target_id].zone_epoch and not(
                        old.zone==Zone.GRAVEYARD and old.zone_epoch==0)):
                raise ValueError('Coin transform lost its original physical recipient or selected face')
            trigger=data['trigger_event']
            if old.zone not in(Zone.HAND,Zone.DECK)and not(old.zone==Zone.GRAVEYARD and trigger is not None):
                raise ValueError('Coin replacement borrowed a nonstored physical card')
            if trigger is not None and not any(type(trigger)is int and e.sequence==trigger and
                    origin.sequence<e.sequence<event.sequence and e.kind in ENTRY_EVENTS and e.target_id==event.target_id and
                    (old.zone!=Zone.GRAVEYARD or e.kind=='card_created')for e in timeline):
                raise ValueError('Coin entry replacement lost its actual acquisition or transformation')
            changed.append((iid,old,trigger))
    for iid,(event,material,inventory)in accepted.items():
        _,c=game.registry.coin_replacement_programs[material['spec_id']]
        expected=[asdict(x)for x in inventory if x.card_id!=c.card_id]
        actual=[asdict(x)for owner,x,trigger in changed if owner==iid and trigger is None]
        if actual!=expected:raise ValueError('Coin installation lost its complete original replacement batch')
    for player in game._state.players.values():
        instance=active_program(game._state,game.registry,player.id)
        expected=[(iid,value)for iid,value in accepted.items()if iid not in retired and value[0].player_id==player.id]
        if len(expected)>1 or(bool(expected)!=(instance is not None))or instance is not None and(
                instance.id!=expected[0][0]or json.loads(pack(asdict(instance)))!=expected[0][1][1]):
            raise ValueError('Coin program was cropped, replaced or borrowed during restoration')
        if instance is not None:
            p,c=game.registry.coin_replacement_programs[instance.spec_id]
            for i in(*player.hand,*player.deck):
                if game._state.entities[i].card_id in p.coin_card_ids and game._state.entities[i].card_id!=c.card_id:
                    raise ValueError('Current stored Coin differs from its active permanent selection')
