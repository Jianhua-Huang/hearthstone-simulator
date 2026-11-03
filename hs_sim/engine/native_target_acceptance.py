"""Actual native manual target replacement with original submission preserved.

Full original windows live only in the unique diagnostic Finish while pending.
Closed private receipts retain complete selection material and the original
proposal; they provide internal consistency, not unsigned origin authentication.
"""
from .runtime_copy import deepcopy
from dataclasses import dataclass, replace
import json
from types import SimpleNamespace

from .effects import Effect
from .model import (ActionWindow, BattlecryRecord, ComboRecord, HeroPowerRecord,
    CardDefinition, GameState)
from .native_random_targets import (NativeTargetPartition, NativeTargetSelection,
    RandomTargetCarrier, manual_partition, sample)
from .rules import Ruleset

ACCEPTED='native_manual_target_selected'
FINISHED='native_manual_target_finished'
FAMILIES={'battlecry':BattlecryRecord,'combo':ComboRecord,'hero_power':HeroPowerRecord,'manual_card':ActionWindow}
HISTORIES={'battlecry':'battlecry_history','combo':'combo_history','hero_power':'hero_power_history'}


def original_target(record):
    value=getattr(record,'native_target',None)
    return record.target_id if value is None else value.partition.submitted_target_id


def validate_model_selection(value,origin,source_id,player_id,target_id):
    if value is None:return
    if type(value) is not NativeTargetSelection:raise ValueError('Native target replacement requires its typed original selection')
    value.__post_init__();p=value.partition
    if not p.applied or (p.origin,p.source.entity_id,p.player_id,value.target_id)!=(origin,source_id,player_id,target_id):
        raise ValueError('Native target replacement borrowed a different activation')


def selection_from_dict(value):
    if value is None:return None
    from .serialization import _row,_list,end_turn_rng_from_json
    from .allocation_facts import allocation_from_dict
    from .model import TargetMode
    row=_row(value,NativeTargetSelection);part=_row(row['partition'],NativeTargetPartition)
    part['source']=allocation_from_dict(part['source'])
    part['mode']=None if part['mode'] is None else TargetMode(part['mode'])
    sources=[]
    for source in _list(part['carriers'],'native target carriers'):
        item=_row(source,RandomTargetCarrier);item['source']=allocation_from_dict(item['source'])
        item['ability_ids']=tuple(_list(item['ability_ids'],'native marker identities'));sources.append(RandomTargetCarrier(**item))
    part['carriers']=tuple(sources);part['candidates']=tuple(allocation_from_dict(x)for x in _list(part['candidates'],'native target candidates'))
    row['partition']=NativeTargetPartition(**part)
    for key in('rng_before','rng_after'):row[key]=end_turn_rng_from_json(row[key])
    return NativeTargetSelection(**row)


def effective_definition(state,registry,origin,proposal):
    from .choose_one import effective
    if origin=='manual_card':
        from .play_history import play_record,play_definition
        from .spell_casts import CONDITIONS,effective_definition as spell_definition
        play=play_record(state,proposal.play_id)
        return spell_definition(play_definition(state,registry,state.entities[proposal.source_id],play),
            {key:getattr(play,key)for key in CONDITIONS})
    if origin=='hero_power':return effective(registry.card(proposal.card_id),proposal.branch_id)
    from .play_history import play_record
    from .body_targets import body_target_contract
    play=play_record(state,proposal.play_id);contract=body_target_contract(registry,proposal.payload.card_id,origin)
    condition=contract.target_condition
    enabled=(True if condition is None else play.mana_crystals>=contract.manathirst_threshold
        if condition=='manathirst' else getattr(play,condition))
    return replace(registry.card(proposal.payload.card_id),requires_target=False,
        targeting=contract.targeting if enabled else None,target_rule=contract.target_rule,
        target_condition=None,manathirst=None)


@dataclass(frozen=True)
class NativeTargetProof:
    before_state: GameState
    rules: Ruleset
    effective_definition: CardDefinition
    selection: NativeTargetSelection
    origin: str
    proposal: object
    information_json: str | None

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                type(self.effective_definition) is not CardDefinition or type(self.selection) is not NativeTargetSelection or
                self.origin not in FAMILIES or type(self.proposal) is not FAMILIES[self.origin]):
            raise ValueError('Native target proof lost its complete original activation window')
        self.selection.__post_init__();self.proposal.__post_init__();self.rules.__post_init__()
        if not self.selection.partition.applied or self.selection.partition.origin!=self.origin:
            raise ValueError('Inactive native policy cannot create an acceptance proof')
        if self.information_json is not None and type(json.loads(self.information_json)) is not dict:
            raise ValueError('Native player predicate lost its original knowledge')


