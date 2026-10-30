"""Actual mana/history conditions, continuous sources and original tutor rewards."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.effects import Damage,DamageBatch
from hs_sim.engine.model import (AuraSpec,BoardPresenceReference,CardDefinition,CardType,DamageKind,EndTurnSpec,
    Keyword,KeywordAuraSpec,PlayedTypeQuery,TriggerSpec,Zone)
from hs_sim.engine.owner_turns import query_previous_owner_turn
from hs_sim.engine.physical_draw_groups import (DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup,FROST_FOLLOWUP,SOURCE_KEYWORDS,TUTOR_KEYWORDS)
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference,SetCapturedMinionStats
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import characters

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-condition-tutor-aura-consumers-v1.json'
BATCH_HASH='63e366b93d51b06356fd8589e165305f8c2765cf723fa24075d336e59653b365'
TYRANT,OZRUK,TURALYON,MALGANIS,VESSINA,YIP,CATRINA,FRIGIDARA,SESELI,VARIAN,ASHMORE,RAS=ROOTS=(
    'MIS_712','UNG_907','SCH_135','GVG_021','ULD_173','LOOT_519','DAL_721','LEG_RLK_224','REV_319','SW_081','GIL_578','SCH_273')
DEPENDENCIES=EXISTING=()
PREFIX='cards.past_condition_tutor_aura.'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION' or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Condition/tutor/aura consumer lost its complete original minion face')
    fields={}
    if cid in(TYRANT,OZRUK,FRIGIDARA,VARIAN,ASHMORE):fields['battlecry']=PREFIX+cid
    if cid==SESELI:fields['deathrattle']=PREFIX+cid
    if cid==TURALYON:fields['triggers']=(TriggerSpec('attack_declared',PREFIX+cid),)
    if cid in(YIP,CATRINA,RAS):fields['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec('controller')),)
    if cid==MALGANIS:fields.update(auras=(AuraSpec(2,health=2,tribes_any=('demon',)),),
        keyword_auras=(KeywordAuraSpec(Keyword.IMMUNE,'friendly_hero'),))
    if cid==VESSINA:fields['auras']=(AuraSpec(2,condition='controller_overloaded'),)
    keys=tuple(key for tag,key in(('TAUNT',Keyword.TAUNT),('RUSH',Keyword.RUSH),('ELUSIVE',Keyword.ELUSIVE))if raw['tags'].get(tag)==1)
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=keys,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            any(d[k]for k in('dependencies','existing_dependencies'))or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=26 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Condition/tutor/aura batch lost full source roles or made a completeness claim')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','evidence_only')for x in d[key]):
        raise TargetValidationError('Condition/tutor/aura batch changed a complete original raw row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Condition/tutor/aura batch changed the complete past reference')
    reference=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in reference['candidate_records']}
    if(len(reference['candidate_ids'])!=732 or d['original_candidate_ids']!=reference['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Condition/tutor/aura batch cropped the original complete past source')
    return d


def register_past_condition_tutor_aura_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Condition/tutor/aura consumer cannot replace an existing original face')
        registry._validate_card(card);prepared.append(card)
    def source_buff(c,attack,health):
        return(BuffCapturedMinion(MinionReference.capture(c.source),attack,health,c.source_id),)if living_source(c)else()
    def ozruk(c):
        previous=query_previous_owner_turn(c.state,c.player_id,PlayedTypeQuery(CardType.MINION,('elemental',)))
        count=sum(row.matched for row in previous.rows)
        return source_buff(c,0,5*count)if count else()
    def turalyon(c):
        if c.event.source_id!=c.source_id:return()
        target=c.state.entities[c.event.target_id]
        if target.kind!=CardType.MINION or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return()
        return(SetCapturedMinionStats(MinionReference.capture(target),3,3,c.source_id),)
    def yip(c):
        amount=min(10,c.state.entities[c.state.players[c.player_id].hero_id].armor)
        return(SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),min_cost=amount,
            max_cost=amount,collectible=True),source_id=c.source_id,cause=SummonCause.capture(c)),)
    def catrina(c):
        return(Resurrect(c.player_id,1,DeathQuery(cards=PoolQuery(tribes_any=('undead',)),exclude_entity_ids=(c.source_id,)),
            source_id=c.source_id,cause=SummonCause.capture(c)),)
    def frigidara(c):
        return(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2,
            DrawGroupReward(FROST_FOLLOWUP,behavior_id=PREFIX+'frost_damage')),)
    def frost_damage(c):
        if c.draw_group is None or c.draw_group.reward.kind!=FROST_FOLLOWUP:
            raise TargetValidationError('Frigidara lost its complete qualified original two-spell group')
        packets=tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)for i in characters(c,registry,3-c.player_id))
        return(DamageBatch(packets),)if packets else()
    def varian(c):
        slots=tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)),current_keywords_all=(key,))for key in TUTOR_KEYWORDS)
        reward=DrawGroupReward(SOURCE_KEYWORDS,source=BoardPresenceReference.capture(c.state,c.source_id))if living_source(c)else DrawGroupReward()
        return(DrawPhysicalGroup(c.player_id,c.source_id,slots,reward),)
    def ashmore(c):
        slots=(DrawGroupSlot(PoolQuery(),current_keywords_all=(Keyword.RUSH,)),
            DrawGroupSlot(PoolQuery(),current_keywords_all=(Keyword.LIFESTEAL,)),DrawGroupSlot(PoolQuery(),current_deathrattle=True))
        return(DrawPhysicalGroup(c.player_id,c.source_id,slots),)
    def ras(c):
        packets=tuple(Damage(i,1,c.source_id,DamageKind.MINION_ABILITY,affected_by_spell_damage=True)
            for i in characters(c,registry,3-c.player_id))
        return(DamageBatch(packets),)if packets else()
    bodies={TYRANT:lambda c:source_buff(c,7,7)if c.state.players[c.player_id].max_mana>=10 else(),OZRUK:ozruk,
        TURALYON:turalyon,YIP:yip,CATRINA:catrina,FRIGIDARA:frigidara,'frost_damage':frost_damage,
        SESELI:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),),
            DrawGroupReward('cost_drawn_minions',8)),),VARIAN:varian,ASHMORE:ashmore,RAS:ras}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
