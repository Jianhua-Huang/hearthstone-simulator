"""Native target replacement for actual location and nonspell on_play entries."""
from .runtime_copy import deepcopy
from dataclasses import dataclass
import json
from types import SimpleNamespace

from .actions import UseInteractable,UseLocation
from .effects import Effect, _integer
from .lifecycle import active_abilities
from .model import CardDefinition, CardType, GameState, PlayRecord
from .native_random_targets import NativeTargetSelection, manual_partition, sample
from .rules import Ruleset

ACCEPTED = 'native_active_target_selected'
FINISHED = 'native_active_target_finished'
REQUEST_TYPES={'location':UseLocation,'interactable':UseInteractable,'on_play':PlayRecord}


def source_id(origin, request):
    return request.entity_id if origin in ('location','interactable') else request.source_id


def target_id(origin,request):
    return request.card_entity_id if origin=='interactable' else request.target_id


def effective_definition(state, registry, origin, request):
    if origin=='interactable':
        from dataclasses import replace
        from .native_hand_targets import hand_target
        return replace(registry.card(state.entities[request.entity_id].card_id),interactable=None,
            targeting=hand_target(),requires_target=False,target_rule='any_entity')
    if origin == 'location':
        return registry.card(state.entities[request.entity_id].card_id)
    from .play_history import play_definition
    from .spell_casts import CONDITIONS, effective_definition as conditioned
    return conditioned(play_definition(state, registry, state.entities[request.source_id], request),
        {key:getattr(request,key) for key in CONDITIONS})


@dataclass(frozen=True)
class NativeActiveTargetProof:
    before_state: GameState
    rules: Ruleset
    origin: str
    request: object
    definition: CardDefinition
    behavior_ids: tuple[str, ...]
    selection: NativeTargetSelection
    acceptance_id: int
    information_json: str | None

    def __post_init__(self):
        if (type(self.before_state) is not GameState or type(self.rules) is not Ruleset or
                self.origin not in REQUEST_TYPES or
                type(self.request) is not REQUEST_TYPES[self.origin] or
                type(self.definition) is not CardDefinition or type(self.selection) is not NativeTargetSelection):
            raise ValueError('Native active proof lost its actual typed entry')
        self.request.__post_init__(); self.selection.__post_init__(); self.rules.__post_init__()
        _integer(self.acceptance_id,'actual native active receipt',1)
        if type(self.behavior_ids) is not tuple or not self.behavior_ids or any(type(x)is not str or not x for x in self.behavior_ids):
            raise ValueError('Native active proof requires complete original body identities')
        p = self.selection.partition
        if not p.applied or (p.origin,p.source.entity_id,p.player_id,p.submitted_target_id) != (
                self.origin,source_id(self.origin,self.request),self.request.player_id,target_id(self.origin,self.request)):
            raise ValueError('Native active proof changed its original actor or submission')
        if self.information_json is not None and type(json.loads(self.information_json)) is not dict:
            raise ValueError('Native active proof lost its original player knowledge')


def validate_proof(proof, registry):
    proof.__post_init__();state=deepcopy(proof.before_state);request=proof.request
    if state.status != 'playing':
        raise ValueError('Native active entry requires its original playing state')
    definition=effective_definition(state,registry,proof.origin,request)
    if definition != proof.definition:
        raise ValueError('Native active proof changed its actual effective target definition')
    needs_information=(registry.target_visibility(definition.target_rule)=='player' or
        proof.origin=='location' and registry.use_visibility(definition.use_rule)=='player')
    if needs_information != (proof.information_json is not None):
        raise ValueError('Native active proof changed predicate visibility')
    game=SimpleNamespace(_state=state,registry=registry,ruleset=proof.rules)
    if needs_information:
        from .information import Information
        game._information=Information.from_dict(json.loads(proof.information_json),game)
    probe=SimpleNamespace(state=state,registry=registry,game=game)
    entity=state.entities[source_id(proof.origin,request)]
    if proof.origin=='location':
        from .locations import location_error
        from .player_target_inputs import live_factory
        context=live_factory(probe,entity) if registry.use_visibility(definition.use_rule)=='player' else None
        if location_error(state,registry,proof.rules,request.player_id,entity.id,context_factory=context) is not None:
            raise ValueError('Native location proof lost its real available use')
        actual=tuple(a.behavior_id for a in active_abilities(entity,'on_use'))
    elif proof.origin=='interactable':
        from .interactables import use_error
        if use_error(state,registry,request.player_id,request.entity_id,request.card_entity_id) is not None:
            raise ValueError('Native investment proof lost its real available action')
        actual=(registry.card(entity.card_id).interactable.behavior_id,)
    else:
        from .play_history import play_record
        if (request.kind not in(CardType.MINION,CardType.WEAPON,CardType.HERO) or request.countered or
                request.completed or play_record(state,request.id)!=request):
            raise ValueError('Native on_play proof requires its actual paid nonspell root')
        actual=tuple(a.behavior_id for a in active_abilities(entity,'on_play'))
    if actual!=proof.behavior_ids:
        raise ValueError('Native active proof changed its complete original bodies')
    partition=manual_partition(probe,entity,definition,target_id(proof.origin,request),
        player_id=request.player_id,origin=proof.origin)
    partition=filter_partition(partition,registry,proof.origin)
    if partition!=proof.selection.partition:
        raise ValueError('Native active proof cropped or changed its complete original domain')


def filter_partition(value,registry,origin):
    if origin!='interactable':return value
    from dataclasses import replace
    return replace(value,candidates=tuple(x for x in value.candidates if registry.card(x.card_id).hand_playable))


