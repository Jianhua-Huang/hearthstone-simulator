"""Explicit original hand/board arrows; ordinary menus never enter this path.

Historical payload names stay stable. Multiple arrows share one acceptance
window and retain their original distinct-target constraint and batch body.
"""
from .runtime_copy import deepcopy
from dataclasses import dataclass,replace
import json

from .allocation_facts import SourceAllocationFact,validate_allocation
from .effects import Effect,RequestChoice,_integer
from .model import CardType,ChoiceResult,Event,GameState,PendingChoice,TargetSpec,Zone
from .native_random_targets import NativeTargetPartition,NativeTargetSelection,current_sources,sample
from .rules import Ruleset

OFFERED='native_hand_targets_offered'
ACCEPTED='native_hand_target_selected'
FINISHED='native_hand_target_finished'


def hand_target(kinds=(CardType.MINION,CardType.SPELL,CardType.WEAPON,CardType.LOCATION,CardType.HERO)):
    return TargetSpec(zones=(Zone.HAND,),kinds=kinds,relation='friendly',exclude_source=False)


def validate_request(choice,request):
    if type(choice)is not PendingChoice or type(request)is not RequestChoice or request.targeting is None:
        raise ValueError('Hand arrow lost its original typed choice request')
    request.__post_init__();choice.__post_init__()
    expected=PendingChoice(choice.id,request.player_id,request.source_id,request.prompt,
        tuple(o.item for o in request.options),request.min_count,request.max_count,request.purpose,request.repeat_key)
    ids=tuple(o.entity_id for o in request.options)
    if expected!=choice or any(i is None for i in ids) or len(set(ids))!=len(ids) or len(request.target_facts)!=len(ids):
        raise ValueError('Hand arrow lost its complete one-per-entity original offer')
    if tuple(f.entity_id for f in request.target_facts)!=ids:
        raise ValueError('Hand arrow changed its original target order')
    for item,fact in zip(request.options,request.target_facts):
        spec=request.targeting
        if (fact.zone not in spec.zones or spec.zones==(Zone.HAND,)and item.card_id is None or
                item.card_id is not None and fact.card_id!=item.card_id or
                fact.kind not in spec.kinds or spec.relation=='friendly'and fact.controller!=request.player_id or
                spec.relation=='enemy'and fact.controller==request.player_id):
            raise ValueError('Target arrow offered a foreign physical card or kind')


def capture_offer(r,choice,request):
    from .native_target_acceptance import encode
    facts=tuple(SourceAllocationFact.capture(r.state,r.state.entities[o.entity_id])for o in request.options)
    request=replace(request,target_facts=facts);validate_request(choice,request)
    r.emit(OFFERED,source_id=request.source_id,player_id=request.player_id,choice_id=choice.id,
        request=encode(r,request),_capture=False)
    return request


def target_origin(request):
    return 'hand_choice'if request.targeting.zones==(Zone.HAND,)else'board_choice'


def contract_digest(request):
    from dataclasses import asdict
    from hs_sim.targets import canonical_digest
    kind='original-hand-arrow-v1'if target_origin(request)=='hand_choice'else'original-board-arrow-v1'
    return canonical_digest({'kind':kind,'targeting':asdict(request.targeting)})


def partition(state,registry,request,result,index=0,excluded=()):
    source=state.entities[request.source_id]
    original=result.selected[index].entity_id
    carriers=current_sources(state,registry);applied=bool(carriers)
    offered={x.entity_id:x for x in request.target_facts}
    spec=request.targeting
    if target_origin(request)=='board_choice':
        from .targeting import target_choices
        actor=deepcopy(source);actor.controller=request.player_id
        definition=replace(registry.card(source.card_id),targeting=spec,requires_target=False,target_rule='any_entity')
        live=set(target_choices(state,registry,actor,definition))if applied else set()
    else:live=set(state.players[request.player_id].hand)
    # Each original physical residence is immutable, including for board copies
    # and captured batch removal. Re-entry cannot reuse an offered numeric ID.
    candidates=tuple(x for eid,e in sorted(state.entities.items())
        for x in(SourceAllocationFact.capture(state,e),)if applied and eid in offered and eid in live and eid not in excluded and
        e.zone in spec.zones and e.kind in spec.kinds and(not spec.exclude_source or eid!=request.source_id)and
        (x.card_id,x.kind,x.owner,x.controller,x.zone,x.zone_epoch,x.entered_order)==
        (offered[x.entity_id].card_id,offered[x.entity_id].kind,offered[x.entity_id].owner,
         offered[x.entity_id].controller,offered[x.entity_id].zone,offered[x.entity_id].zone_epoch,offered[x.entity_id].entered_order))
    return NativeTargetPartition(SourceAllocationFact.capture(state,source),request.player_id,target_origin(request),
        contract_digest(request),
        original,request.targeting.mode,carriers,candidates,applied)


