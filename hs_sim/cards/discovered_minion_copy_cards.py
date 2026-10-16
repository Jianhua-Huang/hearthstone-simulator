"""Ritual of Life retains its discovered card and summons an attributed copy."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,SpellSchool,SummonStats
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/discovered-minion-copy-v1.json'
BATCH_HASH='402032119fcd3386779fe90fc82a2310be07a2a975ede79fbc4137544ba8f592'
RITUAL='DINO_426';POOL_ID='constructed.cards';BODY='cards.discovered_minion_copy.ritual'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(RITUAL,)or
       tuple(x['record']['id']for x in data['evidence_only'])!=('DINO_426e',)or data['dependencies']or data['existing_dependencies']or data['skipped']):
        raise TargetValidationError('Unreviewed complete Ritual source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete Ritual original row')
    return data

def register_discovered_minion_copy_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',2,5):raise TargetValidationError('Ritual requires its current full face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL_ID,
        PoolQuery(kinds=(CardType.MINION,),min_cost=3,max_cost=3,collectible=True,class_mode='current'),
        source_id=c.source_id,cause=SummonCause.capture(c),summon_copy_stats=SummonStats(2,3)),))
    card=CardDefinition(RITUAL,raw['name'],CardType.SPELL,cost=2,spell_school=SpellSchool.HOLY,metadata=metadata_from_record(raw),on_play=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
