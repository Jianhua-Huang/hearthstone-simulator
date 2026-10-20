"""Frozen physical hand cohorts, executed through ordinary stored spell casts."""
from dataclasses import asdict,dataclass
import json

from .effects import Effect,_integer
from .model import CardClass,CardType,Zone
from .zones import CardReference,reference_entity

PAID='adjoining_spell_paid_origin'
AUTO='adjoining_spell_automatic_origin'
ROOT='adjoining_spell_group_accepted'
STEP='adjoining_spell_group_member'
END='adjoining_spell_group_finished'


@dataclass(frozen=True)
class AdjoiningSpellProfile:
    spell_card_ids:tuple[str,...]


def validate_profile(registry,profile):
    if (type(profile)is not AdjoiningSpellProfile or type(profile.spell_card_ids)is not tuple or
            len(profile.spell_card_ids)!=6 or len(set(profile.spell_card_ids))!=6):
        raise ValueError('Adjoining essence declaration requires six distinct original spells')
    for cid in profile.spell_card_ids:
        card=registry.card(cid)
        if (card.kind!=CardType.SPELL or card.cost!=6 or card.on_play is None or card.choice_only or
                card.metadata is None or card.metadata.classes!=(CardClass.NEUTRAL,)):
            raise ValueError('Adjoining essence requires its actual six-cost neutral physical spell')


def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'))


def ref_from_dict(value):
    row=dict(value);row['zone']=Zone(row['zone']);return CardReference(**row)


def cohort(profile,source_id,hand):
    positions=[i for i,row in enumerate(hand)if row['entity_id']==source_id]
    if len(positions)!=1:raise ValueError('Adjoining source is absent or repeated in its original hand')
    index=positions[0];left=right=index
    while left>0 and hand[left-1]['card_id']in profile.spell_card_ids:left-=1
    while right+1<len(hand)and hand[right+1]['card_id']in profile.spell_card_ids:right+=1
    return [row for row in hand[left:right+1]if row['entity_id']!=source_id]


def capture(state,registry,source,from_zone,*,player_id=None):
    profile=registry.adjoining_spell_profiles.get(source.card_id)
    if profile is None:return None
    hand=[asdict(CardReference.capture(state.entities[i]))for i in state.players[source.controller].hand]if from_zone==Zone.HAND else []
    value=dict(source_id=source.id,card_id=source.card_id,player_id=source.controller if player_id is None else player_id,
        hand_owner_id=source.controller,
        from_zone=None if from_zone is None else from_zone.value,turn=state.turn,action=state.action_number,
        next_entity_id=state.next_entity_id,hand=hand,selected=cohort(profile,source.id,hand)if hand else [])
    validate_material(state,registry,value);return value


def validate_material(state,registry,value):
    if set(value)!={'source_id','card_id','player_id','hand_owner_id','from_zone','turn','action','next_entity_id','hand','selected'}:
        raise ValueError('Adjoining group lost its full original material')
    for name,floor in(('source_id',1),('turn',1),('action',0),('next_entity_id',1)):_integer(value[name],name,floor)
    if (type(value['player_id'])is not int or value['player_id']not in(1,2)or type(value['hand_owner_id'])is not int or value['hand_owner_id']not in(1,2)or value['source_id']not in state.entities or
            value['next_entity_id']>state.next_entity_id or value['source_id']>=value['next_entity_id']):
        raise ValueError('Adjoining material borrowed a future or foreign physical allocation')
    profile=registry.adjoining_spell_profiles.get(value['card_id'])
    if profile is None:raise ValueError('Adjoining material borrowed an undeclared source')
    if type(value['hand'])is not list or type(value['selected'])is not list:
        raise ValueError('Adjoining material requires its complete ordered physical hand')
    seen=set()
    for raw in value['hand']:
        ref=ref_from_dict(raw);ref.__post_init__()
        if (ref.entity_id in seen or ref.entity_id>=value['next_entity_id']or ref.entity_id not in state.entities or
                ref.player_id!=value['hand_owner_id']or ref.zone!=Zone.HAND):
            raise ValueError('Adjoining material changed its unique original hand ownership')
        seen.add(ref.entity_id)
    if value['from_zone']==Zone.HAND.value:
        if value['selected']!=cohort(profile,value['source_id'],value['hand']):
            raise ValueError('Adjoining material lost its full original connected cohort')
        source=next(x for x in value['hand']if x['entity_id']==value['source_id'])
        if source['card_id']!=value['card_id']:raise ValueError('Adjoining source changed its accepted face')
    elif value['hand']or value['selected']or value['from_zone']not in(None,Zone.DECK.value):
        raise ValueError('Only an actual hand cast can capture hand neighbors')