def validate_samples(request,result,selections):
    validate_request(result.choice,request);result.__post_init__()
    if type(selections)is not tuple or len(selections)!=len(result.selected_ids):
        raise ValueError('Target arrows lost one of their original selections')
    selected=set();first=None;previous=None
    for item,selection in zip(result.selected,selections):
        if type(selection)is not NativeTargetSelection:raise ValueError('Target arrow lost its typed draw')
        selection.__post_init__();p=selection.partition
        if (not p.applied or(p.origin,p.source.entity_id,p.player_id,p.submitted_target_id,p.mode,p.definition_digest)!=(
                target_origin(request),request.source_id,request.player_id,item.entity_id,request.targeting.mode,contract_digest(request))):
            raise ValueError('Target arrow changed its original user selection or domain')
        if first is None:first=p
        elif ((p.source,p.carriers,p.candidates)!=(first.source,first.carriers,
                tuple(x for x in first.candidates if x.entity_id not in selected)) or selection.rng_before!=previous.rng_after):
            raise ValueError('Distinct target arrows changed the joint acceptance window or RNG chain')
        if selection.target_id is not None:selected.add(selection.target_id)
        previous=selection


def selected_ids(request,selections):
    selected={x.target_id for x in selections if x.failure is None}
    return tuple(o.id for o in request.options if o.entity_id in selected)


@dataclass(frozen=True)
class NativeChoiceResult(ChoiceResult):
    """Execution subset only; the original complete user input stays valid.

    A reaction may remove all but one candidate. Never falsify the original
    PendingChoice counts or pass an invalid manual ChoiceResult to a callback.
    """
    original: ChoiceResult
    request: RequestChoice
    selections: tuple[NativeTargetSelection,...]

    def __post_init__(self):
        if type(self.original)is not ChoiceResult or self.choice!=self.original.choice:
            raise ValueError('Native execution subset lost its complete original manual input')
        validate_samples(self.request,self.original,self.selections)
        if (self.selected_ids!=selected_ids(self.request,self.selections) or
                not 0<len(self.selected_ids)<self.choice.min_count):
            raise ValueError('Native execution subset is not the actual surviving target subset')


def actual_result(request,result,selection,additional=()):
    selections=(selection,*additional);validate_samples(request,result,selections)
    ids=selected_ids(request,selections)
    if not ids:return None
    if len(ids)<result.choice.min_count:return NativeChoiceResult(result.choice,ids,result,request,selections)
    return ChoiceResult(result.choice,ids)


@dataclass(frozen=True)
class NativeHandTargetProof:
    before_state: GameState
    rules: Ruleset
    request: RequestChoice
    original: ChoiceResult
    actual: ChoiceResult | None
    selection: NativeTargetSelection
    selection_event: Event
    acceptance_id: int
    additional_selections: tuple[NativeTargetSelection,...] = ()

    def __post_init__(self):
        if (type(self.before_state)is not GameState or type(self.rules)is not Ruleset or
                type(self.original)is not ChoiceResult or type(self.selection)is not NativeTargetSelection or
                type(self.selection_event)is not Event or type(self.additional_selections)is not tuple):
            raise ValueError('Hand target proof requires its complete original manual selection')
        validate_request(self.original.choice,self.request);self.selection.__post_init__()
        _integer(self.acceptance_id,'actual hand target receipt',1)
        e=self.selection_event;data=dict(e.data);p=self.selection.partition
        validate_samples(self.request,self.original,(self.selection,*self.additional_selections))
        if (not p.applied or e.kind!='choice_selected' or
                (e.source_id,e.player_id,data.get('choice_id'),data.get('option_ids'))!=(self.request.source_id,
                 self.request.player_id,self.original.choice.id,self.original.selected_ids) or
                (p.origin,p.source.entity_id,p.player_id,p.submitted_target_id)!=(target_origin(self.request),self.request.source_id,
                 self.request.player_id,self.original.selected[0].entity_id) or
                self.actual!=actual_result(self.request,self.original,self.selection,self.additional_selections)):
            raise ValueError('Hand target proof changed the actual user submission or result')


