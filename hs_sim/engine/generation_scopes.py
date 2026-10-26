"""Exact source/view coverage for a finite local generation inventory.

An incomplete global domain can expose a complete, explicitly known local view.
Unknown requests are rejected before candidate selection, never returned empty.
Unscoped existing pools retain their original behavior and fingerprints.
"""
from dataclasses import asdict,dataclass
import hashlib
import json

from .model import CardClass,CardType
from .pools import GenerationContext,GenerationPolicy,PoolDefinition,PoolQuery


def pool_digest(pool):
    return hashlib.sha256(json.dumps(asdict(pool),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()


@dataclass(frozen=True)
class GenerationScope:
    id: str
    pool_id: str
    target_id: str
    mode: str
    source_card_id: str
    current_class: CardClass
    query: PoolQuery
    inventory_sha256: str
    policy: GenerationPolicy = GenerationPolicy()

    def __post_init__(self):
        from .construction import name
        for n in ('id','pool_id','source_card_id'):name(getattr(self,n),'generation scope '+n)
        GenerationContext(self.target_id,self.mode)
        if type(self.current_class)is not CardClass or self.current_class==CardClass.NEUTRAL:
            raise ValueError('Generation coverage requires its actual playable class view')
        if type(self.query)is not PoolQuery or type(self.policy)is not GenerationPolicy:
            raise ValueError('Generation coverage requires its exact original query and policy')
        self.query.__post_init__();self.policy.__post_init__()
        if (type(self.inventory_sha256)is not str or len(self.inventory_sha256)!=64 or
                any(c not in '0123456789abcdef'for c in self.inventory_sha256)):
            raise ValueError('Generation scope requires its full original inventory digest')

    @property
    def pool_key(self):return self.pool_id,self.target_id,self.mode


def validate_scope(registry,scope):
    if type(scope)is not GenerationScope:raise ValueError('Typed generation coverage required')
    scope.__post_init__();pool=registry.pool(scope.pool_id,GenerationContext(scope.target_id,scope.mode))
    if type(pool)is not PoolDefinition or not pool.complete or pool_digest(pool)!=scope.inventory_sha256:
        raise ValueError('Generation coverage borrowed or changed its complete original inventory')
    if registry.card(scope.source_card_id).kind not in (CardType.MINION,CardType.SPELL):
        raise ValueError('Generation coverage requires its actual native source identity')


def require_scope(registry,pool,query,*,current_class,source_card_id,policy,exclude_source_by_rule):
    scopes=tuple(s for s in registry.generation_scopes.values()if s.pool_key==pool.key)
    if not scopes:return
    # Trusted pure inventory inspection may omit a source; actual generation
    # always sets exclude_source_by_rule=True and requires its native producer.
    for scope in scopes:
        if (scope.query==query and scope.current_class==current_class and scope.policy==policy and
                (scope.source_card_id==source_card_id or source_card_id is None and not exclude_source_by_rule)):
            return
    from .registry import UnsupportedDefinitionError
    raise UnsupportedDefinitionError('Unreviewed generation scope: '+pool.id+'; source='+str(source_card_id)+'; class='+str(current_class))


def accepted_source_card(r,effect,current_card_id):
    """Typed accepted teaching keeps its original creator through transformation.

    The original memory target already binds the native Battlecry, physical
    student and recipient. Do not infer provenance from a similarly named card
    or borrow any unrelated historical Battlecry belonging to this entity.
    """
    if not r.registry.generation_scopes or type(r.game._generation_context)is not GenerationContext:return current_card_id
    key=(effect.pool_id,r.game._generation_context.target_id,r.game._generation_context.mode)
    if not any(s.pool_key==key for s in r.registry.generation_scopes.values()):return current_card_id
    from .student_teaching import StudentTeachingTarget,validate_target
    if type(getattr(effect,'memory_target',None))is StudentTeachingTarget:
        return validate_target(r.state,r.registry,effect,active=False).payload.card_id
    return current_card_id
