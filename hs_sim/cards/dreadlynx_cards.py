"""Curious Dreadlynx uses ordinary summon material with opposite source stats."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword, SummonStats
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='BE_850t'; TOKEN='BE_850'; BODY='cards.dreadlynx.opposite_stats'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/dreadlynx-v1.json'
BATCH_HASH='d914df9e73510491b0b63f7ffd609dfd8b5fb3835d9abf2b5369e09d4513aba9'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=(CARD,)or
            tuple(x['record']['id']for x in d['dependencies'])!=(TOKEN,)or
            any(d[k]for k in('existing_dependencies','evidence_only','choice_only','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['cards']+d['dependencies'])):
        raise TargetValidationError('Dreadlynx requires both complete reviewed original minion faces')
    return d


def register_dreadlynx_cards(registry):
    d=load_batch();raw=d['cards'][0]['record'];token=d['dependencies'][0]['record']
    if ((raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('RARITY'),
            raw['tags'].get('BATTLECRY'),raw['tags'].get('TAUNT'),raw['tags'].get('CARDRACE'))!=('MINION',5,2,5,2,4,1,1,20)or
            (token['type'],token['cost'],token['attack'],token['health'],token['collectible'],
             token['tags'].get('CLASS'),token['tags'].get('CARDRACE'),token['tags'].get('RUSH'))!=('MINION',5,5,2,False,2,20,1)):
        raise TargetValidationError('Dreadlynx lost its actual Druid Beast Taunt source or Rush Beast')
    def body(c):
        stats=SummonStats(max(0,c.source.health),c.source.attack)
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TOKEN,stats),),SummonCause.capture(c)),)
    registry.register_behavior(BODY,body)
    for row,kw,kwargs in((raw,Keyword.TAUNT,dict(battlecry=BODY)),(token,Keyword.RUSH,{})):
        card=CardDefinition(row['id'],row['name'],CardType.MINION,cost=row['cost'],attack=row['attack'],
            health=row['health'],keywords=(kw,),metadata=metadata_from_record(row),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