def validate_proof(proof,registry):
    proof.__post_init__();state=proof.before_state
    if state.status!='playing' or state.pending_choice is not None or proof.original.choice.id>=state.next_choice_id:
        raise ValueError('Hand target proof lost its actual committed selection phase')
    for fact in proof.request.target_facts:validate_allocation(state,registry,fact)
    excluded=[]
    for index,selection in enumerate((proof.selection,*proof.additional_selections)):
        if partition(state,registry,proof.request,proof.original,index,excluded)!=selection.partition:
            raise ValueError('Target proof cropped or changed the complete live offered domain')
        if selection.target_id is not None:excluded.append(selection.target_id)


def accept(r,request,result,selection_event):
    validate_request(result.choice,request)
    if not r.registry.random_target_cards:return result,None
    value=partition(r.state,r.registry,request,result)
    if not value.applied:return result,None
    before=deepcopy(r.state);selection=sample(r.game._rng,value);additional=[];excluded=[]
    if selection.target_id is not None:excluded.append(selection.target_id)
    for index in range(1,len(result.selected_ids)):
        other=sample(r.game._rng,partition(r.state,r.registry,request,result,index,excluded));additional.append(other)
        if other.target_id is not None:excluded.append(other.target_id)
    additional=tuple(additional);actual=actual_result(request,result,selection,additional)
    from .native_target_acceptance import encode
    event=r.emit(ACCEPTED,source_id=request.source_id,target_id=selection.target_id,player_id=request.player_id,
        choice_id=result.choice.id,request=encode(r,request),original=encode(r,result),actual=encode(r,actual),
        selection=encode(r,selection),selection_event=encode(r,selection_event),
        additional_selections=encode(r,additional),_capture=False)
    return actual,NativeHandTargetProof(before,r.rules,request,result,actual,selection,selection_event,event.sequence,additional)


@dataclass(frozen=True)
class ResolveNativeHandChoice(Effect):
    request: RequestChoice
    original: ChoiceResult
    selection_event: Event

    def __post_init__(self):
        if type(self.original)is not ChoiceResult or type(self.selection_event)is not Event:
            raise ValueError('Native hand continuation requires its actual manual result')
        validate_request(self.original.choice,self.request)
        data=dict(self.selection_event.data)
        if self.selection_event.kind!='choice_selected' or(
                self.selection_event.source_id,self.selection_event.player_id,data.get('choice_id'),data.get('option_ids'))!=(
                self.request.source_id,self.request.player_id,self.original.choice.id,self.original.selected_ids):
            raise ValueError('Native hand continuation changed the actual player selection')


def resolve(r,effect):
    from .choices import choice_effects
    result,proof=accept(r,effect.request,effect.original,effect.selection_event)
    body=[]if result is None else choice_effects(r,result,effect.request.options,effect.request.on_select,
        selection_event=effect.selection_event)
    return [*body,*(()if proof is None else(FinishNativeHandTarget(proof),))]


@dataclass(frozen=True)
class FinishNativeHandTarget(Effect):
    proof: NativeHandTargetProof
    def __post_init__(self):
        if type(self.proof)is not NativeHandTargetProof:raise ValueError('Hand target Finish requires its original proof')
        self.proof.__post_init__()


def finish(r,effect):
    proof=effect.proof;validate_proof(proof,r.registry)
    r.emit(FINISHED,source_id=proof.request.source_id,target_id=proof.selection.target_id,
        player_id=proof.request.player_id,acceptance_id=proof.acceptance_id,_capture=False)
    return ()


