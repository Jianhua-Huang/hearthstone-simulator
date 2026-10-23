"""Native single-damage prefixes and their original health-result gates.

Damage, reactions, deaths and deferred health reads stay in the ordinary
interpreter. Only a reviewed positive reward is replaced by the selected suffix.
"""
from dataclasses import dataclass, replace

from .effects import Damage, Effect
from .errors import ResolutionError
from .health_followups import InvokeHealthResult
from .health_outcomes import health_result
from .model import CardType, DamageKind, Event, TargetMode, TargetSpec, Zone, _int, _name
from .registry import RuleContext


@dataclass(frozen=True)
class AssembleHealthPrefixSource:
    card_id: str
    original_battlecry_id: str
    amount: int
    result_behavior_id: str
    reward_behavior_id: str
    deferred_result_id: str | None = None

    def __post_init__(self):
        for name in ('card_id','original_battlecry_id','result_behavior_id','reward_behavior_id'):
            _name(getattr(self,name),'native health prefix '+name)
        _int(self.amount,'native health prefix amount',1)
        if self.deferred_result_id is not None:_name(self.deferred_result_id,'native deferred result')
        if self.card_id.startswith('assemble:'):raise ValueError('Health prefix requires its original static minion')


def validate_source(registry,source,*,require_template=False):
    if type(source)is not AssembleHealthPrefixSource:raise ValueError('Expected complete native health prefix')
    source.__post_init__();original=registry._cards.get(source.card_id)
    if (original is None or original.kind!=CardType.MINION or
            original.battlecry!=source.original_battlecry_id or original.requires_target or
            original.target_rule!='any_entity' or original.targeting not in (
                TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,)),
                TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),relation='enemy'))):
        raise ValueError('Native health prefix changed its original minion target declaration')
    for key in (source.original_battlecry_id,source.result_behavior_id,source.reward_behavior_id):registry.behavior(key)
    if source.deferred_result_id is not None:registry.behavior(source.deferred_result_id)
    template=registry._assemble_templates.get(source.card_id)
    if template is None:
        if require_template:raise ValueError('Native health prefix lacks its original template')
    elif (template.prefix.timing!='battlecry' or template.prefix.condition_id is not None or
            template.prefix.before_behavior_id!=source.original_battlecry_id or
            template.original_battlecry_id!=source.original_battlecry_id or
            template.suffix.behavior_id!=source.reward_behavior_id):
        raise ValueError('Native health prefix changed its original whole program or reward')


def source_face(registry,template,suffix,face):
    source=registry._assemble_health_prefix_sources.get(template.card_id)
    if source is None:
        if any(p.original_battlecry_id==template.prefix.before_behavior_id
                for p in registry._assemble_health_prefix_sources.values()):
            raise ValueError('Health prefix borrowed a different native declaration')
        return face
    validate_source(registry,source)
    original=registry._cards[source.card_id];spec=original.targeting
    other=suffix.targeting or (TargetSpec() if suffix.requires_target else None)
    # The currently reviewed target-bearing suffix is the ordinary character
    # domain. Keep the narrower native minion/enemy restriction with the prefix.
    # A future incompatible arrow needs its actual source contract, not pruning.
    if other is not None and (other.mode!=TargetMode.IF_AVAILABLE or
            not set(spec.zones)<=set(other.zones) or not set(spec.kinds)<=set(other.kinds) or
            other.relation not in ('any',spec.relation) or suffix.target_rule!='any_entity'):
        raise ValueError('Health prefix has an unreviewed additional target domain')
    fields=dict(requires_target=False,targeting=spec,target_rule=original.target_rule)
    if suffix==template.suffix:fields['battlecry']=source.original_battlecry_id
    return replace(face,**fields)


@dataclass(frozen=True)
class AssembleHealthContinuation:
    accepted: RuleContext
    before_behavior_id: str
    behavior_id: str

    def __post_init__(self):
        if (type(self.accepted)is not RuleContext or self.accepted.battlecry is None or
                self.accepted.deathrattle_followup is not None or self.accepted.paid_battlecry_followup is not None):
            raise ValueError('Health prefix requires one original Battlecry acceptance')
        _name(self.before_behavior_id,'original health prefix');_name(self.behavior_id,'selected health suffix')


