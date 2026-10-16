"""Exact Sewer Swimmer adapter; targeted Kindred root awaits public support."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import TriggerDeathrattles
from hs_sim.engine.model import CardDefinition,CardType,HandActionSpec,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p18-v1.json'
BATCH_HASH='72c2eb6c96bdc0312f63be8029d9b4122dc59839075802c26d01aa66c5cfd062'
SWIMMER='JAIL_395';MATRIARCH='TLC_825';ROOTS=(SWIMMER,);DEPENDENCIES=();PREFIX='cards.simple_followup_p18.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P18 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=(SWIMMER,MATRIARCH)or data['dependencies']or data['existing_dependencies']or data['evidence_only']or
       tuple(x['id']for x in data['skipped'])!=(MATRIARCH,)):raise TargetValidationError('Unreviewed P18 root/dependency set')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P18 original row')
    return data

def register_simple_followup_p18_cards(registry):
    data=load_batch()
    registry.register_behavior(PREFIX+'swimmer',lambda c:(TriggerDeathrattles(c.target_id,c.source_id),)if c.target_id is not None else())
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if cid not in ROOTS:continue
        if raw['type']!='MINION'or raw['tags'].get('BATTLECRY')!=1 or raw['tags'].get('DECK_ACTION_COST')!=1:
            raise TargetValidationError('Sewer Swimmer lost its reviewed Battlecry/Prepare face')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),battlecry=PREFIX+'swimmer',
            hand_actions=(HandActionSpec('prepare','prepare',1),),
            targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
