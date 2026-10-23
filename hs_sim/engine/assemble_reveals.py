"""One native physical spell reveal before its selected Battlecry reward."""
from dataclasses import dataclass,replace

from .deck_reveals import RevealRandomDeckCard,deck_reveal_result,validate_result
from .effects import Effect
from .errors import ResolutionError
from .model import CardType,_int,_name
from .registry import RuleContext


@dataclass(frozen=True)
class AssembleRevealSource:
    card_id: str
    original_battlecry_id: str
    result_behavior_id: str
    reward_behavior_id: str

    def __post_init__(self):
        for name in('card_id','original_battlecry_id','result_behavior_id','reward_behavior_id'):
            _name(getattr(self,name),'original reveal '+name)
        if self.card_id.startswith('assemble:'):raise ValueError('Reveal prefix requires its original static minion')


def validate_source(registry,source,*,require_template=False):
    if type(source)is not AssembleRevealSource:raise ValueError('Expected complete native reveal prefix')
    source.__post_init__();original=registry._cards.get(source.card_id)
    if (original is None or original.kind!=CardType.MINION or original.battlecry!=source.original_battlecry_id or
            original.requires_target or original.targeting is not None or original.target_rule!='any_entity'):
        raise ValueError('Reveal source changed its complete original targetless Battlecry')
    for key in(source.original_battlecry_id,source.result_behavior_id,source.reward_behavior_id):registry.behavior(key)
    template=registry._assemble_templates.get(source.card_id)
    if template is None:
        if require_template:raise ValueError('Reveal prefix lacks its original template')
    elif (template.prefix.timing!='battlecry' or template.prefix.condition_id is not None or
            template.prefix.before_behavior_id!=source.original_battlecry_id or
            template.original_battlecry_id!=source.original_battlecry_id or template.suffix.behavior_id!=source.reward_behavior_id):
        raise ValueError('Reveal prefix changed its native program or independent reward')


def native_battlecry(registry,template,suffix):
    source=registry._assemble_reveal_sources.get(template.card_id)
    if source is None:
        if any(p.original_battlecry_id==template.prefix.before_behavior_id for p in registry._assemble_reveal_sources.values()):
            raise ValueError('Reveal prefix borrowed another native declaration')
        return None
    validate_source(registry,source)
    return source.original_battlecry_id if suffix==template.suffix else None


@dataclass(frozen=True)
class AssembleRevealContinuation:
    accepted: RuleContext
    before_behavior_id: str
    behavior_id: str
    events_before: int | None = None

    def __post_init__(self):
        if (type(self.accepted)is not RuleContext or self.accepted.battlecry is None or
                self.accepted.deathrattle_followup is not None or self.accepted.paid_battlecry_followup is not None):
            raise ValueError('Reveal continuation requires its original Battlecry acceptance')
        _name(self.before_behavior_id,'original reveal program');_name(self.behavior_id,'selected reveal suffix')
        if self.events_before is not None:_int(self.events_before,'reveal original event prefix',0)


def validate_material(registry,material):
    if type(material)is not AssembleRevealContinuation:raise ValueError('Expected original reveal material')
    material.__post_init__();origin=material.accepted;record=origin.battlecry
    from .battlecries import validate_record
    from .assemble_faces import recipe_from_id,before_behavior_id
    validate_record(origin.state,registry,record)
    declaration=record.payload.card_id or record.card_id;recipe=recipe_from_id(declaration)
    prefix_id=recipe.secondary_card_id if recipe.half=='top'else recipe.primary_card_id
    source=registry._assemble_reveal_sources.get(prefix_id)
    if source is None or source.original_battlecry_id!=material.before_behavior_id:
        raise ValueError('Reveal material changed its actual original prefix')
    validate_source(registry,source,require_template=True)
    identity=before_behavior_id(material.before_behavior_id,material.behavior_id)
    if ((origin.source_id,origin.player_id,origin.target_id)!=(record.source_id,record.player_id,record.target_id) or
            record.payload.behavior_id!=identity or registry.card(declaration).battlecry!=identity):
        raise ValueError('Reveal material changed its original complete face or target')
    registry.behavior(material.behavior_id)
    return source


def validate_running(state,registry,material):
    source=validate_material(registry,material);origin=material.accepted
    from .battlecries import battlecry_record,validate_record
    current=battlecry_record(state,origin.battlecry.id);validate_record(state,registry,current)
    if (current.completed or current.interrupted or current.failure is not None or
            (current.source_id,current.player_id,current.target_id,current.payload)!=(
                origin.source_id,origin.player_id,origin.target_id,origin.battlecry.payload)):
        raise ValueError('Reveal continuation lost its still-running original Battlecry')
    return source,current


