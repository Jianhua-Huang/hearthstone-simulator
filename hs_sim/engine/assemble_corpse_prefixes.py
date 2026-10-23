"""Printed corpse providers and the native success branch of a paid Battlecry."""
from dataclasses import dataclass, replace

from .corpse_gains import CorpseGainProfile
from .effects import Effect, SpendResource
from .model import CardType, Resource, _name, _optional_id
from .pools import DiscoverFromPool, PoolQuery
from .registry import RuleContext
from .errors import ResolutionError


@dataclass(frozen=True)
class AssembleCorpseGainSource:
    card_id: str
    native_profile: CorpseGainProfile

    def __post_init__(self):
        _name(self.card_id,'assembly corpse source')
        if type(self.native_profile) is not CorpseGainProfile or self.native_profile.card_id!=self.card_id:
            raise ValueError('Corpse prefix requires its full original native profile')
        self.native_profile.__post_init__()


def validate_gain_source(registry,source,*,require_template=False):
    if type(source) is not AssembleCorpseGainSource:raise ValueError('Expected native corpse prefix')
    source.__post_init__()
    if registry.corpse_gain_profiles.get(source.card_id)!=source.native_profile:
        raise ValueError('Corpse prefix differs from the complete original provider')
    original=registry._cards.get(source.card_id)
    if original is None or original.kind!=CardType.MINION:raise ValueError('Corpse prefix lost original minion')
    if require_template and source.card_id not in registry._assemble_templates:
        raise ValueError('Corpse prefix requires its original template')


def validate_gain_prefix(registry,template):
    source=registry._assemble_corpse_gain_sources.get(template.card_id)
    if source is None:
        if template.card_id in registry.corpse_gain_profiles:
            raise ValueError('Native corpse provider lacks its reviewed whole prefix material')
        return
    validate_gain_source(registry,source)
    if template.prefix.timing!='battlecry' or template.prefix.before_behavior_id is not None:
        raise ValueError('Corpse material changed the actual native Battlecry prefix')


def assembled_gain_ids(registry,card_id):
    from .assemble_faces import recipe_from_id,text_source
    recipe=recipe_from_id(card_id)
    prefix_id=recipe.secondary_card_id if recipe.half=='top'else recipe.primary_card_id
    template=text_source(registry,prefix_id,primary=recipe.half!='top')
    validate_gain_prefix(registry,template)
    return (prefix_id,)if prefix_id in registry._assemble_corpse_gain_sources else ()


@dataclass(frozen=True)
class AssemblePaidBattlecrySource:
    card_id: str
    original_battlecry_id: str
    pool_id: str
    query: PoolQuery

    def __post_init__(self):
        from .assemble_faces import TIMING_PREFIXES
        for field in('card_id','original_battlecry_id','pool_id'):_name(getattr(self,field),'paid prefix '+field)
        if (self.card_id.startswith('assemble:')or self.original_battlecry_id.startswith(TIMING_PREFIXES)or
                type(self.query) is not PoolQuery or self.query!=PoolQuery(collectible=True,runes_any=('blood',))):
            raise ValueError('Paid prefix requires the actual one-corpse Blood discovery program')


def validate_paid_source(registry,source,*,require_template=False):
    if type(source) is not AssemblePaidBattlecrySource:raise ValueError('Expected native paid Battlecry source')
    source.__post_init__();original=registry._cards.get(source.card_id)
    if original is None or original.kind!=CardType.MINION or original.battlecry!=source.original_battlecry_id:
        raise ValueError('Paid prefix changed its whole original Battlecry')
    registry.behavior(source.original_battlecry_id)
    template=registry._assemble_templates.get(source.card_id)
    if require_template and template is None:raise ValueError('Paid prefix lacks its original template')
    if template is not None:validate_paid_prefix(template,source)


def validate_paid_prefix(template,source):
    if (template.prefix.timing!='battlecry'or template.prefix.condition_id is not None or
            template.prefix.before_behavior_id!=source.original_battlecry_id or
            template.original_battlecry_id!=source.original_battlecry_id):
        raise ValueError('Paid prefix changed its original native declaration')


def native_battlecry(registry,template,suffix):
    source=registry._assemble_paid_battlecry_sources.get(template.card_id)
    if source is None:
        if any(p.original_battlecry_id==template.prefix.before_behavior_id
                for p in registry._assemble_paid_battlecry_sources.values()):
            raise ValueError('Paid prefix borrowed another original source')
        return None
    validate_paid_source(registry,source);validate_paid_prefix(template,source)
    return source.original_battlecry_id if suffix==template.suffix else None


@dataclass(frozen=True)
class AssemblePaidBattlecryContinuation:
    accepted: RuleContext
    before_behavior_id: str
    behavior_id: str
    payment_id: int|None=None

    def __post_init__(self):
        if (type(self.accepted)is not RuleContext or self.accepted.battlecry is None or
                self.accepted.paid_battlecry_followup is not None or self.accepted.deathrattle_followup is not None):
            raise ValueError('Paid continuation requires one original Battlecry acceptance')
        _name(self.before_behavior_id,'original paid program');_name(self.behavior_id,'selected paid suffix')
        _optional_id(self.payment_id,'original corpse payment')


