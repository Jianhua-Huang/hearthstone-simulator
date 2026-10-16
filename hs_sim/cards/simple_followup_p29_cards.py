"""Four ordinary native Battlecry discoveries using an explicit host format pool."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p29-v1.json'
BATCH_HASH='7b0e90ba14c8f5652ddef8934295726f07cc75b5cf5688c82fec525b7fa573d1'
WHELP='CATA_484';VICAR='CORE_ONY_022';NETHER='CORE_BT_321';PEDDLER='CORE_WON_096'
ROOTS=(WHELP,VICAR,NETHER,PEDDLER);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p29.'
IDENTITIES={WHELP:WHELP,VICAR:'ONY_022',NETHER:'BT_321',PEDDLER:'WON_096'}
QUERIES={WHELP:PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=1,max_cost=1),
 VICAR:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.HOLY,),class_mode='current'),
 NETHER:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('demon',),class_mode='current'),
 PEDDLER:PoolQuery(collectible=True,min_cost=1,max_cost=1,class_mode='current')}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P29 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('ONY_022','BT_321','WON_096')or data['skipped']):raise TargetValidationError('Unreviewed P29 recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P29 original row')
    return data

def register_simple_followup_p29_cards(registry):
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION'or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):raise TargetValidationError('P29 requires complete reviewed minion faces')
        registry.register_behavior(PREFIX+cid,lambda c,q=QUERIES[cid]:(DiscoverFromPool(c.player_id,POOL_ID,q,source_id=c.source_id),))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],battlecry=PREFIX+cid,metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
