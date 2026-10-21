"""Godfrey's original overdraw lease, after native destruction, then hand refill.

Ordinary draw, destruction, zone movement and cost attachment primitives remain
authoritative. Random return and reaction priority are explicit CN-pending policy.
"""
from dataclasses import asdict, dataclass, replace
import json
from random import Random

from .allocation_facts import SourceAllocationFact, allocation_from_dict, validate_allocation
from .effects import Effect, _integer
from .hand_capacity import hand_capacity
from .model import CostSpec, Zone

SOURCE='JAIL_509'
PROGRAM='cards.godfrey.overdraw'
ACCEPTED='godfrey_overdraw_accepted'
STORED='godfrey_overdraw_stored'
RETURNED='godfrey_overdraw_returned'
DEPARTED='godfrey_overdraw_departed'


@dataclass(frozen=True)
class OverdrawnCard:
    id:int
    draw_id:int
    player_id:int
    provider_id:int
    source_id:int
    original:SourceAllocationFact
    burn_sequence:int
    phase:str='burned'
    stored_epoch:int|None=None
    delivery:SourceAllocationFact|None=None
    discount_id:int|None=None
    candidates:tuple[int,...]=()
    rng_before:tuple|None=None
    rng_after:tuple|None=None
    return_order:int|None=None

    def __post_init__(self):
        for key in ('id','draw_id','provider_id','source_id','burn_sequence'):_integer(getattr(self,key),'overdraw '+key,1)
        if self.player_id not in (1,2)or type(self.player_id)is not int:raise ValueError('Unknown overdraw beneficiary')
        if type(self.original)is not SourceAllocationFact:raise ValueError('Overdraw requires its original physical deck card')
        self.original.__post_init__()
        if self.original.zone!=Zone.DECK or self.phase not in ('burned','stored','returned','departed'):
            raise ValueError('Unknown original overdraw residence or phase')
        if self.phase in ('stored','returned'):
            _integer(self.stored_epoch,'original stored overdraw epoch',self.original.zone_epoch+2)
            if self.stored_epoch!=self.original.zone_epoch+2:raise ValueError('Overdraw skipped its original destruction/storage transitions')
        elif self.stored_epoch is not None:raise ValueError('Unstored overdraw has storage facts')
        if self.phase=='returned':
            if type(self.delivery)is not SourceAllocationFact:raise ValueError('Returned overdraw lost its actual hand allocation')
            self.delivery.__post_init__();_integer(self.discount_id,'overdraw discount attachment',1)
            _integer(self.return_order,'actual overdraw return order',1)
            if type(self.candidates)is not tuple or not self.candidates or self.id not in self.candidates or len(self.candidates)!=len(set(self.candidates)):
                raise ValueError('Return lost its complete original ordered candidates')
            for candidate in self.candidates:_integer(candidate,'original overdraw candidate',1)
            if (self.delivery.entity_id,self.delivery.card_id,self.delivery.owner,self.delivery.controller,self.delivery.zone,self.delivery.zone_epoch)!=(
                    self.original.entity_id,self.original.card_id,self.original.owner,self.player_id,Zone.HAND,self.stored_epoch+1):
                raise ValueError('Overdraw returned a replacement physical card')
            local=Random();local.setstate(self.rng_before)
            index=local.randrange(len(self.candidates))if len(self.candidates)>1 else 0
            if self.candidates[index]!=self.id or local.getstate()!=self.rng_after:raise ValueError('Return changed its original random selection')
        elif any(x is not None for x in (self.delivery,self.discount_id,self.rng_before,self.rng_after,self.return_order))or self.candidates:
            raise ValueError('Unreturned overdraw has invented delivery facts')


@dataclass(frozen=True)
class RefillOverdrawn(Effect):
    pass


def provider(state,player_id):
    return next((p for p in state.players[player_id].player_effects if p.spec_id==PROGRAM),None)


def _json(row):return json.dumps(asdict(row),sort_keys=True,separators=(',',':'))


def _update(state,row,**kw):
    current=replace(row,**kw);state.overdraw_returns[row.id-1]=current;return current


def capture(r,draw):
    active=provider(r.state,draw.player_id)
    if draw.outcome!='burned'or active is None:return
    if active.source_card_id!=SOURCE:raise ValueError('Godfrey program borrowed another original face')
    event=next((e for e in reversed(r.game._events)if e.kind=='card_burned'and dict(e.data).get('draw_id')==draw.id),None)
    from .zones import destruction_result
    result=destruction_result(event)
    if result is None or result.card.entity_id!=draw.entity_id or result.player_id!=draw.player_id:
        raise ValueError('Godfrey requires the actual native physical overdraw destruction')
    if any(x.draw_id==draw.id for x in r.state.overdraw_returns):raise ValueError('Overdraw was already captured')
    row=OverdrawnCard(len(r.state.overdraw_returns)+1,draw.id,draw.player_id,active.id,active.source_id,result.card,event.sequence)
    r.state.overdraw_returns.append(row)
    r.emit(ACCEPTED,source_id=active.source_id,target_id=draw.entity_id,player_id=draw.player_id,row=_json(row),_capture=False)