def validate_material(registry,material):
    if type(material)is not AssemblePaidBattlecryContinuation:raise ValueError('Expected paid Battlecry continuation')
    material.__post_init__();origin=material.accepted;record=origin.battlecry
    from .battlecries import validate_record
    from .assemble_faces import recipe_from_id,before_behavior_id
    validate_record(origin.state,registry,record)
    declaration=record.payload.card_id or record.card_id;recipe=recipe_from_id(declaration)
    prefix_id=recipe.secondary_card_id if recipe.half=='top'else recipe.primary_card_id
    source=registry._assemble_paid_battlecry_sources.get(prefix_id)
    if source is None or source.original_battlecry_id!=material.before_behavior_id:
        raise ValueError('Paid continuation changed its original source program')
    validate_paid_source(registry,source,require_template=True)
    identity=before_behavior_id(material.before_behavior_id,material.behavior_id)
    if ((origin.source_id,origin.player_id,origin.target_id)!=(record.source_id,record.player_id,record.target_id)or
            record.payload.behavior_id!=identity or registry.card(declaration).battlecry!=identity):
        raise ValueError('Paid continuation changed its original complete face or target')
    registry.behavior(material.behavior_id)
    return source


def validate_running(state,registry,material,*,require_payment=False):
    validate_material(registry,material)
    from .battlecries import battlecry_record,validate_record
    origin=material.accepted;current=battlecry_record(state,origin.battlecry.id);validate_record(state,registry,current)
    if (current.completed or current.interrupted or current.failure is not None or
            (current.source_id,current.player_id,current.payload)!=(origin.source_id,origin.player_id,origin.battlecry.payload)):
        raise ValueError('Paid continuation requires its still-running original Battlecry')
    if require_payment and material.payment_id is None:raise ValueError('Paid suffix lacks its actual successful payment')
    if material.payment_id is not None:
        if not len(origin.state.corpse_spend_history)<material.payment_id<=len(state.corpse_spend_history):
            raise ValueError('Paid suffix borrowed a missing, old or future debit')
        row=state.corpse_spend_history[material.payment_id-1]
        if (row.id,row.player_id,row.amount,row.origin,row.source_id,row.source_card_id,row.operation_id)!=(
                material.payment_id,origin.player_id,1,'fixed',None,None,None):
            raise ValueError('Paid suffix changed its original one-corpse fixed debit')
    return current


@dataclass(frozen=True)
class ContinueAssembledPaidBattlecry(Effect):
    continuation: AssemblePaidBattlecryContinuation

    def __post_init__(self):
        if type(self.continuation)is not AssemblePaidBattlecryContinuation:raise ValueError('Expected typed paid continuation')
        self.continuation.__post_init__()

    def validate_in_state(self,state,registry):
        self.__post_init__();validate_running(state,registry,self.continuation)


def selected_request(registry,context,before_id,body_id):
    found=[s for s in registry._assemble_paid_battlecry_sources.values()if s.original_battlecry_id==before_id]
    if not found:return None
    source,=found;material=AssemblePaidBattlecryContinuation(context,before_id,body_id)
    validate_material(registry,material)
    discovery=DiscoverFromPool(context.player_id,source.pool_id,source.query,source_id=context.source_id)
    expected=SpendResource(context.player_id,Resource.CORPSES,1,on_success=(discovery,))
    planned=registry.behavior(before_id)(context)
    if planned!=(expected,):raise ResolutionError('Paid prefix changed its complete native payment or discovery')
    return (replace(expected,on_success=(ContinueAssembledPaidBattlecry(material),)),)


def bind_success(state,registry,effect,row):
    branches=effect.on_success
    if not any(type(e)is ContinueAssembledPaidBattlecry for e in branches):return branches
    if (len(branches)!=1 or effect!=SpendResource(effect.player_id,Resource.CORPSES,1,on_success=branches)or
            branches[0].continuation.payment_id is not None):
        raise ValueError('Paid continuation requires exactly its original unbound resource branch')
    material=replace(branches[0].continuation,payment_id=row.id)
    validate_running(state,registry,material,require_payment=True)
    return (ContinueAssembledPaidBattlecry(material),)


def validate_context(context,registry):
    material=context.paid_battlecry_followup
    current=validate_running(context.state,registry,material,require_payment=True);origin=material.accepted
    if ((context.source_id,context.player_id,context.target_id,context.battlecry)!=(
            origin.source_id,origin.player_id,origin.target_id,current)):
        raise ValueError('Paid context changed its actual original root, player or target')


def validate_call(call,registry):
    if call.context.paid_battlecry_followup is not None:
        validate_context(call.context,registry)
        if call.behavior_id!=call.context.paid_battlecry_followup.behavior_id:
            raise ValueError('Paid callback changed its selected suffix')


def continue_paid(r,effect):
    effect.validate_in_state(r.state,r.registry);material=effect.continuation
    current=validate_running(r.state,r.registry,material,require_payment=True);origin=material.accepted
    call=r.call(material.behavior_id,origin.source_id,origin.player_id,target_id=origin.target_id,
        battlecry=current,paid_battlecry_followup=material)
    return (call,)


def validate_sources(registry):
    for cid,s in registry._assemble_corpse_gain_sources.items():
        validate_gain_source(registry,s,require_template=True);validate_gain_prefix(registry,registry._assemble_templates[cid])
        if cid!=s.card_id:raise ValueError('Renamed corpse prefix material')
    seen=set()
    for cid,s in registry._assemble_paid_battlecry_sources.items():
        validate_paid_source(registry,s,require_template=True)
        if cid!=s.card_id or s.original_battlecry_id in seen:raise ValueError('Duplicate original paid prefix')
        seen.add(s.original_battlecry_id)


def register(mechanics):
    mechanics.register_payload_type(AssemblePaidBattlecryContinuation)
    mechanics.register(ContinueAssembledPaidBattlecry,continue_paid)
