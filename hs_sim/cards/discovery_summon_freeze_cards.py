"""Glaciate uses attributed discovery and its original first summon delivery."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discovery-summon-freeze-v1.json'
BATCH_HASH='38908a5b4df8f883434a49cc440e0c52c00e032d9911aff00729a34042046135'
GLACIATE='CORE_AV_107';POOL_ID='constructed.cards';BODY='cards.discovery_summon_freeze.glaciate'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(GLACIATE,)or
            tuple(x['record']['id']for x in data['evidence_only'])!=('AV_107',)or
            data['dependencies']or data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed complete Glaciate source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original Glaciate row')
    return data


def register_discovery_summon_freeze_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',6,3):
        raise TargetValidationError('Glaciate requires its current full face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),min_cost=8,max_cost=8,collectible=True,class_mode='current'),
        source_id=c.source_id,destination='board',cause=SummonCause.capture(c),freeze_summoned=True),))
    card=CardDefinition(GLACIATE,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.FROST,
        metadata=replace(metadata_from_record(raw),deck_identity='AV_107'),on_play=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
