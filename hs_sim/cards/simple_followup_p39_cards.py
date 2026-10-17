"""Successful Nature casts make real Treants; ordinary targeted Choose One."""
import json
from pathlib import Path
from hs_sim.engine.effects import Destroy
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,ChooseBranch,ChooseOneSpec,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p39-v1.json'
BATCH_HASH='843721ad2733c469e21a69d5cb3987f083015e1fbc05b55a0b89dc1dc43fbb05'
GROVE='EDR_271';INFLUENCE='EDR_463';TREANT='EDR_271t';THORNS='EDR_463a';VINES='EDR_463b';ROOTS=(GROVE,INFLUENCE);DEPENDENCIES=(TREANT,THORNS,VINES);CHOICE_ONLY=(THORNS,VINES);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p39.'
QUERIES={TREANT:PoolQuery(kinds=(CardType.SPELL,),collectible=True,spell_schools=(SpellSchool.NATURE,)),INFLUENCE:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2)}

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES or tuple(data['choice_only_ids'])!=CHOICE_ONLY or any(data[k]for k in('existing_dependencies','evidence_only','skipped'))):raise TargetValidationError('P39 complete reviewed recipe set changed')
    for row in data['cards']+data['dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P39 original row')
    return data

def register_simple_followup_p39_cards(registry):
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']+data['dependencies']}
    def grove(c):
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):raise ResolutionError('Grove Shaper lost original completed spell linkage')
        if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:raise ResolutionError('Grove Shaper requires actual successful spell completion')
        if cast.player_id!=c.player_id or not living_source(c)or registry.card(cast.card_id).spell_school!=SpellSchool.NATURE:return ()
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TREANT),),SummonCause.capture(c)),)
    def treant(c):return(GenerateFromPool(c.player_id,POOL_ID,QUERIES[TREANT],source_id=c.source_id),)
    def destroy(c):return(Destroy(c.target_id,c.source_id),)if c.target_id is not None else()
    def summon(c):return(SummonFromPool(c.player_id,POOL_ID,QUERIES[INFLUENCE],source_id=c.source_id,cause=SummonCause.capture(c)),)
    for name,body in((GROVE,grove),(TREANT,treant),(THORNS,destroy),(VINES,summon),('combined',lambda c:(*destroy(c),*summon(c)))):registry.register_behavior(PREFIX+name,body)
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'small',attack_max=3))
    required=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,));available=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());choice=cid in CHOICE_ONLY;kwargs={}
        if raw['collectible']!=(cid in ROOTS)or type(raw['cost'])is not int:raise TargetValidationError('P39 requires complete collectible and dependent faces')
        if cid in(GROVE,TREANT):
            if raw['type']!='MINION'or any(type(raw[k])is not int for k in('attack','health')):raise TargetValidationError('P39 original minion stats required')
            kwargs.update(attack=raw['attack'],health=raw['health'])
            if cid==GROVE:kwargs['triggers']=(TriggerSpec('spell_cast_finished',PREFIX+GROVE),)
            else:kwargs['deathrattle']=PREFIX+TREANT
        elif cid==INFLUENCE:kwargs['choose_one']=ChooseOneSpec((ChooseBranch(THORNS,raws[THORNS]['name'],PREFIX+THORNS,required,PREFIX+'small'),ChooseBranch(VINES,raws[VINES]['name'],PREFIX+VINES)),ChooseBranch(INFLUENCE+':combined','兼得',PREFIX+'combined',available,PREFIX+'small'))
        card=CardDefinition(cid,raw['name'],kind,cost=0 if choice else raw['cost'],choice_only=choice,spell_school=SpellSchool.SHADOW if raw['tags'].get('SPELL_SCHOOL')==6 else None,metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card)
        if not choice:registry.register_pool_card(PoolCard.from_definition(card))
