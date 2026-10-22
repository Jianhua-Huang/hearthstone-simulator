"""Reviewed text halves resolve to immutable native faces without registry mutation.

This layer does not choose candidates or authorize source-specific offers. Card
identities carry a canonical recipe; frozen declarations bind its semantics.
"""
from collections.abc import Mapping
from dataclasses import asdict,dataclass,fields,replace
import base64
import binascii
import json

from .model import CardDefinition,CardType,EndTurnSpec,HandActionSpec,Keyword,TargetSpec,TriggerSpec,_bool,_name,_int
from .effects import Effect
from .serialization import canonical_hash
from .assemble_reactions import REACTION_PREFIX, REACTION_TIMINGS, reaction_behavior_id

PREFIX='assemble:'
VERSION='assemble-face-v1'
TIMINGS=frozenset(('battlecry','deathrattle','end_turn','start_turn'))|REACTION_TIMINGS
DUAL_TIMING='battlecry_deathrattle'
PREFIX_TIMINGS=TIMINGS|{DUAL_TIMING}
OWNER_START_PREFIX='assemble.owner_start:'
CONDITION_PREFIX='assemble.condition:'
INNER_CONDITION_PREFIX='assemble.condition_inner:'
BEFORE_PREFIX='assemble.before:'
TIMING_PREFIXES=(OWNER_START_PREFIX,CONDITION_PREFIX,BEFORE_PREFIX,INNER_CONDITION_PREFIX,REACTION_PREFIX)
BASIC_KEYWORDS=frozenset((Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.CHARGE,Keyword.RUSH,
    Keyword.WINDFURY,Keyword.MEGA_WINDFURY,Keyword.POISONOUS,Keyword.LIFESTEAL,Keyword.STEALTH,Keyword.ELUSIVE,
    Keyword.REBORN))
SOURCE_FIELDS=frozenset(('id','name','kind','cost','attack','health','metadata','keywords',
    'battlecry','deathrattle','triggers','requires_target','targeting','target_rule','spell_damage','hand_actions'))