def native_request(registry,material):
    source=validate_material(registry,material);c=material.accepted
    expected=RevealRandomDeckCard(c.player_id,source_id=c.source_id,on_result=source.result_behavior_id)
    if registry.behavior(source.original_battlecry_id)(c)!=(expected,):
        raise ResolutionError('Reveal prefix changed its complete original physical spell request')
    return expected


@dataclass(frozen=True)
class RevealAssembledPrefix(Effect):
    continuation: AssembleRevealContinuation

    def __post_init__(self):
        if type(self.continuation)is not AssembleRevealContinuation:raise ValueError('Expected original reveal continuation')
        self.continuation.__post_init__()
        if self.continuation.events_before is not None:raise ValueError('Queued reveal already consumed its event prefix')

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_running(state,registry,self.continuation);native_request(registry,self.continuation)


@dataclass(frozen=True)
class ResolveAssembledRevealResult(Effect):
    continuation: AssembleRevealContinuation
    context: RuleContext

    def __post_init__(self):
        if type(self.continuation)is not AssembleRevealContinuation or type(self.context)is not RuleContext:
            raise ValueError('Reveal callback requires its typed material and original native view')
        self.continuation.__post_init__()
        if self.continuation.events_before is None:raise ValueError('Reveal callback lacks its actual producer event prefix')

    def validate_in_state(self,state,registry):
        self.__post_init__();material=self.continuation;origin=material.accepted;c=self.context
        validate_running(state,registry,material);validate_running(c.state,registry,material)
        result=deck_reveal_result(c.event)
        if (result is None or result.kind!=CardType.SPELL or c.event.sequence!=material.events_before+1 or
                (c.source_id,c.player_id,c.target_id,c.event.source_id,result.player_id)!=(
                    origin.source_id,origin.player_id,None,origin.source_id,origin.player_id)):
            raise ValueError('Reveal callback changed its original event, actor, range or cursor')
        validate_result(c.state,registry,result,captured=True)
        validate_result(state,registry,result)


def selected_request(registry,context,before_id,body_id):
    found=[p for p in registry._assemble_reveal_sources.values()if p.original_battlecry_id==before_id]
    if not found:return None
    source,=found;material=AssembleRevealContinuation(context,before_id,body_id)
    native_request(registry,material)
    return (RevealAssembledPrefix(material),)


def reveal(r,effect):
    effect.validate_in_state(r.state,r.registry)
    material=replace(effect.continuation,events_before=len(r.game._events))
    from .deck_reveals import reveal as native_reveal
    source=validate_material(r.registry,material)
    calls=native_reveal(r,native_request(r.registry,material));out=[]
    for call in calls:
        if call.behavior_id!=source.result_behavior_id:raise ResolutionError('Reveal changed its native callback')
        result=ResolveAssembledRevealResult(material,call.context);result.validate_in_state(r.state,r.registry);out.append(result)
    if len(out)!=1:raise ResolutionError('Reveal prefix lost its one native result callback')
    return tuple(out)


def resolve(r,effect):
    effect.validate_in_state(r.state,r.registry);c=effect.context;material=effect.continuation
    if c.event.sequence>len(r.game._events)or r.game._events[c.event.sequence-1]!=c.event:
        raise ResolutionError('Reveal callback lost its actual original committed event')
    source=validate_material(r.registry,material);planned=r.registry.behavior(source.result_behavior_id)(c)
    if planned==():return ()
    positive=r.registry.behavior(source.reward_behavior_id)(c)
    if not positive or planned!=positive:raise ResolutionError('Reveal gate changed its complete original positive program')
    _,record=validate_running(c.state,r.registry,material)
    return r.registry.behavior(material.behavior_id)(replace(c,battlecry=record,target_id=material.accepted.target_id))


def validate_sources(registry):
    seen=set()
    for cid,source in registry._assemble_reveal_sources.items():
        validate_source(registry,source,require_template=True)
        if cid!=source.card_id or source.original_battlecry_id in seen:raise ValueError('Duplicate original reveal source')
        seen.add(source.original_battlecry_id)


CONTROL=(ResolveAssembledRevealResult,)


def register(mechanics):
    mechanics.register_payload_type(AssembleRevealContinuation)
    mechanics.register(RevealAssembledPrefix,reveal);mechanics.register(ResolveAssembledRevealResult,resolve)
