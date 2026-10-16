"""Flight Maneuvers: complete real Shatter family with finite captured grants."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import InvokeBehavior
from hs_sim.engine.model import CardDefinition,CardType,Keyword,ShatterSpec,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p22-v1.json'
BATCH_HASH='c21f024dd33813140c60185575c402b1b14cc768cd7655630906c098ce8e3c4d'
FLIGHT='CATA_479';SUMMON='CATA_479t';GRANT='CATA_479t2';DRAKE='CATA_479t3';ROOTS=(FLIGHT,);DEPENDENCIES=(SUMMON,GRANT,DRAKE);PYROMANCER='TIME_101';PREFIX='cards.simple_followup_p22.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P22 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
       tuple(x['record']['id']for x in data['existing_dependencies'])!=(PYROMANCER,)or tuple(x['record']['id']for x in data['evidence_only'])!=('CATA_479e',)or data['skipped']):raise TargetValidationError('Unreviewed P22 root/family set')
    for row in data['cards']+data['dependencies']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P22 original row')
    return data

def register_simple_followup_p22_cards(registry):
    data=load_batch();existing,=data['existing_dependencies']
    if canonical_digest(asdict(registry.card(PYROMANCER)))!=existing['definition_sha256']:raise TargetValidationError('P22 existing Pyromancer definition changed')
    def summons(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(DRAKE),),SummonCause.capture(c))
        return request,request
    def grant(c):
        refs=tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,c.player_id))
        return tuple(effect for ref in refs for effect in(BuffCapturedMinion(ref,1,0,c.source_id),GrantCapturedKeyword(ref,Keyword.DIVINE_SHIELD,c.source_id)))
    bodies={'whole':lambda c:(*summons(c),InvokeBehavior(PREFIX+'grant',c.source_id,c.player_id,play_id=None if c.play is None else c.play.id)),
        'summon':summons,'grant':grant}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if cid==DRAKE:
            if raw['type']!='MINION'or raw['collectible']or raw['tags'].get('CARDRACE')!=24:raise TargetValidationError('P22 exact Dragon dependency changed')
            kwargs.update(attack=raw['attack'],health=raw['health'])
        else:
            root=cid==FLIGHT
            if(raw['type']!='SPELL'or raw['collectible']!=root or raw['tags'].get('SPELL_SCHOOL')!=5 or raw['tags'].get('SHATTER'if root else'SHATTERED')!=1):raise TargetValidationError('P22 lost its complete Holy Shatter face')
            kwargs.update(spell_school=SpellSchool.HOLY,on_play=PREFIX+{FLIGHT:'whole',SUMMON:'summon',GRANT:'grant'}[cid],keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,))
            if root:kwargs['shatter']=ShatterSpec(SUMMON,GRANT)
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
