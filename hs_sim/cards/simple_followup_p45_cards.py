"""Native printed-Deathrattle pool summon and ordinary granted two-card DR."""
import json
from pathlib import Path
from hs_sim.engine.effects import GrantDeathrattle
from hs_sim.engine.model import CardDefinition,CardType,TargetSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p45-v1.json'
BATCH_HASH='532ee7b069a308dd8bbfefb4701547030facc615ad4819993a291d8e8346d895'
DOG='JAIL_878';DIG='JAIL_876';ROOTS=(DOG,DIG);DEPENDENCIES=();EVIDENCE_ONLY=('JAIL_876e',);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p45.';PAYLOAD=PREFIX+'two'
QUERIES={DOG:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1,deathrattle=True),DIG:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['evidence_only'])!=EVIDENCE_ONLY or any(data[k]for k in('dependencies','existing_dependencies','skipped'))):raise TargetValidationError('P45 complete reviewed recipe set changed')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P45 original row')
    return data

def register_simple_followup_p45_cards(registry):
    def dog(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[DOG],source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),)
    def two(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[DIG],count=2,source_id=c.source_id,destination='board',cause=SummonCause.capture(c),board_position=deathrattle_position(c)),)
    registry.register_behavior(PREFIX+DOG,dog);registry.register_behavior(PAYLOAD,two);registry.register_behavior(PREFIX+DIG,lambda c:(GrantDeathrattle(c.target_id,PAYLOAD,c.source_id),))
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if raw['collectible']is not True or type(raw['cost'])is not int or 'SPELL_SCHOOL'in raw['tags']:raise TargetValidationError('P45 requires complete unschooled collectible faces')
        if cid==DOG:
            if raw['type']!='MINION'or raw['tags'].get('DEATHRATTLE')!=1 or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P45 native Guard Dog face changed')
            kwargs.update(attack=raw['attack'],health=raw['health'],deathrattle=PREFIX+DOG)
        elif raw['type']=='SPELL':kwargs.update(on_play=PREFIX+DIG,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'))
        else:raise TargetValidationError('P45 granted Deathrattle source face changed')
        card=CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],metadata=metadata_from_record(raw),**kwargs);registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
