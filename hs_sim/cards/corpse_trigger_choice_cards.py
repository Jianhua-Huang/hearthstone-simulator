"""Four actual corpse minions, native end subject and three real choices."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import ChoiceOption,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.guarded_corpse_spends import SpendCorpsesForMinion
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,Keyword,Resource,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.successful_summons import DamageSummonedMinion
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/corpse-trigger-choice-v1.json'
BATCH_HASH='2a81feae470b1cfd888797bdf3871eaa90e2d004f0363a4d349554813c73210a'
PREFIX='cards.corpse_trigger_choice.'
NECRO='RLK_061';DIREHORN='DINO_416';FLOWER='EDR_815';VOLCOROSS='FIR_951';FOOTMAN='RLK_061t'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Corpse trigger/choice source pin changed')
    return data


def living_source(c):
    return c.source.kind==CardType.MINION and c.source.zone==Zone.BOARD and c.source.active and c.source.health>0 and not c.source.doomed and c.source.controller==c.player_id


def register_corpse_trigger_choice_cards(registry):
    data=load_batch()
    def necromancer(c):
        if not living_source(c):return()
        request=SummonByCard(c.player_id,(SummonEntryMaterial(FOOTMAN),),SummonCause.capture(c))
        return(SpendCorpsesForMinion(MinionReference.capture(c.source),1,(request,),mode='free_space'),)
    def direhorn(c):
        if c.event is None or not living_source(c):return()
        identity=dict(c.event.data)['death_id'];dead=next((x for x in c.state.death_history if x.id==identity),None)
        if dead is None or(dead.entity_id,dead.controller)!=(c.event.source_id,c.event.player_id):raise ResolutionError('Direhorn lost the original death fact')
        if dead.controller!=c.player_id or dead.entity_id==c.source_id:return()
        ref=MinionReference.capture(c.source)
        return(SpendCorpsesForMinion(ref,3,(GrantCapturedKeyword(ref,Keyword.REBORN,c.source_id),),mode='missing_reborn'),)
    def flower(c):
        if c.event is None or c.event.player_id==c.player_id or not living_source(c):return()
        rows=[x for x in c.state.successful_summon_history if x.event_sequence==c.event.sequence]
        if len(rows)!=1 or(rows[0].entity_id,rows[0].player_id)!=(c.event.target_id,c.event.player_id):
            raise ResolutionError('Corpse Flower lost its original opponent successful summon')
        row=rows[0];damage=DamageSummonedMinion(row.player_id,row.id,c.source_id,3)
        return(SpendCorpsesForMinion(MinionReference.capture(c.source),2,(damage,),mode='summon',summon_id=row.id),)
    def volcoross(c):
        if not living_source(c):return()
        ref=MinionReference.capture(c.source);bank=c.state.players[c.player_id].resources[Resource.CORPSES]
        options=tuple(ChoiceOption(str(row['amount']),row['record']['name'],
            (SpendCorpsesForMinion(ref,row['amount'],(BuffCapturedMinion(ref,row['amount'],row['amount'],c.source_id),)),),
            card_id=row['record']['id'])for row in data['choices']if bank>=row['amount'])
        return(RequestChoice(c.player_id,options,c.source_id,prompt='选择消耗的残骸数量'),)if options else()
    for name,body in dict(necromancer=necromancer,direhorn=direhorn,flower=flower,volcoross=volcoross).items():
        registry.register_behavior(PREFIX+name,body)
    if tuple(x['record']['id']for x in data['cards'])!=(NECRO,DIREHORN,FLOWER,VOLCOROSS)or tuple(x['amount']for x in data['choices'])!=(10,20,30):
        raise TargetValidationError('Unreviewed corpse trigger/choice batch')
    for row in data['cards']+data['choices']+data['reused_dependencies']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete corpse trigger/choice raw row')
    for row in data['cards']+data['choices']:
        raw=row['record'];cid=raw['id'];meta=replace(metadata_from_record(raw),deck_identity=cid)
        if raw['type']=='SPELL':
            if raw['tags'].get('HIDE_COST')!=1 or cid not in('FIR_951t2','FIR_951t3','FIR_951t4'):
                raise TargetValidationError('Only the three original Volcoross descriptors are nonphysical')
            card=CardDefinition(cid,raw['name'],CardType.SPELL,choice_only=True,metadata=meta)
        else:
            recipe=row['recipe'];body=PREFIX+recipe['script'];kwargs={}
            if recipe['entry']=='owner_end':kwargs['triggers']=(TriggerSpec('turn_ended',body,EndTurnSpec()),)
            elif recipe['entry']=='friendly_death':kwargs['triggers']=(TriggerSpec('minion_died',body),)
            elif recipe['entry']=='enemy_summon':kwargs['triggers']=(TriggerSpec('minion_summoned',body),)
            elif recipe['entry']=='battlecry':kwargs['battlecry']=body
            else:raise TargetValidationError('Unknown corpse trigger native entry')
            keywords=tuple(k for tag,k in(('RUSH',Keyword.RUSH),('TAUNT',Keyword.TAUNT))if raw['tags'].get(tag)==1)
            card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health'],keywords=keywords,metadata=meta,**kwargs)
        registry.register_card(card)
        if not card.choice_only:registry.register_pool_card(PoolCard.from_definition(card))
    row=data['reused_dependencies'][0]
    if row['record']['id']!=FOOTMAN or canonical_digest(asdict(registry.card(FOOTMAN)))!=row['definition_digest']:
        raise TargetValidationError('Original Risen Footman dependency changed')
