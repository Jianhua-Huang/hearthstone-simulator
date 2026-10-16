"""Reviewed fixed-class and Deathrattle consumers of the explicit format pool."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,Rarity,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p28-v1.json'
BATCH_HASH='5b93c187ea5769eea8b837d0411ed30f813402e5423a538e73f082e979a3d7bc'
WITCH='CORE_GIL_531';DRAGON='MEND_045';CHAMPION='TIME_613';MENDER='TLC_814'
ROOTS=(WITCH,DRAGON,CHAMPION,MENDER);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p28.'
QUERIES={WITCH:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.SHAMAN,),include_neutral=False),
 DRAGON:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',)),
 CHAMPION:PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,)),
 MENDER+'.holy':PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.HOLY,)),
 MENDER+'.shadow':PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.SHADOW,))}
RECIPES={WITCH:((WITCH,None),),DRAGON:((DRAGON,CostSpec(delta=-2)),),CHAMPION:((CHAMPION,CostSpec(delta=-1)),),MENDER:((MENDER+'.holy',None),(MENDER+'.shadow',None))}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P28 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('GIL_531',)or data['skipped']or data['reviewed_zero_cost']!={WITCH:0}or data['reviewed_zero_attack']!={WITCH:0}):raise TargetValidationError('Unreviewed P28 recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P28 original row')
    faces=[o['face']for o in data['official_observations']['observations']if o['card_id']==WITCH]
    if len(faces)!=2 or any(f['manaCost']!=0 or f['attack']!=0 for f in faces):raise TargetValidationError('P28 absent cost/attack require both complete official zero faces')
    return data

def register_simple_followup_p28_cards(registry):
    data=load_batch()
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];cost=raw['cost'];attack=raw['attack']
        if raw['type']!='MINION'or raw['collectible']is not True or type(raw['health'])is not int:raise TargetValidationError('P28 requires complete reviewed minion faces')
        if cid==WITCH:
            if cost is not None or attack is not None or 'COST'in raw['tags']or 'ATK'in raw['tags']:raise TargetValidationError('P28 zero recipe must preserve original absent tags')
            cost=data['reviewed_zero_cost'][cid];attack=data['reviewed_zero_attack'][cid]
        elif type(cost)is not int or type(attack)is not int:raise TargetValidationError('Unreviewed P28 missing cost/attack')
        registry.register_behavior(PREFIX+cid,lambda c,recipe=RECIPES[cid]:tuple(GenerateFromPool(c.player_id,POOL_ID,QUERIES[key],source_id=c.source_id,cost=discount)for key,discount in recipe))
        kwargs={'battlecry'if cid==WITCH else'deathrattle':PREFIX+cid}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=cost,attack=attack,health=raw['health'],keywords=(Keyword.TAUNT,)if cid in(WITCH,DRAGON)else(),
            metadata=replace(metadata_from_record(raw),deck_identity='GIL_531'if cid==WITCH else cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