@dataclass(frozen=True)
class AssemblePrefix:
    timing: str
    keywords: tuple[Keyword,...]=()
    end_turn: EndTurnSpec|None=None
    spell_damage: int=0
    condition_id: str|None=None
    hand_actions: tuple[HandActionSpec,...]=()
    before_behavior_id: str|None=None

    def __post_init__(self):
        if type(self.timing)is not str or self.timing not in PREFIX_TIMINGS:
            raise ValueError('Unsupported assembled text prefix timing')
        if (type(self.keywords)is not tuple or any(type(k)is not Keyword or k not in BASIC_KEYWORDS for k in self.keywords)
                or len(set(self.keywords))!=len(self.keywords)):
            raise ValueError('Assembled prefix requires unique supported native keywords')
        if self.timing=='end_turn':
            if type(self.end_turn)is not EndTurnSpec:raise ValueError('End-turn prefix requires its explicit native policy')
            self.end_turn.__post_init__()
        elif self.end_turn is not None:
            raise ValueError('Only end-turn text has an end-turn policy')
        _int(self.spell_damage,'assembled printed spell damage',0)
        if self.condition_id is not None:
            _name(self.condition_id,'assembled prefix condition')
            if self.timing not in ('battlecry','end_turn') and self.timing not in REACTION_TIMINGS:
                raise ValueError('Conditional assembly prefix requires its reviewed native Battlecry or end-turn window')
        if self.timing in REACTION_TIMINGS and self.condition_id is None:
            raise ValueError('Reaction prefix requires its actual reviewed native condition')
        if self.before_behavior_id is not None:
            _name(self.before_behavior_id,'assembled prefix body')
            if (self.timing not in ('battlecry','deathrattle') or self.condition_id is not None or
                    self.before_behavior_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Assembly prefix body requires its reviewed native Battlecry or Deathrattle window')
        if type(self.hand_actions)is not tuple or len(self.hand_actions)>1:
            raise ValueError('Assembly prefix requires one reviewed ordinary hand action or none')
        for spec in self.hand_actions:
            if type(spec)is not HandActionSpec:raise ValueError('Assembly hand action requires its immutable native declaration')
            spec.__post_init__()
            if (spec.id,spec.kind,spec.cost,spec.upgrade_card_id,spec.on_use,spec.use_rule) not in (
                    ('trade','trade',1,None,None,'always'),('prepare','prepare',1,None,None,'always')):
                raise ValueError('Assembly only reviewed ordinary one-fee Trade or Prepare prefixes')

@dataclass(frozen=True)
class AssembleSuffix:
    behavior_id: str
    allowed_timings: tuple[str,...]
    requires_target: bool=False
    targeting: TargetSpec|None=None
    target_rule: str='any_entity'
    deathrattle_behavior_id: str|None=None
    pending_timings: tuple[str,...]=()

    def __post_init__(self):
        _name(self.behavior_id,'assembled suffix behavior');_name(self.target_rule,'assembled suffix target rule')
        if self.behavior_id.startswith(TIMING_PREFIXES):raise ValueError('Assembly suffix cannot recursively wrap a timing gate')
        if (type(self.allowed_timings)is not tuple or not self.allowed_timings or
                any(type(t)is not str or t not in TIMINGS for t in self.allowed_timings) or
                len(set(self.allowed_timings))!=len(self.allowed_timings)):
            raise ValueError('Suffix needs explicit unique reviewed timing compatibility')
        _bool(self.requires_target,'assembled suffix requires_target')
        if self.targeting is not None:
            if type(self.targeting)is not TargetSpec:raise ValueError('Suffix requires typed targeting')
            self.targeting.__post_init__()
        if (self.requires_target or self.targeting is not None) and self.allowed_timings!=('battlecry',):
            raise ValueError('Explicitly selected suffix targets only support a Battlecry prefix')
        if self.deathrattle_behavior_id is not None:
            _name(self.deathrattle_behavior_id,'assembled native Deathrattle body')
            if ('deathrattle'not in self.allowed_timings or
                    self.deathrattle_behavior_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Alternate Deathrattle body requires its reviewed native timing')
        if(type(self.pending_timings)is not tuple or any(type(t)is not str or t not in TIMINGS for t in self.pending_timings)
                or len(set(self.pending_timings))!=len(self.pending_timings)or set(self.pending_timings)&set(self.allowed_timings)):
            raise ValueError('Pending assembly timing needs a distinct explicit unsupported inventory')

@dataclass(frozen=True)
class AssembleTemplate:
    card_id: str
    prefix: AssemblePrefix
    suffix: AssembleSuffix
    original_battlecry_id: str|None=None
    original_start_turn_id: str|None=None
    original_end_turn_id: str|None=None
    original_deathrattle_id: str|None=None

    def __post_init__(self):
        _name(self.card_id,'assembled template source')
        if self.card_id.startswith(PREFIX):raise ValueError('Assembly source must be a static reviewed minion')
        if type(self.prefix)is not AssemblePrefix or type(self.suffix)is not AssembleSuffix:
            raise ValueError('Assembly template requires immutable typed halves')
        self.prefix.__post_init__();self.suffix.__post_init__()
        if self.original_battlecry_id is not None:
            _name(self.original_battlecry_id,'original conditional assembly Battlecry')
            if(self.prefix.timing!='battlecry' or
                    self.prefix.condition_id is None and self.prefix.before_behavior_id is None or
                    self.original_battlecry_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Original Battlecry bridge requires a reviewed native condition or prefix body')
        if self.original_start_turn_id is not None:
            _name(self.original_start_turn_id,'original owner-start assembly trigger')
            if(self.prefix.timing!='start_turn' or
                    self.original_start_turn_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Original owner-start bridge requires its reviewed native start prefix')
        if self.original_end_turn_id is not None:
            _name(self.original_end_turn_id,'original conditional assembly end trigger')
            if(self.prefix.timing!='end_turn' or self.prefix.condition_id is None or
                    self.original_end_turn_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Original end-turn bridge requires its reviewed native conditional prefix')
        if self.original_deathrattle_id is not None:
            _name(self.original_deathrattle_id,'original prefixed assembly Deathrattle')
            if (self.prefix.before_behavior_id is None or self.prefix.timing!='deathrattle' or
                    self.original_deathrattle_id.startswith(TIMING_PREFIXES)):
                raise ValueError('Original Deathrattle bridge requires its reviewed native prefix body')

@dataclass(frozen=True)
class AssembleProjection:
    """Reviewed secondary text from a whole non-minion original.

    A projection supplies text, never a replacement physical source card. The
    original remains executable with its complete independently pinned rules.
    """
    card_id: str
    source_kind: CardType
    definition_sha256: str
    record_sha256: str
    prefix: AssemblePrefix
    suffix: AssembleSuffix

    def __post_init__(self):
        _name(self.card_id,'assembly projection source')
        if self.card_id.startswith(PREFIX) or self.source_kind not in (CardType.SPELL,CardType.WEAPON,CardType.HERO) or type(self.source_kind)is not CardType:
            raise ValueError('Projection requires an original non-minion text source')
        for name in ('definition_sha256','record_sha256'):
            value=getattr(self,name)
            if type(value)is not str or len(value)!=64 or any(c not in '0123456789abcdef'for c in value):
                raise ValueError('Projection requires complete canonical original pins')
        if type(self.prefix)is not AssemblePrefix or type(self.suffix)is not AssembleSuffix:
            raise ValueError('Projection requires reviewed immutable text halves')
        self.prefix.__post_init__();self.suffix.__post_init__()

@dataclass(frozen=True)
class AssembleRecipe:
    primary_card_id: str
    secondary_card_id: str
    half: str
    version: str=VERSION

    def __post_init__(self):
        for n in ('primary_card_id','secondary_card_id'):
            v=getattr(self,n);_name(v,n)
            if v.startswith(PREFIX):raise ValueError('Recursive assembled recipe sources are unsupported')
        if type(self.half)is not str or self.half not in ('top','bottom'):raise ValueError('Select one explicit text half')
        if type(self.version)is not str or self.version!=VERSION:raise ValueError('Unsupported assembly recipe version')

    @property
    def card_id(self):
        self.__post_init__()
        body=json.dumps(asdict(self),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        result=PREFIX+base64.urlsafe_b64encode(body).decode().rstrip('=')
        if len(result)>8192:raise ValueError('Assembly identity exceeds its bounded recipe size')
        return result

def recipe_from_id(card_id):
    if type(card_id)is not str or not card_id.startswith(PREFIX) or len(card_id)>8192:
        raise ValueError('Invalid assembly identity')
    token=card_id[len(PREFIX):]
    try:
        body=base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True)
        row=json.loads(body.decode('utf-8'))
    except (ValueError,UnicodeError,binascii.Error) as exc:
        raise ValueError('Invalid assembly identity encoding') from exc
    if type(row)is not dict or set(row)!={'primary_card_id','secondary_card_id','half','version'}:
        raise ValueError('Assembly identity requires the complete recipe')
    recipe=AssembleRecipe(**row)
    if recipe.card_id!=card_id:raise ValueError('Assembly identity is not canonical')
    return recipe

def prefix_timings(prefix):
    prefix.__post_init__()
    return ('battlecry','deathrattle')if prefix.timing==DUAL_TIMING else(prefix.timing,)


def compatible(prefix,suffix):
    suffix.__post_init__()
    timings=prefix_timings(prefix)
    if prefix.timing in REACTION_TIMINGS and prefix.timing not in suffix.allowed_timings:
        raise ValueError('Eligible reaction body context remains explicitly unimplemented: '+prefix.timing)
    if any(t in suffix.pending_timings for t in timings):
        raise ValueError('Eligible assembly timing remains explicitly unimplemented: '+','.join(timings))
    if prefix.condition_id is not None and(suffix.requires_target or suffix.targeting is not None):
        raise ValueError('Eligible conditional assembly arrow requires its explicit targeting acceptance contract')
    return all(t in suffix.allowed_timings for t in timings)


def printed_face(primary,prefix,suffix,card_id):
    prefix.__post_init__();suffix.__post_init__()
    if not compatible(prefix,suffix):raise ValueError('Unreviewed prefix/suffix compatibility')
    timings=prefix_timings(prefix)
    battlecry=(condition_behavior_id(prefix.condition_id,suffix.behavior_id)if prefix.condition_id is not None
        else suffix.behavior_id)if 'battlecry'in timings else None
    deathrattle=suffix.deathrattle_behavior_id or suffix.behavior_id
    if prefix.before_behavior_id is not None:
        if 'battlecry'in timings:battlecry=before_behavior_id(prefix.before_behavior_id,battlecry)
        if 'deathrattle'in timings:deathrattle=before_behavior_id(prefix.before_behavior_id,deathrattle)
    return replace(primary,id=card_id,keywords=prefix.keywords,spell_damage=prefix.spell_damage,hand_actions=prefix.hand_actions,
        battlecry=battlecry,
        deathrattle=deathrattle if 'deathrattle'in timings else None,
        triggers=((TriggerSpec('turn_ended',condition_behavior_id(prefix.condition_id,suffix.behavior_id)
            if prefix.condition_id is not None else suffix.behavior_id,prefix.end_turn),) if prefix.timing=='end_turn' else
            (TriggerSpec('turn_started',OWNER_START_PREFIX+suffix.behavior_id),) if prefix.timing=='start_turn' else
            (TriggerSpec(prefix.timing,reaction_behavior_id(prefix.timing,prefix.condition_id,suffix.behavior_id)),)
                if prefix.timing in REACTION_TIMINGS else ()),
        requires_target=suffix.requires_target if 'battlecry'in timings else False,
        targeting=suffix.targeting if 'battlecry'in timings else None,
        target_rule=suffix.target_rule if 'battlecry'in timings else 'any_entity')

def validate_template(registry,template):
    template.__post_init__()
    primary=registry._cards.get(template.card_id)
    if primary is None or primary.kind!=CardType.MINION:
        raise ValueError('Assembly template needs an executable static minion')
    default=CardDefinition(primary.id,primary.name,CardType.MINION)
    if any(getattr(primary,f.name)!=getattr(default,f.name)for f in fields(CardDefinition)if f.name not in SOURCE_FIELDS):
        raise ValueError('Assembly template has unreviewed text or declaration fields')
    registry.behavior(template.suffix.behavior_id)
    if template.suffix.deathrattle_behavior_id is not None:
        registry.behavior(template.suffix.deathrattle_behavior_id)
    if template.prefix.condition_id is not None:registry.trigger_condition(template.prefix.condition_id)
    if template.prefix.before_behavior_id is not None:registry.behavior(template.prefix.before_behavior_id)
    if template.suffix.requires_target or template.suffix.targeting is not None:
        registry.target_rule(template.suffix.target_rule)
    if template.prefix.end_turn is not None:registry.trigger_condition(template.prefix.end_turn.condition_id)
    original=printed_face(primary,template.prefix,template.suffix,primary.id)
    if template.prefix.timing in REACTION_TIMINGS:
        from .assemble_reactions import original_trigger
        original=replace(original,triggers=original_trigger(registry,template))
    elif template.card_id in registry._assemble_reaction_sources:
        raise ValueError('Reaction source bridge cannot mask another prefix timing')
    if template.original_battlecry_id is not None:
        registry.behavior(template.original_battlecry_id)
        if primary.battlecry!=template.original_battlecry_id:
            raise ValueError('Conditional assembly changed its exact original Battlecry identity')
        original=replace(original,battlecry=template.original_battlecry_id)
    if template.original_deathrattle_id is not None:
        registry.behavior(template.original_deathrattle_id)
        if primary.deathrattle!=template.original_deathrattle_id:
            raise ValueError('Prefixed assembly changed its exact original Deathrattle identity')
        original=replace(original,deathrattle=template.original_deathrattle_id)
    if template.original_start_turn_id is not None:
        registry.behavior(template.original_start_turn_id)
        declared=(TriggerSpec('turn_started',template.original_start_turn_id),)
        if primary.triggers!=declared:
            raise ValueError('Owner-start assembly changed its exact complete original trigger identity')
        original=replace(original,triggers=declared)
    if template.original_end_turn_id is not None:
        registry.behavior(template.original_end_turn_id)
        declared=(TriggerSpec('turn_ended',template.original_end_turn_id,template.prefix.end_turn),)
        if primary.triggers!=declared:
            raise ValueError('Conditional assembly changed its exact complete original end-turn trigger identity')
        original=replace(original,triggers=declared)
    if original!=primary:raise ValueError('Reviewed halves do not reconstruct the complete original minion')
    registry._validate_card(original)

def validate_projection(registry,projection):
    if projection.prefix.timing in REACTION_TIMINGS:
        raise ValueError('Reaction prefix requires its actual native minion source')
    projection.__post_init__()
    source=registry._cards.get(projection.card_id)
    if (source is None or source.kind!=projection.source_kind or source.choice_only or not source.hand_playable or
            canonical_hash(asdict(source))!=projection.definition_sha256):
        raise ValueError('Assembly projection changed its complete original definition')
    registry.behavior(projection.suffix.behavior_id)
    if projection.suffix.deathrattle_behavior_id is not None:
        registry.behavior(projection.suffix.deathrattle_behavior_id)
    if projection.prefix.condition_id is not None:registry.trigger_condition(projection.prefix.condition_id)
    if projection.prefix.before_behavior_id is not None:registry.behavior(projection.prefix.before_behavior_id)
    if projection.suffix.behavior_id.startswith(OWNER_START_PREFIX):
        raise ValueError('Projection payload cannot recursively wrap an owner-start gate')
    if projection.suffix.requires_target or projection.suffix.targeting is not None:
        registry.target_rule(projection.suffix.target_rule)
    if projection.prefix.end_turn is not None:registry.trigger_condition(projection.prefix.end_turn.condition_id)

def text_source(registry,card_id,*,primary=False):
    source=registry._assemble_templates.get(card_id)
    if source is not None:
        validate_template(registry,source)
        return source
    if not primary:
        source=registry._assemble_projections.get(card_id)
        if source is not None:
            validate_projection(registry,source)
            return source
    raise ValueError('Eligible assembly source lacks reviewed '+('primary minion'if primary else 'text halves')+': '+card_id)

def owner_start_behavior(registry,behavior_id):
    """Pure derived wrapper; accepted native contexts retain their original body.

    The body identity lives in the printed trigger, so a later transform or a
    copied listener cannot redirect it through a carrier's current card face.
    """
    from .registry import UnsupportedDefinitionError
    payload=behavior_id[len(OWNER_START_PREFIX):]
    sources=(*registry._assemble_templates.values(),*registry._assemble_projections.values())
    if payload.startswith(OWNER_START_PREFIX) or not any(
            s.suffix.behavior_id==payload and 'start_turn'in s.suffix.allowed_timings for s in sources):
        raise UnsupportedDefinitionError('Unreviewed assembled owner-start body: '+payload)
    body=registry.behavior(payload)
    def run(context):
        if context.event is None or context.event.kind!='turn_started':
            raise ValueError('Assembled owner-start body requires its accepted native turn boundary')
        return body(context)if context.event.player_id==context.player_id else ()
    return run


def condition_behavior_id(condition_id,behavior_id):
    _name(condition_id,'assembled condition identity');_name(behavior_id,'assembled conditional payload')
    if behavior_id.startswith(TIMING_PREFIXES):
        raise ValueError('Conditional assembly cannot recursively wrap a timing gate')
    body=json.dumps(dict(condition_id=condition_id,behavior_id=behavior_id),sort_keys=True,separators=(',',':')).encode()
    result=CONDITION_PREFIX+base64.urlsafe_b64encode(body).decode().rstrip('=')
    if len(result)>8192:raise ValueError('Conditional assembly identity exceeds bounded size')
    return result


def before_behavior_id(before_behavior_id,behavior_id):
    _name(before_behavior_id,'assembled prefix body');_name(behavior_id,'assembled suffix body')
    if any(value.startswith(TIMING_PREFIXES)for value in (before_behavior_id,behavior_id)):
        raise ValueError('Assembly prefix sequence cannot recursively wrap a timing gate')
    row=dict(before_behavior_id=before_behavior_id,behavior_id=behavior_id)
    body=json.dumps(row,sort_keys=True,separators=(',',':')).encode()
    result=BEFORE_PREFIX+base64.urlsafe_b64encode(body).decode().rstrip('=')
    if len(result)>8192:raise ValueError('Assembly prefix sequence exceeds bounded size')
    return result


def before_behavior(registry,behavior_id):
    """Preserve each reviewed native sequence inside one original activation."""
    from .registry import UnsupportedDefinitionError
    try:
        if len(behavior_id)>8192:raise ValueError('Oversized prefix sequence identity')
        token=behavior_id[len(BEFORE_PREFIX):]
        row=json.loads(base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True).decode())
        if (type(row)is not dict or set(row)!={'before_behavior_id','behavior_id'}or
                before_behavior_id(**row)!=behavior_id):
            raise ValueError('Noncanonical prefix sequence identity')
        sources=(*registry._assemble_templates.values(),*registry._assemble_projections.values())
        timings={s.prefix.timing for s in sources if s.prefix.before_behavior_id==row['before_behavior_id']} & {
            timing for s in sources for timing in s.suffix.allowed_timings if
            ((s.suffix.deathrattle_behavior_id or s.suffix.behavior_id)if timing=='deathrattle'
                else s.suffix.behavior_id)==row['behavior_id']}
        if not timings:
            raise ValueError('Unreviewed prefix sequence or native suffix timing')
        first=registry.behavior(row['before_behavior_id']);second=registry.behavior(row['behavior_id'])
    except(ValueError,TypeError,UnicodeError,binascii.Error)as exc:
        raise UnsupportedDefinitionError('Unsupported assembled prefix sequence: '+str(exc))from exc
    def run(context):
        if ('battlecry'in timings and context.battlecry is not None and
                context.battlecry.payload.behavior_id==behavior_id and
                (context.battlecry.source_id,context.battlecry.player_id)==(context.source_id,context.player_id)):
            from .battlecries import validate_record
            from .effects import InvokeBehavior
            validate_record(context.state,registry,context.battlecry)
            prefix_effects=first(context)
            # The native draw-before-buff sequence plans its suffix after Draw
            # and its reactions, so newly drawn cards enter the actual query.
            return (*(()if prefix_effects is None else prefix_effects),InvokeBehavior(
                row['behavior_id'],context.source_id,context.player_id,context.target_id,
                None if context.play is None else context.play.id))
        if ('deathrattle'in timings and context.deathrattle is not None and
                context.deathrattle.ability.behavior_id==behavior_id):
            from .deathrattles import validate_context
            validate_context(context,registry)
            prefix_effects=first(context);suffix_effects=second(context)
            return (*(()if prefix_effects is None else prefix_effects),*(()if suffix_effects is None else suffix_effects))
        native='Battlecry'if timings=={'battlecry'}else'Deathrattle'if timings=={'deathrattle'}else'Battlecry or Deathrattle'
        raise ValueError('Assembly prefix sequence requires its original native '+native+' context')
    return run


def conditional_parts(registry,behavior_id):
    from .registry import UnsupportedDefinitionError
    try:
        if len(behavior_id)>8192:raise ValueError('Oversized conditional identity')
        token=behavior_id[len(CONDITION_PREFIX):]
        row=json.loads(base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True).decode())
        if type(row)is not dict or set(row)!={'condition_id','behavior_id'}or condition_behavior_id(**row)!=behavior_id:
            raise ValueError('Noncanonical conditional identity')
        sources=(*registry._assemble_templates.values(),*registry._assemble_projections.values())
        timings={s.prefix.timing for s in sources if s.prefix.condition_id==row['condition_id']} & {
            t for s in sources if s.suffix.behavior_id==row['behavior_id'] for t in s.suffix.allowed_timings}
        if not timings:
            raise ValueError('Unreviewed assembly condition or payload')
        predicate=registry.trigger_condition(row['condition_id']);body=registry.behavior(row['behavior_id'])
    except(ValueError,TypeError,UnicodeError,binascii.Error)as exc:
        raise UnsupportedDefinitionError('Unsupported assembled conditional body: '+str(exc))from exc
    return row,predicate,body,frozenset(timings)


def conditional_behavior(registry,behavior_id):
    row,predicate,body,timings=conditional_parts(registry,behavior_id)
    def run(context):
        if ('battlecry'in timings and context.battlecry is not None and
                context.battlecry.payload.behavior_id==behavior_id):
            if row['condition_id'] in registry.assemble_inner_conditions:
                from .effects import InvokeBehavior
                return (InvokeBehavior(inner_condition_behavior_id(row['condition_id'],
                    row['behavior_id'], context.battlecry.id), context.source_id,
                    context.player_id, context.target_id,
                    None if context.play is None else context.play.id),)
            result=predicate(context)
            if type(result)is not bool:raise ValueError('Assembly condition requires an explicit boolean')
            return body(context)if result else()
        if ('end_turn'in timings and context.end_turn is not None and
                context.end_turn.subject.behavior_id==behavior_id):
            from .end_turns import validate_context
            validate_context(context,registry)
            return (CheckAssembledEndCondition(context.end_turn.id,context.source_id,context.player_id,
                row['condition_id'],row['behavior_id']),)
        raise ValueError('Conditional assembly requires its original native Battlecry or end-turn context')
    return run


def inner_condition_behavior_id(condition_id, behavior_id, battlecry_id):
    # The continuation carries its exact already accepted activation, rather
    # than selecting whichever incomplete Battlecry happens to be nearest.
    condition_behavior_id(condition_id, behavior_id)
    _int(battlecry_id, 'assembled inner condition Battlecry', 1)
    row = dict(condition_id=condition_id, behavior_id=behavior_id, battlecry_id=battlecry_id)
    body = json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
    result = INNER_CONDITION_PREFIX + base64.urlsafe_b64encode(body).decode().rstrip('=')
    if len(result) > 8192:
        raise ValueError('Assembled inner condition identity exceeds bounded size')
    return result


def inner_condition_behavior(registry, behavior_id):
    """Use the ordinary fresh InvokeBehavior view, retaining the native root."""
    from .registry import UnsupportedDefinitionError
    try:
        if not behavior_id.startswith(INNER_CONDITION_PREFIX) or len(behavior_id) > 8192:
            raise ValueError('Invalid assembled inner condition identity')
        token = behavior_id[len(INNER_CONDITION_PREFIX):]
        row = json.loads(base64.b64decode(token + '=' * (-len(token) % 4),
            altchars=b'-_', validate=True).decode())
        if (type(row) is not dict or set(row) != {'condition_id', 'behavior_id', 'battlecry_id'} or
                inner_condition_behavior_id(**row) != behavior_id):
            raise ValueError('Noncanonical assembled inner condition identity')
        outer = condition_behavior_id(row['condition_id'], row['behavior_id'])
        _, predicate, body, timings = conditional_parts(registry, outer)
        if 'battlecry' not in timings or row['condition_id'] not in registry.assemble_inner_conditions:
            raise ValueError('Unreviewed assembled inner condition window')
    except (ValueError, TypeError, UnicodeError, binascii.Error) as exc:
        raise UnsupportedDefinitionError('Unsupported assembled inner condition: ' + str(exc)) from exc

    def run(context):
        from .battlecries import battlecry_record, validate_record
        record = battlecry_record(context.state, row['battlecry_id'])
        if (context.battlecry != record or record.completed or record.interrupted or
                record.failure is not None or record.payload.behavior_id != outer or
                (record.source_id, record.player_id, record.target_id) !=
                (context.source_id, context.player_id, context.target_id)):
            raise ValueError('Assembled inner condition differs from its accepted Battlecry')
        validate_record(context.state, registry, record)
        result = predicate(context)
        if type(result) is not bool:
            raise ValueError('Assembly condition requires an explicit boolean')
        return body(context) if result else ()
    return run


@dataclass(frozen=True)
class CheckAssembledEndCondition(Effect):
    """Read the live inner-call view, bound to the already accepted end subject."""
    activation_id: int
    source_id: int
    player_id: int
    condition_id: str
    behavior_id: str

    def __post_init__(self):
        _int(self.activation_id,'assembled end activation',1)
        _int(self.source_id,'assembled end source',1)
        if type(self.player_id)is not int or self.player_id not in (1,2):
            raise ValueError('Assembled end condition requires its accepted player')
        condition_behavior_id(self.condition_id,self.behavior_id)

    def validate_in_state(self,state,registry):
        from .end_turns import record,running_parent
        self.__post_init__()
        saved=record(state,self.activation_id);subject=saved.capture.subject
        bid=condition_behavior_id(self.condition_id,self.behavior_id)
        if (saved.execution_order is None or saved.completed or saved.interrupted or saved.skipped or
                running_parent(state)!=self.activation_id or self.source_id not in state.entities or
                (subject.source_id,subject.player_id,subject.behavior_id)!=(self.source_id,self.player_id,bid)):
            raise ValueError('Assembled end condition differs from its running accepted subject')
        if 'end_turn'not in conditional_parts(registry,bid)[3]:
            raise ValueError('Assembled condition lacks its reviewed end-turn window')


def check_end_condition(resolver,effect):
    effect.validate_in_state(resolver.state,resolver.registry)
    bid=condition_behavior_id(effect.condition_id,effect.behavior_id)
    predicate=conditional_parts(resolver.registry,bid)[1]
    # Match the original InvokeBehavior boundary, without manufacturing a new
    # EndTurnCapture in this fresh view or moving the check to early acceptance.
    call=resolver.call(effect.behavior_id,effect.source_id,effect.player_id)
    result=predicate(call.context)
    if type(result)is not bool:raise ValueError('Assembly condition requires an explicit boolean')
    return [call]if result else []

def validate_templates(registry):
    from .assemble_reactions import validate_sources
    validate_sources(registry)
    for condition_id in registry._assemble_inner_conditions:
        registry.trigger_condition(condition_id)
        if not any(template.prefix.timing == 'battlecry' and
                template.prefix.condition_id == condition_id
                for template in (*registry._assemble_templates.values(), *registry._assemble_projections.values())):
            raise ValueError('Assembled inner condition requires its actual reviewed Battlecry prefix')
    for cid,template in registry._assemble_templates.items():
        if type(template)is not AssembleTemplate or cid!=template.card_id:raise ValueError('Invalid assembly template identity')
        validate_template(registry,template)
    for cid,projection in registry._assemble_projections.items():
        if type(projection)is not AssembleProjection or cid!=projection.card_id or cid in registry._assemble_templates:
            raise ValueError('Invalid or overlapping assembly text projection')
        validate_projection(registry,projection)
    if any(cid.startswith(PREFIX)for cid in registry._cards):raise ValueError('Assembly namespace cannot contain registered substitutes')

def resolve_face(registry,card_id):
    from .registry import UnsupportedDefinitionError
    try:
        recipe=recipe_from_id(card_id)
        first=text_source(registry,recipe.primary_card_id,primary=True);second=text_source(registry,recipe.secondary_card_id)
        prefix=second.prefix if recipe.half=='top' else first.prefix
        suffix=second.suffix if recipe.half=='bottom' else first.suffix
        face=printed_face(registry._cards[first.card_id],prefix,suffix,card_id)
        registry._validate_card(face)
        return face
    except (ValueError,TypeError,KeyError)as exc:
        raise UnsupportedDefinitionError('Unsupported assembled card definition: '+str(exc)) from exc

class AssembleCardCatalog(Mapping):
    """Static inventory iteration plus pure lookup of implicit recipe identities.

Lookup/membership can resolve a reviewed recipe; iteration and len deliberately
describe only registered static inventory. No query-dependent cache is added.
"""
    def __init__(self,registry):self.registry=registry
    def __iter__(self):return iter(self.registry._cards)
    def __len__(self):return len(self.registry._cards)
    def __getitem__(self,card_id):
        from .registry import UnsupportedDefinitionError
        hash(card_id)  # Match mapping behavior for unhashable caller keys.
        if type(card_id)is not str or not card_id.strip():raise KeyError(card_id)
        try:return self.registry.card(card_id)
        except UnsupportedDefinitionError as exc:raise KeyError(card_id)from exc