def accept(r,origin,request,behavior_ids):
    if not r.registry.random_target_cards or target_id(origin,request) is None or not behavior_ids:
        return None
    entity=r.state.entities[source_id(origin,request)]
    definition=effective_definition(r.state,r.registry,origin,request)
    information=None
    if (r.registry.target_visibility(definition.target_rule)=='player' or
            origin=='location' and r.registry.use_visibility(definition.use_rule)=='player'):
        r.game._information.sync(r.game)
        information=json.dumps(r.game._information.to_dict(),ensure_ascii=False,sort_keys=True,separators=(',',':'))
    partition=manual_partition(r,entity,definition,target_id(origin,request),player_id=request.player_id,origin=origin)
    partition=filter_partition(partition,r.registry,origin)
    if not partition.applied:
        return None
    before=deepcopy(r.state);selection=sample(r.game._rng,partition)
    from .native_target_acceptance import encode
    event=r.emit(ACCEPTED,source_id=entity.id,target_id=selection.target_id,player_id=request.player_id,
        origin=origin,request=encode(r,request),selection=encode(r,selection),behavior_ids=behavior_ids,_capture=False)
    return NativeActiveTargetProof(before,r.rules,origin,request,definition,behavior_ids,selection,event.sequence,information)


@dataclass(frozen=True)
class FinishNativeActiveTarget(Effect):
    proof: NativeActiveTargetProof
    def __post_init__(self):
        if type(self.proof) is not NativeActiveTargetProof:
            raise ValueError('Native active Finish requires its complete original proof')
        self.proof.__post_init__()


def finish(r,effect):
    proof=effect.proof;validate_proof(proof,r.registry)
    r.emit(FINISHED,source_id=source_id(proof.origin,proof.request),target_id=proof.selection.target_id,
        player_id=proof.request.player_id,acceptance_id=proof.acceptance_id,origin=proof.origin,_capture=False)
    return ()


def validate_boundary(game):
    if not game.registry.random_target_cards:
        return
    from .continuations import FrameCodec
    from .hero_health_history import effective_events
    from .allocation_facts import validate_allocation
    codec=FrameCodec(game.mechanics,game.registry);events=effective_events(game._events);accepted={};finished={}
    for event in events:
        if event.kind not in(ACCEPTED,FINISHED):continue
        data=dict(event.data)
        if event.kind==ACCEPTED:
            origin=data['origin'];request=codec.decode(json.loads(data['request']));selection=codec.decode(json.loads(data['selection']))
            if origin not in REQUEST_TYPES or type(request)is not REQUEST_TYPES[origin] or type(selection)is not NativeTargetSelection:
                raise ValueError('Native active receipt lost its original typed entry')
            p=selection.partition
            if not p.applied or (p.origin,p.source.entity_id,p.player_id,p.submitted_target_id)!=(origin,source_id(origin,request),request.player_id,target_id(origin,request)) or (
                    event.source_id,event.player_id,event.target_id)!=(p.source.entity_id,request.player_id,selection.target_id):
                raise ValueError('Native active receipt borrowed its original actor or target')
            for fact in(p.source,*(x.source for x in p.carriers),*p.candidates):validate_allocation(game._state,game.registry,fact)
            for behavior in data['behavior_ids']:game.registry.behavior(behavior)
            if origin=='on_play':
                from .play_history import play_record
                play=play_record(game._state,request.id)
                if (play.source_id,play.player_id,play.card_id,play.target_id)!=(request.source_id,request.player_id,request.card_id,request.target_id):
                    raise ValueError('Native on_play receipt changed the original paid submission')
            accepted[event.sequence]=(event,request,selection)
        else:
            ident=data['acceptance_id']
            if ident not in accepted or ident in finished:
                raise ValueError('Native active Finish duplicated or borrowed an entry')
            original,request,selection=accepted[ident]
            if (event.source_id,event.player_id,event.target_id,data['origin'])!=(original.source_id,original.player_id,selection.target_id,dict(original.data)['origin']):
                raise ValueError('Native active Finish changed its accepted identity')
            finished[ident]=event.sequence
    frame=game._frame;queue=()if frame is None else(*frame.prefix,*frame.continuation)
    for ident,(event,request,selection)in accepted.items():
        if dict(event.data)['origin']=='location':
            started=[e for e in events if e.kind=='location_activated'and ident<e.sequence<=finished.get(ident,len(game._events))and
                (e.source_id,e.player_id)==(event.source_id,event.player_id)]
            if not started or started[0].target_id!=selection.target_id:
                raise ValueError('Native location lost its actual selected activation')
        elif dict(event.data)['origin']=='interactable':
            investments=[row for row in game._state.interactable_history if
                ident<row.started_event<=finished.get(ident,len(game._events)) and
                (row.entity_id,row.player_id)==(event.source_id,event.player_id)]
            if len(investments)!=1 or investments[0].invested.entity_id!=selection.target_id:
                raise ValueError('Native investment lost its actual selected hand payment')
        if game._state.status=='playing'and ident not in finished:
            tails=[x for x in queue if type(x)is FinishNativeActiveTarget and x.proof.acceptance_id==ident]
            if len(tails)!=1 or (tails[0].proof.request,tails[0].proof.selection)!=(request,selection):
                raise ValueError('Waiting native active entry lost its unique original Finish')
            validate_proof(tails[0].proof,game.registry)
    for item in queue:
        if type(item)is FinishNativeActiveTarget and item.proof.acceptance_id not in accepted:
            raise ValueError('Native active Finish has no actual acceptance')


def register(mechanics):
    mechanics.register_payload_type(NativeActiveTargetProof)
    mechanics.register(FinishNativeActiveTarget,finish)