def validate_proof(proof,registry):
    proof.__post_init__();state=deepcopy(proof.before_state);origin=proof.origin;proposal=proof.proposal
    if state.status!='playing' or getattr(proposal,'native_target',None) is not None:
        raise ValueError('Native target proof lost its original pre-replacement proposal')
    if origin=='manual_card':
        from .interrupts import find_window
        if proposal.kind!='spell' or not proposal.target_phase or proposal.countered or find_window(state,proposal.id)!=proposal:
            raise ValueError('Native spell target proof lost its actual target phase')
    elif proposal.id!=len(getattr(state,HISTORIES[origin]))+1:
        raise ValueError('Native target proof changed its original allocation position')
    if origin=='battlecry' and proposal.origin!='hand' or origin=='combo' and proposal.physical_child_id is not None or origin=='hero_power' and proposal.origin!='manual':
        raise ValueError('Native manual targeting cannot replace an automatic producer')
    expected=effective_definition(state,registry,origin,proposal)
    if expected!=proof.effective_definition:raise ValueError('Native target proof changed its actual effective definition')
    player_predicate=registry.target_visibility(expected.target_rule)=='player'
    if player_predicate!=(proof.information_json is not None):raise ValueError('Native target proof changed predicate visibility')
    game=SimpleNamespace(_state=state,registry=registry,ruleset=proof.rules)
    if player_predicate:
        from .information import Information
        game._information=Information.from_dict(json.loads(proof.information_json),game)
    probe=SimpleNamespace(state=state,registry=registry,game=game)
    actual=manual_partition(probe,state.entities[proposal.source_id],expected,proposal.target_id,
        player_id=proposal.player_id,origin=origin)
    if actual!=proof.selection.partition:raise ValueError('Native target proof cropped or changed its complete original domain')


def encode(r,value):
    from .continuations import FrameCodec
    return json.dumps(FrameCodec(r.game.mechanics,r.registry).encode(value),ensure_ascii=False,sort_keys=True,separators=(',',':'))


def accept(r,origin,proposal):
    """One real handler accepts its native target; never overwrite submission."""
    if not r.registry.random_target_cards or proposal.target_id is None:return None
    definition=effective_definition(r.state,r.registry,origin,proposal)
    information=None
    if r.registry.target_visibility(definition.target_rule)=='player':
        r.game._information.sync(r.game)
        information=json.dumps(r.game._information.to_dict(),ensure_ascii=False,sort_keys=True,separators=(',',':'))
    partition=manual_partition(r,r.state.entities[proposal.source_id],definition,proposal.target_id,
        player_id=proposal.player_id,origin=origin)
    if not partition.applied:return None
    before=deepcopy(r.state);selection=sample(r.game._rng,partition)
    proof=NativeTargetProof(before,r.rules,definition,selection,origin,proposal,information)
    r.emit(ACCEPTED,source_id=proposal.source_id,target_id=selection.target_id,player_id=proposal.player_id,
        origin=origin,activation_id=proposal.id,play_id=getattr(proposal,'play_id',None),
        proposal=encode(r,proposal),selection=encode(r,selection),_capture=False)
    return proof


def spell_failure(game,play_id):
    """A targeted native empty domain fizzles every original physical CAST."""
    from .play_history import play_record
    actual = play_record(game._state, play_id).spell_target_receipt
    if actual is not None:
        if not actual.closed: raise ValueError('A physical CAST overtook its actual group target phase')
        return 'no_target' if actual.primary_target_id is None else None
    if not game.registry.random_target_cards:return None
    from .hero_health_history import effective_events
    from .continuations import FrameCodec
    matches=[e for e in effective_events(game._events)if e.kind==ACCEPTED and
        dict(e.data)['origin']=='manual_card'and dict(e.data)['play_id']==play_id]
    if len(matches)>1:raise ValueError('Native spell has multiple original target acceptances')
    if not matches:return None
    return FrameCodec(game.mechanics,game.registry).decode(json.loads(dict(matches[0].data)['selection'])).failure


@dataclass(frozen=True)
class FinishNativeTarget(Effect):
    proof: NativeTargetProof
    def __post_init__(self):
        if type(self.proof) is not NativeTargetProof:raise ValueError('Native target Finish requires its original full proof')
        self.proof.__post_init__()


def normalized(record):
    """Only progress and an explicitly proved replacement differ from proposal."""
    value=getattr(record,'native_target',None)
    if value is None:return record
    updates=dict(native_target=None,target_id=value.partition.submitted_target_id,completed=False,interrupted=False)
    if value.failure is not None:
        updates['failure']=None
        if type(record) is BattlecryRecord:updates['payload_started']=True
    if type(record) is HeroPowerRecord:
        from .model import HeroPowerRepeatPlan
        updates.update(payloads=(),repeat_plan=HeroPowerRepeatPlan())
    return replace(record,**updates)


