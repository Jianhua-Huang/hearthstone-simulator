"""Ivory Knight consumes a real discovery selection through public healing."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discovery-cost-heal-v1.json'
BATCH_HASH='31e34fb6b20e342a66f99043d0951560d12b7deea9f738cb574011de367673d3'
KNIGHT='CORE_KAR_057';POOL_ID='constructed.cards';BODY='cards.discovery_cost_heal.knight'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(KNIGHT,)or
            tuple(x['record']['id']for x in data['evidence_only'])!=('KAR_057',)or data['dependencies']or
            data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed complete discovery cost-heal source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original discovery cost-heal row')
    return data


def register_discovery_cost_heal_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'))!=('MINION',4,4,4,1):
        raise TargetValidationError('Ivory Knight requires its current complete face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
        PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current'),source_id=c.source_id,
        heal_hero_by_printed_cost=True),))
    card=CardDefinition(KNIGHT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=replace(metadata_from_record(raw),deck_identity='KAR_057'),battlecry=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
