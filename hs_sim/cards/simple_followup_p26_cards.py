"""Legendary Battlecry and reusable school-qualified ending generators."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,EndTurnSpec,Rarity,SpellSchool,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p26-v1.json'
BATCH_HASH='286eaebb5955ec80f40cbccbfb6ebb526a2173733022e1d64bb4929399a42e18'
BRIGHT='CORE_EX1_189';SENTRY='CATA_474';PIXIE='EDR_530';TOTEM='END_029';ROOTS=(BRIGHT,SENTRY,PIXIE,TOTEM);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p26.'
ZERO_ATTACK=(PIXIE,TOTEM)
QUERIES={BRIGHT:PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,)),
 SENTRY:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.HOLY,)),
 PIXIE:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.NATURE,)),
 TOTEM:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.SHADOW,))}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P26 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or data['existing_dependencies']or tuple(x['record']['id']for x in data['evidence_only'])!=('EX1_189',)or data['skipped']or data['reviewed_zero_attack']!={PIXIE:0,TOTEM:0}):raise TargetValidationError('Unreviewed P26 root/zero-attack recipe set')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P26 original row')
    for cid in ZERO_ATTACK:
        faces=[o['face']for o in data['official_observations']['observations']if o['card_id']==cid]
        if len(faces)!=2 or any(f['attack']!=0 for f in faces):raise TargetValidationError('P26 reviewed absent-ATK face requires both official zero observations')
    return data

def register_simple_followup_p26_cards(registry):
    data=load_batch()
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];attack=raw['attack'];kwargs={}
        if raw['type']!='MINION'or raw['collectible']is not True:raise TargetValidationError('P26 requires complete physical minion faces')
        if cid in ZERO_ATTACK:
            if attack is not None or 'ATK'in raw['tags']:raise TargetValidationError('P26 zero recipe must preserve original absent ATK')
            attack=data['reviewed_zero_attack'][cid]
        elif type(attack)is not int:raise TargetValidationError('Unreviewed missing P26 Attack')
        registry.register_behavior(PREFIX+cid,lambda c,query=QUERIES[cid],cost=CostSpec(delta=-3)if cid==SENTRY else None:(GenerateFromPool(c.player_id,POOL_ID,query,source_id=c.source_id,cost=cost),))
        if cid==BRIGHT:kwargs['battlecry']=PREFIX+cid
        else:kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec()),)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=attack,health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity='EX1_189'if cid==BRIGHT else cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