def note_paid(r,play,state):
    source=state.entities[play.source_id];material=capture(state,r.registry,source,Zone.HAND)
    if material is not None:r.emit(PAID,source_id=source.id,player_id=play.player_id,play_id=play.id,material_json=pack(material),_capture=False)


def events(game,kind):
    from .hero_health_history import effective_events
    return tuple(e for e in effective_events(game._events)if e.kind==kind)


def one(game,kind,key,identity):
    found=tuple(e for e in events(game,kind)if dict(e.data).get(key)==identity)
    if len(found)!=1:raise ValueError('Adjoining group lost its unique '+kind)
    return found[0]


def note_automatic(r,record,material,parent):
    if material is not None:r.emit(AUTO,source_id=record.source_id,player_id=record.player_id,
        cast_id=record.id,material_json=pack(material),_capture=False)
    if parent is not None:
        root,index=parent
        r.emit(STEP,source_id=record.source_id,player_id=record.player_id,root_cast_id=root,index=index,
            child_cast_id=record.id,result='cast',_capture=False)


def child_ids(game):return {dict(e.data)['child_cast_id']for e in events(game,STEP)if dict(e.data).get('result')=='cast'}


def accept(r,record):
    if record.card_id not in r.registry.adjoining_spell_profiles or record.id in child_ids(r.game):return
    event=one(r.game,PAID,'play_id',record.play_id)if record.play_id is not None else one(r.game,AUTO,'cast_id',record.id)
    raw=dict(event.data)['material_json']
    r.emit(ROOT,source_id=record.source_id,player_id=record.player_id,cast_id=record.id,material_json=raw,_capture=False)


def payload_tail(r,record):
    return ()if record.card_id not in r.registry.adjoining_spell_profiles or record.id in child_ids(r.game)else(CastAdjoiningSpells(record.id),)


@dataclass(frozen=True)
class CastAdjoiningSpells(Effect):
    root_cast_id:int
    index:int=0

    def __post_init__(self):
        _integer(self.root_cast_id,'adjoining root cast',1);_integer(self.index,'adjoining member cursor',0)


def progress(r,effect):
    from .spell_casts import cast_record,automatic,CastStoredSpell
    event=one(r.game,ROOT,'cast_id',effect.root_cast_id);material=json.loads(dict(event.data)['material_json'])
    validate_material(r.state,r.registry,material);root=cast_record(r.state,effect.root_cast_id)
    steps=tuple(e for e in events(r.game,STEP)if dict(e.data)['root_cast_id']==root.id)
    if effect.index!=len(steps)or events_for_root(r.game,END,root.id):raise ValueError('Adjoining group changed its original progress')
    if effect.index==len(material['selected']):
        r.emit(END,source_id=root.source_id,player_id=root.player_id,root_cast_id=root.id,_capture=False);return ()
    ref=ref_from_dict(material['selected'][effect.index]);entity=reference_entity(r,ref)
    tail=CastAdjoiningSpells(root.id,effect.index+1)
    if entity is None:
        r.emit(STEP,source_id=ref.entity_id,player_id=root.player_id,root_cast_id=root.id,index=effect.index,
            child_cast_id=None,result='stale',_capture=False);return(tail,)
    work=automatic(r,CastStoredSpell(ref,root.player_id,root.source_id),entity,Zone.HAND,
        adjoining_parent=(root.id,effect.index))
    return(*work,tail)


def events_for_root(game,kind,root_id):return tuple(e for e in events(game,kind)if dict(e.data).get('root_cast_id')==root_id)


