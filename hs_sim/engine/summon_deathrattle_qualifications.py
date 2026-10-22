"""Append-only own-entry Battlecry qualifications; original summons stay frozen."""
from dataclasses import asdict, dataclass
import json
from .model import CardType, Event, Zone, _int

KEY = '_summon_deathrattle_qualification'

@dataclass(frozen=True)
class SummonDeathrattleQualification:
    summon_id: int
    battlecry_id: int
    ability_id: int
    event_sequence: int
    action: int

    def __post_init__(self):
        for name in ('summon_id','battlecry_id','ability_id','event_sequence'):
            _int(getattr(self,name),'entry qualification '+name,1)
        _int(self.action,'entry qualification action',0)

def from_dict(value):
    from .serialization import _row
    return SummonDeathrattleQualification(**_row(value,SummonDeathrattleQualification))

def validate_operand(qualifications,records,action):
    if type(qualifications)is not tuple:raise ValueError('Entry qualifications require a complete immutable prefix')
    seen=set();last_event=last_action=0
    for q in qualifications:
        if type(q)is not SummonDeathrattleQualification:raise ValueError('Entry qualification requires a typed original grant')
        q.__post_init__()
        if not 1<=q.summon_id<=len(records):raise ValueError('Entry qualification borrowed an unknown summon')
        row=records[q.summon_id-1]
        if (q.summon_id in seen or row.deathrattle_ids or q.event_sequence<=max(last_event,row.event_sequence) or
                not max(last_action,row.action)<=q.action<=action):
            raise ValueError('Entry qualification duplicated or rewrote an original occurrence')
        seen.add(q.summon_id);last_event=q.event_sequence;last_action=q.action

def _root_entry(state,bc,hand_entries):
    if bc.play_id is not None:
        if not 1<=bc.play_id<=len(state.play_history):return None
        play=state.play_history[bc.play_id-1]
        if play.kind!=CardType.MINION or play.minion_result!='summoned' or play.source_id!=bc.source_id:return None
        return hand_entries.get(play.id)
    if bc.physical_child_id is not None:
        children=state.whole_card_replay_ledger.children
        if not 1<=bc.physical_child_id<=len(children):return None
        child=children[bc.physical_child_id-1];progress=child.physical
        if child.kind!=CardType.MINION or progress is None or progress.source is None:return None
        source=progress.source
        return next((row for row in state.successful_summon_history if
            (row.entity_id,row.minion.zone_epoch,row.minion.entered_order)==
            (source.entity_id,source.zone_epoch,source.entered_order)),None)
    return None

def _context(state):
    return dict(rows={r.event_sequence:r for r in state.successful_summon_history},
        pending={},hand_entries={},latest={},active={},qualified=set())

def _advance(state,ctx,event):
    data=dict(event.data)
    if event.kind=='minion_play_accepted':ctx['pending'][event.source_id]=data.get('play_id')
    elif event.kind=='minion_summoned':
        row=ctx['rows'].get(event.sequence)
        if row is not None:
            ctx['latest'][row.entity_id]=row
            play_id=ctx['pending'].pop(row.entity_id,None)
            if play_id is not None:ctx['hand_entries'][play_id]=row
    elif event.kind=='battlecry_started':
        identity=data.get('battlecry_id')
        if type(identity)is int:ctx['active'][identity]=event.source_id
    elif event.kind=='battlecry_finished':ctx['active'].pop(data.get('battlecry_id'),None)

def _expected(state,ctx,event):
    data=dict(event.data)
    if event.kind!='ability_granted' or data.get('ability_kind')!='deathrattle':return None
    row=ctx['latest'].get(event.target_id)
    if row is None or row.deathrattle_ids or row.id in ctx['qualified']:return None
    ability=data.get('ability_id')
    if type(ability)is not int or ability<1:raise ValueError('Deathrattle grant lost its actual attachment')
    for identity,source in sorted(ctx['active'].items()):
        if source!=row.entity_id or not 1<=identity<=len(state.battlecry_history):continue
        bc=state.battlecry_history[identity-1]
        if bc.failure is not None or not bc.payload_started:continue
        original=_root_entry(state,bc,ctx['hand_entries'])
        if original is not None and original.id==row.id:
            return SummonDeathrattleQualification(row.id,bc.id,ability,event.sequence,event.action)
    return None

