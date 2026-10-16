"""I Know a Guy forwards one actual fixed discovery grant to shared creation."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discovered-minion-grant-v1.json'
BATCH_HASH='4a82f17e370ca6c3428ac6a3b294584abe1af02eb3c0ba002c9b9dd780d84db7'
GUY='CORE_WON_350';POOL_ID='constructed.cards';BODY='cards.discovered_minion_grant.guy'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(GUY,)or
            tuple(x['record']['id']for x in data['evidence_only'])!=('WON_350','CFM_940')or data['dependencies']or data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed complete discovered minion grant source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original minion grant row')
    return data

def register_discovered_minion_grant_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('CLASS'))!=('SPELL',1,10):raise TargetValidationError('I Know a Guy requires its current full face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.TAUNT,),class_mode='current'),
        source_id=c.source_id,minion_grant=CreatedMinionGrant(attack=1,health=2)),))
    card=CardDefinition(GUY,raw['name'],CardType.SPELL,cost=1,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
        metadata=replace(metadata_from_record(raw),deck_identity='WON_350'),on_play=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