def validate_material(registry,material):
    if type(material)is not AssembleHealthContinuation:raise ValueError('Expected native health continuation')
    material.__post_init__();origin=material.accepted;record=origin.battlecry
    from .battlecries import validate_record
    from .assemble_faces import recipe_from_id,before_behavior_id
    validate_record(origin.state,registry,record)
    declaration=record.payload.card_id or record.card_id;recipe=recipe_from_id(declaration)
    prefix_id=recipe.secondary_card_id if recipe.half=='top' else recipe.primary_card_id
    source=registry._assemble_health_prefix_sources.get(prefix_id)
    if source is None or source.original_battlecry_id!=material.before_behavior_id:
        raise ValueError('Health continuation changed its original prefix')
    validate_source(registry,source,require_template=True)
    expected=before_behavior_id(material.before_behavior_id,material.behavior_id)
    if ((origin.source_id,origin.player_id,origin.target_id)!=(record.source_id,record.player_id,record.target_id) or
            record.payload.behavior_id!=expected or registry.card(declaration).battlecry!=expected):
        raise ValueError('Health continuation changed its original whole face or target')
    registry.behavior(material.behavior_id)
    return source


def validate_running(state,registry,material):
    source=validate_material(registry,material);origin=material.accepted
    from .battlecries import battlecry_record,validate_record
    current=battlecry_record(state,origin.battlecry.id);validate_record(state,registry,current)
    if (current.completed or current.interrupted or current.failure is not None or
            (current.source_id,current.player_id,current.payload)!=(origin.source_id,origin.player_id,origin.battlecry.payload)):
        raise ValueError('Health continuation lost its running original Battlecry')
    return source,current


def native_request(registry,material):
    source=validate_material(registry,material);c=material.accepted
    expected=() if c.target_id is None else (Damage(c.target_id,source.amount,c.source_id,
        DamageKind.MINION_ABILITY,source.result_behavior_id),)
    planned=registry.behavior(source.original_battlecry_id)(c)
    if planned!=expected:raise ResolutionError('Health prefix changed its complete original damage program')
    return expected


@dataclass(frozen=True)
class ApplyAssembledHealthPrefix(Effect):
    continuation: AssembleHealthContinuation

    def __post_init__(self):
        if type(self.continuation)is not AssembleHealthContinuation:raise ValueError('Expected native health material')
        self.continuation.__post_init__()
    def validate_in_state(self,state,registry):
        self.__post_init__();validate_running(state,registry,self.continuation);native_request(registry,self.continuation)


@dataclass(frozen=True)
class AssembledHealthDamageBatch(Effect):
    continuation: AssembleHealthContinuation

    def __post_init__(self):
        if type(self.continuation)is not AssembleHealthContinuation:raise ValueError('Expected native health material')
        self.continuation.__post_init__()
    def validate_in_state(self,state,registry):
        self.__post_init__();validate_running(state,registry,self.continuation);native_request(registry,self.continuation)


def validate_event(state,registry,material,event):
    source,_=validate_running(state,registry,material);result=health_result(event);origin=material.accepted
    if (result is None or (result.source_id,result.source_controller,result.original_target_id,
            result.base_amount,result.original_flow,result.damage_kind)!=(origin.source_id,origin.player_id,
                origin.target_id,source.amount,'damage',DamageKind.MINION_ABILITY.value)):
        raise ValueError('Health suffix changed its original sourced damage result')
    matches=[row for row in state.damage_history if row.result==result.payload()]
    if len(matches)!=1 or matches[0].id<=len(origin.state.damage_history):
        raise ValueError('Health suffix borrowed an old, missing or duplicate result')
    return source,result


@dataclass(frozen=True)
class ResolveAssembledHealthResult(Effect):
    continuation: AssembleHealthContinuation
    context: RuleContext
    stage: int = 0

    def __post_init__(self):
        if type(self.continuation)is not AssembleHealthContinuation:raise ValueError('Expected native health material')
        self.continuation.__post_init__()
        if type(self.context)is not RuleContext or type(self.stage)is not int or self.stage not in(0,1):
            raise ValueError('Native health gate requires its original callback view and stage')

    def validate_in_state(self,state,registry):
        self.__post_init__();source,result=validate_event(state,registry,self.continuation,self.context.event)
        validate_event(self.context.state,registry,self.continuation,self.context.event)
        origin=self.continuation.accepted
        if ((self.context.source_id,self.context.player_id,self.context.target_id)!=(
                origin.source_id,origin.player_id,result.target_id if self.stage==0 else result.original_target_id) or
                self.stage==1 and source.deferred_result_id is None):
            raise ValueError('Health callback changed its original actor, result target or deferred stage')