def _effective(events):
    from .hero_health_history import effective_events
    return effective_events(events)

def publication(r,kind,target_id,data):
    if KEY in data:raise ValueError('Entry qualification belongs to the actual grant publisher')
    if kind!='ability_granted' or data.get('ability_kind')!='deathrattle':return {}
    entity=r.state.entities.get(target_id)
    if entity is None or entity.kind!=CardType.MINION or entity.zone!=Zone.BOARD:return {}
    if not any(b.source_id==target_id and not b.completed and not b.interrupted and b.payload_started
        and (b.play_id is not None or b.physical_child_id is not None)for b in r.state.battlecry_history):return {}
    ctx=_context(r.state)
    for event in _effective(r.game._events):
        _advance(r.state,ctx,event)
        prior=from_event(event)
        if prior is not None:ctx['qualified'].add(prior.summon_id)
    event=Event(sequence=len(r.game._events)+1,action=r.state.action_number,kind=kind,
        target_id=target_id,data=tuple(sorted(data.items())))
    q=_expected(r.state,ctx,event)
    if q is None:return {}
    ability=next((a for a in entity.abilities if a.id==q.ability_id),None)
    if ability is None or ability.kind!='deathrattle' or ability.consumed:
        raise ValueError('Entry qualification requires the actual attached Deathrattle')
    return {KEY:json.dumps(asdict(q),sort_keys=True,separators=(',',':'))}

def from_event(event):
    data=dict(event.data)
    if KEY not in data:return None
    if event.kind!='ability_granted' or data.get('ability_kind')!='deathrattle' or type(data[KEY])is not str:
        raise ValueError('Entry qualification requires its native grant event')
    q=from_dict(json.loads(data[KEY]))
    if(q.event_sequence,q.action,q.ability_id)!=(event.sequence,event.action,data.get('ability_id')):
        raise ValueError('Entry qualification changed its actual grant envelope')
    return q

def commit(r,event):
    q=from_event(event)
    if q is not None:
        r.state.summon_deathrattle_qualifications.append(q)
        validate_state(r.state)

def validate_state(state):
    values=state.summon_deathrattle_qualifications
    if type(values)is not list:raise ValueError('Entry qualifications require original ordered history')
    validate_operand(tuple(values),state.successful_summon_history,state.action_number)
    for q in values:
        if q.ability_id>=state.next_attachment_id or not 1<=q.battlecry_id<=len(state.battlecry_history):
            raise ValueError('Entry qualification borrowed a future grant or Battlecry')
        bc=state.battlecry_history[q.battlecry_id-1];row=state.successful_summon_history[q.summon_id-1]
        if(bc.source_id!=row.entity_id or bc.action>q.action or bc.failure is not None or
                not bc.payload_started or bc.play_id is None and bc.physical_child_id is None):
            raise ValueError('Entry qualification lost its original own-entry Battlecry')

def validate_boundary(game,timeline=None):
    state=game._state;ctx=_context(state);expected=[]
    for event in (_effective(game._events) if timeline is None else timeline):
        _advance(state,ctx,event)
        q=_expected(state,ctx,event);actual=from_event(event)
        if q!=actual:raise ValueError('Own-entry Deathrattle grant lost or changed its qualification')
        if q is not None:expected.append(q);ctx['qualified'].add(q.summon_id)
    if state.summon_deathrattle_qualifications!=expected:
        raise ValueError('Entry qualification history lost its complete event inventory')

def register(mechanics):
    mechanics.register_payload_type(SummonDeathrattleQualification)
