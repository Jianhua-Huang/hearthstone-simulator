"""Actual minion Battlecries delegate capacity-aware fill to the pool producer."""
import json
from pathlib import Path
from hs_sim.engine.effects import Heal,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,HealingKind,Keyword
from hs_sim.engine.pools import FillBoardFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.turn_scheduling import SkipTurns
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-pool-fill-v1.json'
BATCH_HASH='95e7ad284baee425899de75f1f50fe27b25285306328631f1851920674d44b8c'
CHAMPION='TIME_872';MUROZOND='END_037';PREFIX='cards.native_pool_fill.'
POOL_ID='constructed.cards'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CHAMPION,MUROZOND)
            or any(d[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Native pool fill requires complete reviewed sources')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']):
        raise TargetValidationError('Native pool fill original source row changed')
    return d


def register_native_pool_fill_cards(registry):
    def champion(c):
        return (FillBoardFromPool(3-c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=1,max_cost=1),c.source_id,SummonCause.capture(c)),)
    def muro(c):
        return (FillBoardFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            tribes_any=('dragon',)),c.source_id,SummonCause.capture(c)),
            InvokeBehavior(PREFIX+'heal',c.source_id,c.player_id),SkipTurns(c.player_id,source_id=c.source_id))
    def heal(c):
        hero=c.state.entities[c.state.players[c.player_id].hero_id]
        return (Heal(hero.id,hero.max_health,c.source_id,HealingKind.EFFECT),)
    for name,body in((CHAMPION,champion),(MUROZOND,muro),('heal',heal)):
        registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION' or raw['tags'].get('BATTLECRY')!=1:
            raise TargetValidationError('Pool fill requires its actual minion Battlecry')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),battlecry=PREFIX+cid,
            keywords=(Keyword.RUSH,)if cid==CHAMPION else())
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
