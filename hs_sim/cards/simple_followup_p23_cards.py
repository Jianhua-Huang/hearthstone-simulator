"""Schism's complete Shatter family, captured grants and original-residence copy."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import CopyMinion
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,Keyword,ShatterSpec,SpellSchool,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p23-v1.json'
BATCH_HASH='6f2c51b9c371f8509fb3801c570f7613a171b795335c50e50b4746b3a7c6ecdc'
SCHISM='CATA_306';GRANT='CATA_306t1';COPY='CATA_306t2';ROOTS=(SCHISM,);DEPENDENCIES=(GRANT,COPY);PYROMANCER='TIME_101';PREFIX='cards.simple_followup_p23.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P23 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
       tuple(x['record']['id']for x in data['existing_dependencies'])!=(PYROMANCER,)or tuple(x['record']['id']for x in data['evidence_only'])!=('CATA_306e',)or data['skipped']):raise TargetValidationError('Unreviewed P23 root/family set')
    for row in data['cards']+data['dependencies']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P23 original row')
    return data

def register_simple_followup_p23_cards(registry):
    data=load_batch();existing,=data['existing_dependencies']
    if canonical_digest(asdict(registry.card(PYROMANCER)))!=existing['definition_sha256']:raise TargetValidationError('P23 existing Pyromancer definition changed')
    def body(c,grant,copy):
        result=()
        if grant:
            ref=MinionReference.capture(c.state.entities[c.target_id])
            result=(BuffCapturedMinion(ref,2,3,c.source_id),GrantCapturedKeyword(ref,Keyword.ELUSIVE,c.source_id))
        if copy:result+= (CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),)
        return result
    for name,grant,copy in(('whole',True,True),('grant',True,False),('copy',False,True)):
        registry.register_behavior(PREFIX+name,lambda c,grant=grant,copy=copy:body(c,grant,copy))
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];root=cid==SCHISM;kwargs={}
        if(raw['type']!='SPELL'or raw['collectible']!=root or raw['tags'].get('SPELL_SCHOOL')!=6 or raw['tags'].get('SHATTER'if root else'SHATTERED')!=1):raise TargetValidationError('P23 lost its complete Shadow Shatter face')
        if root:kwargs['shatter']=ShatterSpec(GRANT,COPY)
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.SHADOW,on_play=PREFIX+{SCHISM:'whole',GRANT:'grant',COPY:'copy'}[cid],
            keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,),targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'),
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
