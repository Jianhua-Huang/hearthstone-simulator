"""A native summon prefix finishes before its selected Deathrattle suffix."""
from dataclasses import dataclass

from .effects import Effect, InvokeBehavior
from .errors import ResolutionError
from .model import CardType, _name
from .pools import PoolQuery, SummonFromPool
from .registry import RuleContext
from .summon_quantities import SummonCause


@dataclass(frozen=True)
class AssembleDeferredDeathSource:
    card_id: str
    original_deathrattle_id: str
    original_suffix_id: str
    pool_id: str
    query: PoolQuery

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        for field in ('card_id','original_deathrattle_id','original_suffix_id','pool_id'):
            _name(getattr(self,field),'deferred Deathrattle '+field)
        if (self.card_id.startswith('assemble:') or
                any(v.startswith(TIMING_PREFIXES) for v in (self.original_deathrattle_id,self.original_suffix_id)) or
                type(self.query) is not PoolQuery or
                self.query != PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1)):
            raise ValueError('Deferred prefix requires the original two one-cost minion requests')


def validate_source(registry, source, *, require_template=False):
    if type(source) is not AssembleDeferredDeathSource:
        raise ValueError('Expected AssembleDeferredDeathSource')
    source.__post_init__()
    original=registry._cards.get(source.card_id)
    if original is None or original.kind!=CardType.MINION or original.deathrattle!=source.original_deathrattle_id:
        raise ValueError('Deferred prefix changed its complete original Deathrattle')
    registry.behavior(source.original_deathrattle_id);registry.behavior(source.original_suffix_id)
    template=registry._assemble_templates.get(source.card_id)
    if require_template and template is None:raise ValueError('Deferred source lacks its native template')
    if template is not None:validate_prefix(template,source)


def validate_prefix(template, source):
    if (template.prefix.timing!='deathrattle' or
            template.prefix.before_behavior_id!=source.original_deathrattle_id or
            template.original_deathrattle_id!=source.original_deathrattle_id):
        raise ValueError('Deferred Deathrattle changed its selected original prefix')


def native_deathrattle(registry, template, suffix):
    source=registry._assemble_deferred_death_sources.get(template.card_id)
    if source is None:
        if any(p.original_deathrattle_id==template.prefix.before_behavior_id
                for p in registry._assemble_deferred_death_sources.values()):
            raise ValueError('Deferred prefix borrowed another original source')
        return None
    validate_source(registry,source);validate_prefix(template,source)
    return source.original_deathrattle_id if suffix==template.suffix else None


@dataclass(frozen=True)
class AssembleDeathContinuation:
    accepted: RuleContext
    before_behavior_id: str
    behavior_id: str

    def __post_init__(self):
        if (type(self.accepted) is not RuleContext or self.accepted.deathrattle is None or
                self.accepted.deathrattle_followup is not None):
            raise ValueError('Deathrattle followup requires one original nonrecursive acceptance')
        _name(self.before_behavior_id,'original prefix program');_name(self.behavior_id,'selected suffix program')


def validate_material(registry, material):
    if type(material) is not AssembleDeathContinuation:raise ValueError('Expected original Deathrattle continuation')
    material.__post_init__()
    from .deathrattles import validate_context
    from .assemble_faces import before_behavior_id,recipe_from_id
    origin=material.accepted;validate_context(origin,registry)
    # The declaration follows copied/inherited abilities and accepted repeats;
    # the current carrier may already have another face or board residence.
    declaration_id=origin.deathrattle.ability.deathrattle_card_id
    recipe=recipe_from_id(declaration_id)
    prefix_id=recipe.secondary_card_id if recipe.half=='top' else recipe.primary_card_id
    source=registry._assemble_deferred_death_sources.get(prefix_id)
    if source is None or source.original_deathrattle_id!=material.before_behavior_id:
        raise ValueError('Followup changed its actual selected native program')
    validate_source(registry,source,require_template=True)
    identity=before_behavior_id(material.before_behavior_id,material.behavior_id)
    if (origin.deathrattle.ability.behavior_id!=identity or
            registry.card(declaration_id).deathrattle!=identity):
        raise ValueError('Followup changed the whole accepted immutable face')
    registry.behavior(material.behavior_id)
    return source


def validate_request(state,registry,material):
    validate_material(registry,material)
    from .deathrattles import validate_capture,record
    capture=material.accepted.deathrattle;validate_capture(state,registry,capture)
    current=record(state,capture.id)
    if current.capture!=capture or current.execution_order is None or current.completed or current.interrupted:
        raise ValueError('Followup requires its still-running original Deathrattle')


def validate_context(context,registry):
    material=context.deathrattle_followup
    validate_request(context.state,registry,material)
    origin=material.accepted
    if ((context.source_id,context.player_id,context.target_id,context.deathrattle,context.death,context.event)!=
            (origin.source_id,origin.player_id,origin.target_id,origin.deathrattle,origin.death,origin.event)):
        raise ValueError('Followup changed its accepted root, source, event or player')


def validate_call(call,registry):
    if call.context.deathrattle_followup is not None:
        validate_context(call.context,registry)
        if call.behavior_id!=call.context.deathrattle_followup.behavior_id:
            raise ValueError('Followup callback differs from the selected suffix')


@dataclass(frozen=True)
class ContinueAssembledDeathrattle(Effect):
    continuation: AssembleDeathContinuation

    def __post_init__(self):
        if type(self.continuation) is not AssembleDeathContinuation:raise ValueError('Expected typed Deathrattle continuation')
        self.continuation.__post_init__()

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_request(state,registry,self.continuation)


def selected_request(registry,context,before_id,body_id):
    matches=[p for p in registry._assemble_deferred_death_sources.values()if p.original_deathrattle_id==before_id]
    if not matches:return None
    source,=matches
    material=AssembleDeathContinuation(context,before_id,body_id);validate_material(registry,material)
    planned=registry.behavior(before_id)(context)
    summon=SummonFromPool(context.player_id,source.pool_id,source.query,
        source_id=context.source_id,cause=SummonCause.capture(context))
    expected=(summon,summon,InvokeBehavior(source.original_suffix_id,context.source_id,context.player_id))
    if planned!=expected:raise ResolutionError('Deferred prefix changed its complete native ordered plan')
    return (*planned[:2],ContinueAssembledDeathrattle(material))


def continue_deathrattle(r,effect):
    effect.validate_in_state(r.state,r.registry);material=effect.continuation;origin=material.accepted
    call=r.call(material.behavior_id,origin.source_id,origin.player_id,event=origin.event,
        death=origin.death,deathrattle=origin.deathrattle,deathrattle_followup=material)
    validate_call(call,r.registry)
    return (call,)


def validate_sources(registry):
    seen=set()
    for cid,source in registry._assemble_deferred_death_sources.items():
        validate_source(registry,source,require_template=True)
        if cid!=source.card_id or source.original_deathrattle_id in seen:raise ValueError('Duplicate deferred native prefix')
        seen.add(source.original_deathrattle_id)


def register(mechanics):
    mechanics.register_payload_type(AssembleDeathContinuation)
    mechanics.register(ContinueAssembledDeathrattle,continue_deathrattle)
