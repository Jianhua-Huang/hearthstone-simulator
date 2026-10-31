"""A complete named spell recipe reuses ordinary discovery and hand delivery."""
from dataclasses import fields
from .model import CardType
from .construction import ids

POOL='named.fixed.cards'


def validate_spec(spec):
    from .pools import DiscoverFromPool
    ids(spec.fixed_candidates,'fixed discovery candidates',unique=True)
    if not spec.fixed_candidates:
        if spec.pool_id==POOL:raise ValueError('Named discovery requires its complete explicit candidate list')
        return
    plain=DiscoverFromPool(spec.player_id,'constructed.cards',source_id=spec.source_id,prompt=spec.prompt)
    if (type(spec)is not DiscoverFromPool or spec.pool_id!=POOL or spec.source_id is None or
            any(getattr(spec,f.name)!=getattr(plain,f.name)for f in fields(spec)if f.name not in('pool_id','fixed_candidates'))):
        raise ValueError('Named spell discovery requires one plain source-bound hand discovery')


def candidates(registry,spec):
    validate_spec(spec)
    from .pools import PoolMember
    from .errors import ResolutionError
    rows=[];identities=set()
    # Validate every named identity before offering or using randomness. Named
    # uncollectible spells are independent of an ordinary format inventory.
    for cid in sorted(spec.fixed_candidates):
        card=registry.card(cid);meta=registry.pool_card(cid)
        if (card.kind!=CardType.SPELL or not card.hand_playable or card.choice_only or
                card.metadata is None or card.metadata.collectible is not False or
                meta.generation_identity in identities):
            raise ResolutionError('Named spell discovery requires distinct complete uncollectible physical spells')
        identities.add(meta.generation_identity);rows.append(PoolMember(cid))
    return tuple(rows)
