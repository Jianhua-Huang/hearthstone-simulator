"""Reviewed text halves resolve to immutable native faces without registry mutation.

This layer does not choose candidates or authorize source-specific offers. Card
identities carry a canonical recipe; frozen declarations bind its semantics.
"""
from collections.abc import Mapping
from dataclasses import asdict,dataclass,fields,replace
import base64
import binascii
import json

from .model import CardDefinition,CardType,EndTurnSpec,Keyword,TargetSpec,TriggerSpec,_bool,_name
from .serialization import canonical_hash

PREFIX='assemble:'
VERSION='assemble-face-v1'
TIMINGS=frozenset(('battlecry','deathrattle','end_turn','start_turn'))
OWNER_START_PREFIX='assemble.owner_start:'
BASIC_KEYWORDS=frozenset((Keyword.TAUNT,Keyword.DIVINE_SHIELD,Keyword.CHARGE,Keyword.RUSH,
    Keyword.WINDFURY,Keyword.MEGA_WINDFURY,Keyword.POISONOUS,Keyword.LIFESTEAL,Keyword.STEALTH,Keyword.ELUSIVE,
    Keyword.REBORN))
SOURCE_FIELDS=frozenset(('id','name','kind','cost','attack','health','metadata','keywords',
    'battlecry','deathrattle','triggers','requires_target','targeting','target_rule'))

@dataclass(frozen=True)
class AssemblePrefix:
    timing: str
    keywords: tuple[Keyword,...]=()
    end_turn: EndTurnSpec|None=None

    def __post_init__(self):
        if type(self.timing)is not str or self.timing not in TIMINGS:
            raise ValueError('Unsupported assembled text prefix timing')
        if (type(self.keywords)is not tuple or any(type(k)is not Keyword or k not in BASIC_KEYWORDS for k in self.keywords)
                or len(set(self.keywords))!=len(self.keywords)):
            raise ValueError('Assembled prefix requires unique supported native keywords')
        if self.timing=='end_turn':
            if type(self.end_turn)is not EndTurnSpec:raise ValueError('End-turn prefix requires its explicit native policy')
            self.end_turn.__post_init__()
        elif self.end_turn is not None:
            raise ValueError('Only end-turn text has an end-turn policy')

@dataclass(frozen=True)
class AssembleSuffix:
    behavior_id: str
    allowed_timings: tuple[str,...]
    requires_target: bool=False
    targeting: TargetSpec|None=None
    target_rule: str='any_entity'

    def __post_init__(self):
        _name(self.behavior_id,'assembled suffix behavior');_name(self.target_rule,'assembled suffix target rule')
        if self.behavior_id.startswith(OWNER_START_PREFIX):raise ValueError('Assembly suffix cannot recursively wrap a timing gate')
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

@dataclass(frozen=True)
class AssembleTemplate:
    card_id: str
    prefix: AssemblePrefix
    suffix: AssembleSuffix

    def __post_init__(self):
        _name(self.card_id,'assembled template source')
        if self.card_id.startswith(PREFIX):raise ValueError('Assembly source must be a static reviewed minion')
        if type(self.prefix)is not AssemblePrefix or type(self.suffix)is not AssembleSuffix:
            raise ValueError('Assembly template requires immutable typed halves')
        self.prefix.__post_init__();self.suffix.__post_init__()

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

def printed_face(primary,prefix,suffix,card_id):
    prefix.__post_init__();suffix.__post_init__()
    if prefix.timing not in suffix.allowed_timings:raise ValueError('Unreviewed prefix/suffix compatibility')
    return replace(primary,id=card_id,keywords=prefix.keywords,
        battlecry=suffix.behavior_id if prefix.timing=='battlecry' else None,
        deathrattle=suffix.behavior_id if prefix.timing=='deathrattle' else None,
        triggers=((TriggerSpec('turn_ended',suffix.behavior_id,prefix.end_turn),) if prefix.timing=='end_turn' else
            (TriggerSpec('turn_started',OWNER_START_PREFIX+suffix.behavior_id),) if prefix.timing=='start_turn' else ()),
        requires_target=suffix.requires_target if prefix.timing=='battlecry' else False,
        targeting=suffix.targeting if prefix.timing=='battlecry' else None,
        target_rule=suffix.target_rule if prefix.timing=='battlecry' else 'any_entity')

def validate_template(registry,template):
    template.__post_init__()
    primary=registry._cards.get(template.card_id)
    if primary is None or primary.kind!=CardType.MINION:
        raise ValueError('Assembly template needs an executable static minion')
    default=CardDefinition(primary.id,primary.name,CardType.MINION)
    if any(getattr(primary,f.name)!=getattr(default,f.name)for f in fields(CardDefinition)if f.name not in SOURCE_FIELDS):
        raise ValueError('Assembly template has unreviewed text or declaration fields')
    registry.behavior(template.suffix.behavior_id)
    if template.suffix.requires_target or template.suffix.targeting is not None:
        registry.target_rule(template.suffix.target_rule)
    if template.prefix.end_turn is not None:registry.trigger_condition(template.prefix.end_turn.condition_id)
    original=printed_face(primary,template.prefix,template.suffix,primary.id)
    if original!=primary:raise ValueError('Reviewed halves do not reconstruct the complete original minion')
    registry._validate_card(original)

def validate_projection(registry,projection):
    projection.__post_init__()
    source=registry._cards.get(projection.card_id)
    if (source is None or source.kind!=projection.source_kind or source.choice_only or not source.hand_playable or
            canonical_hash(asdict(source))!=projection.definition_sha256):
        raise ValueError('Assembly projection changed its complete original definition')
    registry.behavior(projection.suffix.behavior_id)
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

def validate_templates(registry):
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
