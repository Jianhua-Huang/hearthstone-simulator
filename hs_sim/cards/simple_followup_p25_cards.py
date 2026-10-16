"""Four native Battlecry consumers of an explicit host-qualified constructed pool."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p25-v1.json'
BATCH_HASH='adc6616daec47a16111fc95e4555680b4c2ee4f242c76b16310868da8b8d2a19'
RAIDER='CORE_DRG_024';MACAW='CORE_UNG_912';GREENFIN='EDR_999';WHELP='CATA_556';ROOTS=(RAIDER,MACAW,GREENFIN,WHELP);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p25.'
TRIBES={RAIDER:'pirate',MACAW:'beast',GREENFIN:'murloc',WHELP:'dragon'}
IDENTITIES={RAIDER:'DRG_024',MACAW:'UNG_912',GREENFIN:GREENFIN,WHELP:WHELP}
QUERIES={cid:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=(TRIBES[cid],),max_cost=3 if cid==WHELP else None)for cid in ROOTS}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P25 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or
       tuple(x['record']['id']for x in data['evidence_only'])!=('DRG_024','UNG_912')or data['skipped']):raise TargetValidationError('Unreviewed P25 root/dependency set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P25 original row')
    return data

def register_simple_followup_p25_cards(registry):
    data=load_batch()
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if(raw['type']!='MINION'or raw['collectible']is not True or raw['tags'].get('BATTLECRY')!=1):raise TargetValidationError('P25 requires complete native Battlecry minion faces')
        registry.register_behavior(PREFIX+cid,lambda c,query=QUERIES[cid]:(GenerateFromPool(c.player_id,POOL_ID,query,source_id=c.source_id),))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],battlecry=PREFIX+cid,
            metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