def validate_game(game):
    if not game.registry.adjoining_spell_profiles:return
    state=game._state;children=child_ids(game);paid={};automatic={};roots={}
    for kind,key,destination in((PAID,'play_id',paid),(AUTO,'cast_id',automatic),(ROOT,'cast_id',roots)):
        for event in events(game,kind):
            data=dict(event.data)
            if set(data)!={key,'material_json'}or type(data[key])is not int or data[key]in destination:
                raise ValueError('Adjoining origin or root was duplicated/rewritten')
            material=json.loads(data['material_json']);validate_material(state,game.registry,material)
            if (event.source_id,event.player_id)!=(material['source_id'],material['player_id']):
                raise ValueError('Adjoining origin borrowed another source or player')
            destination[data[key]]=(event,material)
    expected_paid={p.id for p in state.play_history if p.card_id in game.registry.adjoining_spell_profiles}
    if set(paid)!=expected_paid:raise ValueError('Adjoining physical payment lost its complete original hand')
    for pid,(event,material)in paid.items():
        play=state.play_history[pid-1]
        if (material['hand_owner_id']!=play.player_id or (material['source_id'],material['card_id'],material['player_id'],material['action'],material['turn'])!=
                (play.source_id,play.card_id,play.player_id,play.action,play.turn)or len(material['hand'])!=play.hand_size or
                material['hand'][play.hand_index]['entity_id']!=play.source_id):raise ValueError('Adjoining hand differs from its actual paid root')
    expected_auto={c.id for c in state.cast_history if c.card_id in game.registry.adjoining_spell_profiles and c.play_id is None and c.id not in children}
    if set(automatic)!=expected_auto:raise ValueError('Adjoining automatic origin was cropped or borrowed')
    expected_roots={c.id for c in state.cast_history if c.card_id in game.registry.adjoining_spell_profiles and c.payload_started and c.id not in children}
    if set(roots)!=expected_roots:raise ValueError('Adjoining payload lost its complete group acceptance')
    queue=()if game._frame is None else(*game._frame.prefix,*game._frame.continuation)
    queued=[x for x in queue if type(x)is CastAdjoiningSpells]
    for cid,(event,material)in automatic.items():
        cast=state.cast_history[cid-1]
        if (cast.source_id,cast.card_id,cast.player_id,cast.action,cast.from_zone)!=(material['source_id'],material['card_id'],material['player_id'],material['action'],
                None if material['from_zone']is None else Zone(material['from_zone'])):raise ValueError('Adjoining automatic source differs from its original window')
    for cid,(event,material)in roots.items():
        cast=state.cast_history[cid-1];origin=paid[cast.play_id]if cast.play_id is not None else automatic[cid]
        if (cast.source_id,cast.player_id)!=(event.source_id,event.player_id)or material!=origin[1]:
            raise ValueError('Adjoining accepted group lost its genuine original inventory')
        steps=events_for_root(game,STEP,cid);ends=events_for_root(game,END,cid)
        if len(steps)>len(material['selected'])or len(ends)>1:raise ValueError('Adjoining group exceeded its accepted inventory')
        for index,step in enumerate(steps):
            d=dict(step.data);ref=ref_from_dict(material['selected'][index])
            if set(d)!={'root_cast_id','index','child_cast_id','result'}or type(d['index'])is not int or d['index']!=index or (step.source_id,step.player_id)!=(ref.entity_id,cast.player_id):
                raise ValueError('Adjoining group lost its full ordered physical members')
            if d['result']=='cast':
                _integer(d['child_cast_id'],'adjoining child',1)
                child=state.cast_history[d['child_cast_id']-1]
                if (child.source_id,child.card_id,child.player_id,child.caster_id,child.from_zone,child.play_id,child.action)!=(
                        ref.entity_id,ref.card_id,cast.player_id,cast.source_id,Zone.HAND,None,step.action):
                    raise ValueError('Adjoining member borrowed another actual physical cast')
            elif d['result']!='stale'or d['child_cast_id']is not None:raise ValueError('Adjoining member has no actual cast or stale disposition')
        pending=[x for x in queued if x.root_cast_id==cid]
        if ends:
            end=ends[0]
            if len(steps)!=len(material['selected'])or pending or (end.source_id,end.player_id)!=(cast.source_id,cast.player_id):
                raise ValueError('Adjoining group finished before its full accepted inventory')
        elif state.status=='playing':
            if cast.completed or cast.interrupted or pending!=[CastAdjoiningSpells(cid,len(steps))]:
                raise ValueError('Suspended adjoining group lost its unique next obligation')
        elif not cast.interrupted or not any(e.kind=='game_ended'and e.sequence>event.sequence for e in game._events):
            raise ValueError('Adjoining interruption lost its actual terminal event')
    if any(x.root_cast_id not in roots for x in queued)or any(dict(e.data)['root_cast_id']not in roots for kind in(STEP,END)for e in events(game,kind)):
        raise ValueError('Adjoining work or member borrowed an unknown original group')