def finish(r,effect):
    proof=effect.proof;validate_proof(proof,r.registry);proposal=proof.proposal
    if proof.origin!='manual_card':
        row=getattr(r.state,HISTORIES[proof.origin])[proposal.id-1]
        if row.native_target!=proof.selection or normalized(row)!=proposal:
            raise ValueError('Native target Finish changed its actual accepted record')
    r.emit(FINISHED,source_id=proposal.source_id,target_id=proof.selection.target_id,player_id=proposal.player_id,
        origin=proof.origin,activation_id=proposal.id,_capture=False)
    return ()


def validate_boundary(game):
    if not game.registry.random_target_cards:return
    from .hero_health_history import effective_events
    from .continuations import FrameCodec
    from .allocation_facts import validate_allocation
    codec=FrameCodec(game.mechanics,game.registry);accepted={};finished=set()
    for event in effective_events(game._events):
        if event.kind not in(ACCEPTED,FINISHED):continue
        data=dict(event.data);key=(data['origin'],data['activation_id'])
        if event.kind==ACCEPTED:
            if key in accepted:raise ValueError('Native target accepted one activation twice')
            selection=codec.decode(json.loads(data['selection']));proposal=codec.decode(json.loads(data['proposal']))
            if type(selection)is not NativeTargetSelection or key[0]not in FAMILIES or type(proposal)is not FAMILIES[key[0]]:
                raise ValueError('Native target acceptance lost its typed original material')
            p=selection.partition
            if (p.origin,proposal.id,proposal.source_id,proposal.player_id,selection.target_id)!=(key[0],key[1],event.source_id,event.player_id,event.target_id)or p.submitted_target_id!=proposal.target_id:
                raise ValueError('Native target acceptance borrowed its original proposal')
            for fact in(p.source,*(x.source for x in p.carriers),*p.candidates):validate_allocation(game._state,game.registry,fact)
            if key[0]!='manual_card':
                rows=getattr(game._state,HISTORIES[key[0]])
                if key[1]>len(rows)or rows[key[1]-1].native_target!=selection or normalized(rows[key[1]-1])!=proposal:
                    raise ValueError('Native target acceptance lost its actual family record')
            else:
                targeted=[e for e in effective_events(game._events)if e.kind=='spell_targeted'and dict(e.data).get('window_id')==key[1]]
                valid=(not targeted if selection.failure else len(targeted)==1 and
                    targeted[0].target_id==selection.target_id and targeted[0].source_id==event.source_id)
                if not valid:
                    raise ValueError('Native spell target acceptance lost its actual target publication')
                if selection.failure is not None and any(c.failure!='no_target'or c.target_id is not None or
                        c.payload_started or not c.completed for c in game._state.cast_history if c.play_id==proposal.play_id):
                    raise ValueError('Native empty domain cannot invent a successful hand CAST')
            accepted[key]=(event,selection,proposal)
        else:
            if key not in accepted or key in finished:raise ValueError('Native target Finish duplicated or borrowed an acceptance')
            parent,selection,proposal=accepted[key]
            if (event.source_id,event.player_id,event.target_id)!=(parent.source_id,parent.player_id,selection.target_id):
                raise ValueError('Native target Finish changed the accepted actor or target')
            finished.add(key)
    for origin,history in HISTORIES.items():
        for row in getattr(game._state,history):
            if row.native_target is not None and (origin,row.id)not in accepted:
                raise ValueError('Native family record lost its complete acceptance receipt')
    for cast in game._state.cast_history:
        if cast.play_id is None or cast.failure!='no_target':continue
        if cast.spell_target_receipt is not None:continue
        matches=[selection for key,(_,selection,proposal)in accepted.items()if key[0]=='manual_card'and
            proposal.play_id==cast.play_id and selection.failure=='no_target']
        if len(matches)!=1 or cast.target_id is not None:
            raise ValueError('Failed hand CAST lost its actual native empty-domain acceptance')
    if game._state.status!='playing':return
    queue=()if game._frame is None else(*game._frame.prefix,*game._frame.continuation)
    for key,(event,selection,proposal)in accepted.items():
        if key in finished:continue
        controls=[w for w in queue if type(w)is FinishNativeTarget and(w.proof.origin,w.proof.proposal.id)==key]
        if len(controls)!=1 or controls[0].proof.selection!=selection or controls[0].proof.proposal!=proposal:
            raise ValueError('Waiting native target lost its unique original Finish')
        validate_proof(controls[0].proof,game.registry)


def register(mechanics):
    for cls in(RandomTargetCarrier,NativeTargetPartition,NativeTargetSelection,NativeTargetProof):mechanics.register_payload_type(cls)
    mechanics.register(FinishNativeTarget,finish)
