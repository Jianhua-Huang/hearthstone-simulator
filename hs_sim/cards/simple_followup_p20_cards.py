"""Two complete real Shatter families composed from native sequential effects."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import Damage,DamageBatch,InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,ShatterSpec,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p20-v1.json'
BATCH_HASH='2610212635c9703decd0293b0e5d7b871f09e0874ae3ee34b9b693557f233baf'
SUPPLY='CATA_820';FLOW='CATA_489';SUPPLY_DRAW='CATA_820t';SUPPLY_BUFF='CATA_820t2';FLOW_HIT='CATA_489t';FLOW_AOE='CATA_489t2'
ROOTS=(SUPPLY,FLOW);DEPENDENCIES=(SUPPLY_DRAW,SUPPLY_BUFF,FLOW_HIT,FLOW_AOE);PYROMANCER='TIME_101';PREFIX='cards.simple_followup_p20.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P20 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
       tuple(x['record']['id']for x in data['existing_dependencies'])!=(PYROMANCER,)or tuple(x['record']['id']for x in data['evidence_only'])!=('CATA_820e',)or data['skipped']):raise TargetValidationError('Unreviewed P20 root/family set')
    for row in data['cards']+data['dependencies']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P20 original row')
    return data

def register_simple_followup_p20_cards(registry):
    data=load_batch();existing,=data['existing_dependencies']
    if canonical_digest(asdict(registry.card(PYROMANCER)))!=existing['definition_sha256']:raise TargetValidationError('P20 existing Pyromancer definition changed')
    def next_body(c,name):return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id)
    def draw(c):return DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,)),'skip',count=3,source_id=c.source_id)
    bodies={'supply':lambda c:(draw(c),next_body(c,'buff')),'draw':lambda c:(draw(c),),
        'buff':lambda c:(BuffMinionsInZones(c.player_id,2,2,MinionScope(zones=(Zone.HAND,)),c.source_id),),
        'flow':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),next_body(c,'aoe')),
        'hit':lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),),
        'aoe':lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)for i in characters(c,registry,3-c.player_id))),)}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    scripts={SUPPLY:'supply',SUPPLY_DRAW:'draw',SUPPLY_BUFF:'buff',FLOW:'flow',FLOW_HIT:'hit',FLOW_AOE:'aoe'}
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];root=cid in ROOTS;kwargs={};flow=cid in(FLOW,FLOW_HIT,FLOW_AOE)
        if(raw['type']!='SPELL'or raw['collectible']!=root or raw['tags'].get('SHATTER'if root else'SHATTERED')!=1):raise TargetValidationError('P20 lost its exact physical Shatter/fragment face')
        if flow:
            if raw['tags'].get('SPELL_SCHOOL')!=1:raise TargetValidationError('Arcane Flow lost its exact Arcane school')
            kwargs['spell_school']=SpellSchool.ARCANE
        elif 'SPELL_SCHOOL'in raw['tags']:raise TargetValidationError('Supply Run must retain absent spell school')
        if root:kwargs['shatter']=ShatterSpec(*( (SUPPLY_DRAW,SUPPLY_BUFF)if cid==SUPPLY else(FLOW_HIT,FLOW_AOE)))
        if cid in(FLOW,FLOW_HIT):kwargs['targeting']=TargetSpec()
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+scripts[cid],keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,),metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