@dataclass(frozen=True)
class RecheckAssembledHealthResult(Effect):
    continuation: AssembleHealthContinuation
    event: Event

    def __post_init__(self):
        if type(self.continuation)is not AssembleHealthContinuation:raise ValueError('Expected native health material')
        self.continuation.__post_init__()
        if type(self.event)is not Event:raise ValueError('Deferred health gate requires its original event')

    def validate_in_state(self,state,registry):
        self.__post_init__();source,_=validate_event(state,registry,self.continuation,self.event)
        if source.deferred_result_id is None:raise ValueError('Health prefix has no native deferred result')


def selected_request(registry,context,before_id,body_id):
    found=[s for s in registry._assemble_health_prefix_sources.values() if s.original_battlecry_id==before_id]
    if not found:return None
    source,=found;material=AssembleHealthContinuation(context,before_id,body_id)
    if not native_request(registry,material):return ()
    return (ApplyAssembledHealthPrefix(material),)


def begin(r,effect):
    effect.validate_in_state(r.state,r.registry)
    return (AssembledHealthDamageBatch(effect.continuation),)


def damage(r,effect):
    effect.validate_in_state(r.state,r.registry)
    from .resolver import settle_health_batch
    return settle_health_batch(r,native_request(r.registry,effect.continuation),assembled_health=effect.continuation)


def bind_result(registry,material,call):
    source=validate_material(registry,material)
    if call.behavior_id!=source.result_behavior_id:raise ValueError('Health prefix changed its original callback')
    result=ResolveAssembledHealthResult(material,call.context)
    result.validate_in_state(call.context.state,registry)
    return result


def resolve_result(r,effect):
    effect.validate_in_state(r.state,r.registry);source,_=validate_event(r.state,r.registry,effect.continuation,effect.context.event)
    if (effect.context.event.sequence>len(r.game._events) or
            r.game._events[effect.context.event.sequence-1]!=effect.context.event):
        raise ResolutionError('Health prefix lost its actual committed event')
    key=source.result_behavior_id if effect.stage==0 else source.deferred_result_id
    planned=r.registry.behavior(key)(effect.context)
    if planned==():return ()
    if effect.stage==0 and source.deferred_result_id is not None:
        if planned!=(InvokeHealthResult(source.deferred_result_id,effect.context.event),):
            raise ResolutionError('Health prefix changed its native deferred-result program')
        return (RecheckAssembledHealthResult(effect.continuation,effect.context.event),)
    positive=r.registry.behavior(source.reward_behavior_id)(effect.context)
    if not positive or planned!=positive:raise ResolutionError('Health gate changed its complete original positive reward')
    _,record=validate_running(effect.context.state,r.registry,effect.continuation)
    selected=replace(effect.context,battlecry=record,target_id=effect.continuation.accepted.target_id)
    return r.registry.behavior(effect.continuation.behavior_id)(selected)


def recheck(r,effect):
    effect.validate_in_state(r.state,r.registry);source,_=validate_event(r.state,r.registry,effect.continuation,effect.event)
    from .health_followups import invoke
    calls=invoke(r,InvokeHealthResult(source.deferred_result_id,effect.event))
    return tuple(ResolveAssembledHealthResult(effect.continuation,call.context,1)for call in calls)


def validate_sources(registry):
    seen=set()
    for cid,source in registry._assemble_health_prefix_sources.items():
        validate_source(registry,source,require_template=True)
        if cid!=source.card_id or source.original_battlecry_id in seen:raise ValueError('Duplicate original native health prefix')
        seen.add(source.original_battlecry_id)


CONTROL=(ResolveAssembledHealthResult,)


def register(mechanics):
    mechanics.register_payload_type(AssembleHealthContinuation)
    for kind,handler in ((ApplyAssembledHealthPrefix,begin),(AssembledHealthDamageBatch,damage),
            (ResolveAssembledHealthResult,resolve_result),(RecheckAssembledHealthResult,recheck)):
        mechanics.register(kind,handler)