def finish_draw(r,draw):
    row=next((x for x in r.state.overdraw_returns if x.draw_id==draw.id),None)
    if row is None:return ()
    if row.phase!='burned':raise ValueError('Overdraw storage ran twice')
    entity=r.state.entities[row.original.entity_id]
    if (entity.controller,entity.zone,entity.card_id,entity.zone_epoch)!=(row.player_id,Zone.GRAVEYARD,row.original.card_id,row.original.zone_epoch+1):
        row=_update(r.state,row,phase='departed')
        r.emit(DEPARTED,source_id=row.source_id,target_id=entity.id,row=_json(row),_capture=False)
        return ()
    from .temporary_hands import hide
    hide(r,entity)
    row=_update(r.state,row,phase='stored',stored_epoch=entity.zone_epoch)
    r.emit(STORED,source_id=row.source_id,target_id=entity.id,player_id=row.player_id,row=_json(row),_capture=False)
    return ()


def available(state,rules,player_id):
    if len(state.players[player_id].hand)>=hand_capacity(state.players[player_id],rules):return ()
    return tuple(x.id for x in state.overdraw_returns if x.phase=='stored'and x.player_id==player_id)


def ready(state,rules):
    return state.status=='playing'and any(available(state,rules,p)for p in (state.active_player,3-state.active_player))


def schedule(r,queue,continuation,triggers):
    if ready(r.state,r.rules)and not any(type(w)is RefillOverdrawn for w in (*queue,*continuation,*triggers)):
        # Existing captured reactions, including a quest's own immediate reward,
        # keep their original priority. Nested work retains this single marker.
        triggers.append(RefillOverdrawn())


def refill(r,work):
    from .quest_hand_rewards import ready as quest_reward_ready
    if quest_reward_ready(r.state,r.rules):return ()
    player_id=next((p for p in (r.state.active_player,3-r.state.active_player)if available(r.state,r.rules,p)),None)
    if player_id is None:return ()
    candidates=available(r.state,r.rules,player_id);before=r.game._rng.getstate()
    selected=r.game._rng.randrange(len(candidates))if len(candidates)>1 else 0
    row=r.state.overdraw_returns[candidates[selected]-1];entity=r.state.entities[row.original.entity_id]
    if (entity.zone,entity.controller,entity.zone_epoch,entity.card_id)!=(Zone.SETASIDE,player_id,row.stored_epoch,row.original.card_id):
        raise ValueError('Overdraw lost its original hidden physical lease')
    r.move(entity,Zone.HAND,hand_entry_source_id=row.source_id)
    from .costs import attach_cost
    attachment=attach_cost(r.state,entity,CostSpec(delta=-1),row.source_id)
    row=_update(r.state,row,phase='returned',delivery=SourceAllocationFact.capture(r.state,entity),discount_id=attachment.id,
        candidates=candidates,rng_before=before,rng_after=r.game._rng.getstate(),
        return_order=1+sum(x.phase=='returned'for x in r.state.overdraw_returns))
    r.emit(RETURNED,source_id=row.source_id,target_id=entity.id,player_id=player_id,row=_json(row),_capture=False)
    r.emit('cost_modified',source_id=row.source_id,target_id=entity.id,attachment_id=attachment.id)
    r.emit('card_moved_to_hand',source_id=row.source_id,target_id=entity.id,player_id=player_id)
    from .hand_history import publish as publish_hand_entry
    publish_hand_entry(r, entity.hand_entry_id)
    return ()


def rows_from_dict(value):
    from .serialization import _row,_list,end_turn_rng_from_json
    rows=[]
    for raw in _list(value['overdraw_returns'],'original overdraw history'):
        row=_row(raw,OverdrawnCard);row['original']=allocation_from_dict(row['original'])
        row['delivery']=None if row['delivery']is None else allocation_from_dict(row['delivery'])
        row['candidates']=tuple(_list(row['candidates'],'overdraw return candidates'))
        for key in ('rng_before','rng_after'):
            row[key]=None if row[key]is None else end_turn_rng_from_json(row[key])
        rows.append(OverdrawnCard(**row))
    value['overdraw_returns']=rows


