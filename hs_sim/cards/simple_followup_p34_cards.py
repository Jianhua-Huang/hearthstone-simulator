"""Six native pool consumers; all timing and resources use public effects."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.imbue import Imbue
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,Keyword,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p34-v1.json'
BATCH_HASH='618ce636fb8c17d12da944526cfa1517c542fce5b6b230834b614d3ae69654a5'
JACKPOT='CORE_TID_931';SELLER='CORE_ETC_111';ASTRO='CORE_BOT_256';ATLAS='DINO_431';DRAKE='EDR_462';AEGIS='EDR_264';POWER='EDR_445p'
ROOTS=(JACKPOT,SELLER,ASTRO,ATLAS,DRAKE,AEGIS);DEPENDENCIES=();EXISTING_DEPENDENCIES=(POWER,);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p34.'
IDENTITIES={cid:{JACKPOT:'TID_931',SELLER:'ETC_111',ASTRO:'BOT_256'}.get(cid,cid)for cid in ROOTS}
QUERIES={JACKPOT:PoolQuery(kinds=(CardType.SPELL,),collectible=True,min_cost=5,class_mode='other',include_neutral=False),
 SELLER:PoolQuery(kinds=(CardType.SPELL,),collectible=True),
 ATLAS:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=5,keywords_all=(Keyword.TAUNT,)),
 DRAKE:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',)),
 AEGIS:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P34 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or tuple(x['record']['id']for x in data['existing_dependencies'])!=EXISTING_DEPENDENCIES or tuple(x['record']['id']for x in data['evidence_only'])!=('TID_931','ETC_111','BOT_256')or data['skipped']):raise TargetValidationError('Unreviewed P34 recipe set')
    for row in data['cards']+data['existing_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P34 original row')
    for row in data['existing_dependencies']:
        if canonical_digest(row['definition'])!=row['definition_sha256']:raise TargetValidationError('Incomplete P34 existing dependency definition')
    return data

def register_simple_followup_p34_cards(registry):
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:raise TargetValidationError('P34 requires unchanged complete Blessing of the Dragon')
    def jackpot(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[JACKPOT],count=2,source_id=c.source_id),)
    def seller(c):return(GenerateFromPool(3-c.player_id,POOL_ID,QUERIES[SELLER],destination='deck',position='top',source_id=c.source_id),)
    def astro(c):
        size=len(c.state.players[c.player_id].hand)
        return(SummonFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=size,max_cost=size),source_id=c.source_id,cause=SummonCause.capture(c)),)
    def atlas(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[ATLAS],source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),)
    def drake(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[DRAKE],source_id=c.source_id),)
    def aegis(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[AEGIS],source_id=c.source_id,cause=SummonCause.capture(c),entry_keywords=(Keyword.TAUNT,)),Imbue(c.player_id,c.source_id))
    bodies=dict(zip(ROOTS,(jackpot,seller,astro,atlas,drake,aegis)))
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());school=raw['tags'].get('SPELL_SCHOOL');kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int or school is not None and school not in SCHOOLS:raise TargetValidationError('P34 requires complete reviewed faces')
        registry.register_behavior(PREFIX+cid,bodies[cid])
        if kind==CardType.MINION:
            if any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P34 minion stats must be explicit')
            kwargs.update(attack=raw['attack'],health=raw['health'])
            if cid in(SELLER,DRAKE):kwargs['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,end_turn=EndTurnSpec()),)
            elif cid==ASTRO:kwargs['battlecry']=PREFIX+cid
            elif cid==ATLAS:kwargs['deathrattle']=PREFIX+cid
            else:raise TargetValidationError('Unreviewed P34 minion body')
            if cid==ATLAS:kwargs['keywords']=(Keyword.TAUNT,)
            if cid==DRAKE:kwargs['keywords']=(Keyword.ELUSIVE,)
        elif kind==CardType.SPELL:kwargs['on_play']=PREFIX+cid
        else:raise TargetValidationError('Unreviewed P34 card type')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],spell_school=SCHOOLS.get(school),metadata=replace(metadata_from_record(raw),deck_identity=IDENTITIES[cid]),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
