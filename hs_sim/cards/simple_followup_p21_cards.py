"""Wildwood Circle's complete real Shatter family and finite granted Deathrattle."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import GrantDeathrattle,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,ShatterSpec,SpellSchool
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p21-v1.json'
BATCH_HASH='d66f5758c035493de97372d9bde51dac41077c5193df60b229e8eb4aea7546b2'
CIRCLE='CATA_134';SUMMON='CATA_134t';GRANT='CATA_134t2';TREANT='CATA_134t3';ROOTS=(CIRCLE,);DEPENDENCIES=(SUMMON,GRANT,TREANT);PYROMANCER='TIME_101';PREFIX='cards.simple_followup_p21.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P21 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or
       tuple(x['record']['id']for x in data['existing_dependencies'])!=(PYROMANCER,)or tuple(x['record']['id']for x in data['evidence_only'])!=('CATA_134e',)or data['skipped']):raise TargetValidationError('Unreviewed P21 root/family set')
    for row in data['cards']+data['dependencies']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P21 original row')
    return data

def register_simple_followup_p21_cards(registry):
    data=load_batch();existing,=data['existing_dependencies']
    if canonical_digest(asdict(registry.card(PYROMANCER)))!=existing['definition_sha256']:raise TargetValidationError('P21 existing Pyromancer definition changed')
    def summons(c):
        request=SummonByCard(c.player_id,(SummonEntryMaterial(TREANT),),SummonCause.capture(c))
        return request,request
    def rattle(c):
        if c.deathrattle is None:raise ResolutionError('Wildwood grant requires its actual natural or effect Deathrattle activation')
        board=c.state.players[c.player_id].board
        position=c.death.position if c.death is not None else board.index(c.source_id)+1 if c.source_id in board else None
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TREANT),),SummonCause.capture(c),position=position),)
    bodies={'whole':lambda c:(*summons(c),InvokeBehavior(PREFIX+'grant',c.source_id,c.player_id,play_id=None if c.play is None else c.play.id)),
        'summon':summons,'grant':lambda c:tuple(GrantDeathrattle(i,PREFIX+'rattle',c.source_id)for i in minions(c,registry,c.player_id)),'rattle':rattle}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if cid==TREANT:
            if raw['type']!='MINION'or raw['collectible']or raw['tags'].get('2831')!=1:raise TargetValidationError('P21 exact vanilla Treant dependency changed')
            kwargs.update(attack=raw['attack'],health=raw['health'])
        else:
            root=cid==CIRCLE
            if(raw['type']!='SPELL'or raw['collectible']!=root or raw['tags'].get('SPELL_SCHOOL')!=4 or raw['tags'].get('SHATTER'if root else'SHATTERED')!=1):raise TargetValidationError('P21 lost its complete Nature Shatter face')
            kwargs.update(spell_school=SpellSchool.NATURE,on_play=PREFIX+{CIRCLE:'whole',SUMMON:'summon',GRANT:'grant'}[cid],keywords=(Keyword.SHATTER if root else Keyword.SHATTERED,))
            if root:kwargs['shatter']=ShatterSpec(SUMMON,GRANT)
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
