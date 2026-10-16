"""Attributed pool summons and an ordinary two-spell creation discount."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Rarity
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p30-v1.json'
BATCH_HASH='74a78237b63e65038ee37f215e2d11ea18bae5d1de9e4069222ee6c521089a37'
MAZE='CORE_REV_308';MONGREL='CATA_723';SNEED='CORE_GVG_114';TOOLS='JAIL_706'
ROOTS=(MAZE,MONGREL,SNEED,TOOLS);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p30.'
IDENTITIES={MAZE:'REV_308',MONGREL:MONGREL,SNEED:'GVG_114',TOOLS:TOOLS}
QUERIES={MAZE:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2),
 MONGREL:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4),
 SNEED:PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,)),
 TOOLS:PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=4,max_cost=4)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P30 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('REV_308','GVG_114')or data['skipped']):raise TargetValidationError('Unreviewed P30 recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P30 original row')
    return data

def register_simple_followup_p30_cards(registry):
    def maze(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[MAZE],source_id=c.source_id,cause=SummonCause.capture(c)),)
    def mongrel(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[MONGREL],count=2,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)
    def sneed(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[SNEED],source_id=c.source_id,cause=SummonCause.capture(c)),)
    def tools(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[TOOLS],count=2,source_id=c.source_id,cost=CostSpec(delta=-2)),)
    bodies={MAZE:maze,MONGREL:mongrel,SNEED:sneed,TOOLS:tools}
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int:raise TargetValidationError('P30 requires complete reviewed costs')
        if kind==CardType.MINION:
            if any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P30 requires complete reviewed minion stats')
            kwargs.update(attack=raw['attack'],health=raw['health']);kwargs['battlecry'if cid==MAZE else'deathrattle']=PREFIX+cid
        elif cid==TOOLS and kind==CardType.SPELL:kwargs.update(on_play=PREFIX+cid,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
        else:raise TargetValidationError('Unreviewed P30 card type')
        registry.register_behavior(PREFIX+cid,bodies[cid]);card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