def validate_boundary(game):
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    events=effective_events(game._events);frame=game._frame
    queue=()if frame is None else(*frame.prefix,*frame.continuation)
    relevant=[e for e in events if e.kind in(OFFERED,ACCEPTED,FINISHED)]
    if not relevant and(frame is None or frame.native_target_request is None)and not any(
            type(x)in(ResolveNativeHandChoice,FinishNativeHandTarget)for x in queue):
        return
    codec=FrameCodec(game.mechanics,game.registry)
    offers={};accepted={};finished=set()
    for event in relevant:
        data=dict(event.data)
        if event.kind==OFFERED:
            ident=data['choice_id'];request=codec.decode(json.loads(data['request']))
            if ident in offers or type(request)is not RequestChoice or request.targeting is None or (
                    event.source_id,event.player_id)!=(request.source_id,request.player_id):
                raise ValueError('Hand target offer duplicated or borrowed an entry')
            validate_request(PendingChoice(ident,request.player_id,request.source_id,request.prompt,
                tuple(o.item for o in request.options),request.min_count,request.max_count,request.purpose,request.repeat_key),request)
            for fact in request.target_facts:validate_allocation(game._state,game.registry,fact)
            requested=[e for e in events if e.kind=='choice_requested'and dict(e.data).get('choice_id')==ident]
            if len(requested)!=1 or dict(requested[0].data).get('option_ids')!=tuple(o.id for o in request.options):
                raise ValueError('Hand target offer lost its complete actual choice publication')
            offers[ident]=request
        elif event.kind==ACCEPTED:
            ident=data['choice_id'];request=codec.decode(json.loads(data['request']))
            original=codec.decode(json.loads(data['original']));actual=codec.decode(json.loads(data['actual']))
            selection=codec.decode(json.loads(data['selection']));selected=codec.decode(json.loads(data['selection_event']))
            additional=codec.decode(json.loads(data['additional_selections']))
            if (ident not in offers or request!=offers[ident] or ident in accepted or
                    type(selection)is not NativeTargetSelection or type(original)is not ChoiceResult or
                    (event.source_id,event.player_id,event.target_id)!=(request.source_id,request.player_id,selection.target_id) or
                    original.choice.id!=ident or actual!=actual_result(request,original,selection,additional) or
                    not 0<selected.sequence<event.sequence or game._events[selected.sequence-1]!=selected):
                raise ValueError('Hand target acceptance changed its original offer or submission')
            validate_request(original.choice,request)
            validate_samples(request,original,(selection,*additional))
            p=selection.partition;d=dict(selected.data)
            if (not p.applied or
                    (p.origin,p.source.entity_id,p.player_id,p.submitted_target_id)!=(target_origin(request),request.source_id,
                     request.player_id,original.selected[0].entity_id) or selected.kind!='choice_selected' or
                    (selected.source_id,selected.player_id,d.get('choice_id'),d.get('option_ids'))!=(request.source_id,
                     request.player_id,ident,original.selected_ids)):
                raise ValueError('Hand target receipt changed its actual user selection')
            for draw in(selection,*additional):
                p=draw.partition
                for fact in(p.source,*(x.source for x in p.carriers),*p.candidates):validate_allocation(game._state,game.registry,fact)
            accepted[ident]=(event,request,original,actual,selection,selected,additional)
        elif event.kind==FINISHED:
            match=[ident for ident,row in accepted.items()if row[0].sequence==data['acceptance_id']]
            if len(match)!=1 or match[0]in finished:raise ValueError('Hand target Finish duplicated or borrowed an entry')
            ident=match[0];parent,request,_,_,selection,_,_=accepted[ident]
            if (event.source_id,event.player_id,event.target_id)!=(request.source_id,request.player_id,selection.target_id):
                raise ValueError('Hand target Finish changed its accepted identity')
            finished.add(ident)
    if frame is not None and (frame.native_target_request is not None or game._state.pending_choice.id in offers):
        request=frame.native_target_request;choice=game._state.pending_choice
        validate_request(choice,request)
        if offers.get(choice.id)!=request or frame.options!=request.options or frame.on_select!=request.on_select:
            raise ValueError('Pending hand target lost its complete original offer')
    if game._state.status!='playing':return
    pending=set();accepted_ids={row[0].sequence:ident for ident,row in accepted.items()}
    for item in queue:
        if type(item)is ResolveNativeHandChoice:
            item.__post_init__();event=item.selection_event
            ident=item.original.choice.id
            if (ident in pending or ident in accepted or offers.get(ident)!=item.request or
                    not 0<event.sequence<=len(game._events) or game._events[event.sequence-1]!=event):
                raise ValueError('Pending hand target continuation lost its actual original offer')
            pending.add(ident)
        elif type(item)is FinishNativeHandTarget:
            ident=accepted_ids.get(item.proof.acceptance_id)
            if ident is None or ident in finished:
                raise ValueError('Hand target Finish borrowed a missing or already completed acceptance')
    for ident,(event,request,original,actual,selection,selected,additional)in accepted.items():
        if ident in finished:continue
        tails=[x for x in queue if type(x)is FinishNativeHandTarget and x.proof.acceptance_id==event.sequence]
        if len(tails)!=1 or (tails[0].proof.request,tails[0].proof.original,tails[0].proof.actual,
                tails[0].proof.selection,tails[0].proof.selection_event,tails[0].proof.additional_selections)!=(request,original,actual,selection,selected,additional):
            raise ValueError('Waiting hand target lost its unique original Finish')
        validate_proof(tails[0].proof,game.registry)


def register(mechanics):
    mechanics.register_payload_type(NativeHandTargetProof)
    mechanics.register_payload_type(NativeChoiceResult)
    mechanics.register(ResolveNativeHandChoice,resolve)
    mechanics.register(FinishNativeHandTarget,finish)