def validate_shape(state,registry):
    if type(state.overdraw_returns)is not list:raise ValueError('Overdraw history must be a complete list')
    seen=set();orders=[]
    for i,row in enumerate(state.overdraw_returns,1):
        if type(row)is not OverdrawnCard:raise ValueError('Typed original overdraw record required')
        row.__post_init__()
        if row.id!=i or row.draw_id in seen or row.draw_id>len(state.draw_history):raise ValueError('Overdraw history lost original draw identity')
        seen.add(row.draw_id);draw=state.draw_history[row.draw_id-1]
        if (draw.outcome,draw.entity_id,draw.card_id,draw.player_id)!=('burned',row.original.entity_id,row.original.card_id,row.player_id):
            raise ValueError('Overdraw borrowed another draw or generated card')
        validate_allocation(state,registry,row.original)
        if row.source_id not in state.entities or row.provider_id>=state.next_attachment_id:
            raise ValueError('Overdraw lost its original Godfrey allocation or program')
        e=state.entities[row.original.entity_id]
        if row.phase=='stored'and(e.zone,e.controller,e.card_id,e.zone_epoch)!=(Zone.SETASIDE,row.player_id,row.original.card_id,row.stored_epoch):
            raise ValueError('Stored overdraw no longer has its original hidden residence')
        if row.phase=='returned':
            validate_allocation(state,registry,row.delivery);orders.append(row.return_order)
            if row.discount_id>=state.next_attachment_id or any(j<1 or j>len(state.overdraw_returns)for j in row.candidates):
                raise ValueError('Overdraw borrowed future return candidates or discount')
            if e.zone==Zone.HAND and e.zone_epoch==row.delivery.zone_epoch:
                a=next((a for a in e.enchantments if a.id==row.discount_id),None)
                if a is not None and(a.cost!=-1 or a.source_id!=row.source_id):raise ValueError('Returned overdraw changed its original discount')
    if sorted(orders)!=list(range(1,len(orders)+1)):raise ValueError('Overdraw return execution order is incomplete')


def validate_boundary(game):
    from .hero_health_history import effective_events
    from .zones import destruction_result
    from .summon_quantities import walk_work
    validate_shape(game._state,game.registry)
    events=effective_events(game._events)
    by_sequence={e.sequence:e for e in events}
    stored_sequences={};return_sequences={}
    identities={r.id for r in game._state.overdraw_returns}
    for e in events:
        if e.kind in (ACCEPTED,STORED,RETURNED,DEPARTED)and json.loads(dict(e.data).get('row','{}')).get('id')not in identities:
            raise ValueError('Overdraw history lost a recorded original lease')
    captured={r.draw_id for r in game._state.overdraw_returns}
    for pid in (1,2):
        active=provider(game._state,pid)
        if active is None:continue
        starts=[e.sequence for e in events if e.kind=='player_effect_added'and e.player_id==pid and
                e.source_id==active.source_id and dict(e.data).get('effect_key')==PROGRAM]
        if not starts:raise ValueError('Godfrey program lost its original installation')
        owed={dict(e.data).get('draw_id')for e in events if e.kind=='card_burned'and e.player_id==pid and
              e.sequence>min(starts)and dict(e.data).get('draw_id')is not None}
        if not owed<=captured:raise ValueError('Godfrey omitted an actual overdraw from his original queue')
    for row in game._state.overdraw_returns:
        burn=by_sequence.get(row.burn_sequence)
        result=destruction_result(burn)
        if result is None or result.card!=row.original or dict(burn.data).get('draw_id')!=row.draw_id:
            raise ValueError('Overdraw lost its original native destruction event')
        expected=[(ACCEPTED,replace(row,phase='burned',stored_epoch=None,delivery=None,discount_id=None,candidates=(),rng_before=None,rng_after=None,return_order=None))]
        if row.phase in ('stored','returned'):
            expected.append((STORED,replace(row,phase='stored',delivery=None,discount_id=None,candidates=(),rng_before=None,rng_after=None,return_order=None)))
        if row.phase=='returned':expected.append((RETURNED,row))
        if row.phase=='departed':expected.append((DEPARTED,row))
        for kind,original in expected:
            matches=[e for e in events if e.kind==kind and dict(e.data).get('row')==_json(original)]
            if len(matches)!=1:raise ValueError('Overdraw lost its complete original lifecycle receipt')
            if kind==STORED:stored_sequences[row.id]=matches[0].sequence
            if kind==RETURNED:return_sequences[row.id]=matches[0].sequence
    for row in game._state.overdraw_returns:
        if row.phase=='returned':
            moment=return_sequences[row.id]
            actual=tuple(x.id for x in game._state.overdraw_returns if x.player_id==row.player_id and
                stored_sequences.get(x.id,moment)>=1 and stored_sequences.get(x.id,moment)<moment and
                return_sequences.get(x.id,moment)>=moment)
            if actual!=row.candidates:raise ValueError('Overdraw random selection omitted an original available physical card')
    frame=game._frame;queue=(*frame.prefix,*frame.continuation)if frame else()
    controls=tuple(w for w in queue if type(w)is RefillOverdrawn)
    if len(controls)>1:raise ValueError('Duplicated overdraw refill marker')
    if frame:
        if any(type(w)is RefillOverdrawn for w in walk_work(frame.options)):raise ValueError('Choice cannot inject an overdraw refill')
        old=tuple(w for w in frame.paid_hand_choice_boundary.work if type(w)is RefillOverdrawn)
        if controls!=old:raise ValueError('Overdraw changed original choice continuation')
    if ready(game._state,game.ruleset)and not controls:raise ValueError('Available overdraw lost its original refill continuation')


def register(mechanics):mechanics.register(RefillOverdrawn,refill)
