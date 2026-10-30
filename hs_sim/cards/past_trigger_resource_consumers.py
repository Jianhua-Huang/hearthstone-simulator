"""Actual turn, attack and resource consumers with the complete invention set."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import (Buff,ChoiceOption,Damage,DamageBatch,Destroy,Draw,EquipWeapon,
    ForceAttack,GrantSpellDamage,Heal,ModifyWeapon,RandomBuff,RefreshMana,Transform)
from hs_sim.engine.equipment import EquippedWeaponReference,equipped_weapon
from hs_sim.engine.health_outcomes import health_result,is_overkill
from hs_sim.engine.minion_type_history import submitted_minion_types
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,DamageKind,EndTurnSpec,
    HealingKind,Keyword,LimitedTriggerSpec,TriggerSpec,Zone)
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import CardReference,DiscardCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-trigger-resource-consumers-v1.json'
BATCH_HASH='aab66997267b4b67cb20e1e8e05da8ce1693cc801f169619695656cc78af5371'
GREEN,PROFESSOR,CORNELIUS,OMU,DRED,FLURGL,NAT,LEOROXX,OONDASTA,KRYXIS,VEREESA,GELBIN=ROOTS=(
    'NEW1_024','SCH_425','SW_080','SCH_614','UNG_919','BAR_860','OG_338','BT_214','TRL_542','REV_510','DAL_379','EX1_112')
WEAPON,EMBOLDENER,CHICKEN_BOT,REPAIR,POULTRYIZER,CHICKEN=DEPENDENCIES=(
    'DAL_379t','Mekka3','Mekka1','Mekka2','Mekka4','Mekka4t')
INVENTIONS=(EMBOLDENER,CHICKEN_BOT,REPAIR,POULTRYIZER)
NORMALIZATIONS={cid:{'attack':0}for cid in INVENTIONS}|{CHICKEN:{'cost':0}}
PREFIX='cards.past_trigger_resource.'


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower());norm=NORMALIZATIONS.get(cid,{})
    if cid not in(*ROOTS,*DEPENDENCIES)or kind not in(CardType.MINION,CardType.WEAPON):
        raise TargetValidationError('Trigger/resource consumer lost its complete original face')
    cost=raw['cost']if raw['cost']is not None else norm.get('cost')
    attack=raw['attack']if raw['attack']is not None else norm.get('attack')
    if type(cost)is not int or type(attack)is not int or type(raw['health'])is not int:
        raise TargetValidationError('Trigger/resource requires reviewed complete numeric bases')
    fields={};keywords=tuple(k for tag,k in(('RUSH',Keyword.RUSH),('SPELLBURST',Keyword.SPELLBURST))if raw['tags'].get(tag)==1)
    if cid in(GREEN,LEOROXX,KRYXIS,VEREESA,GELBIN):fields['battlecry']=PREFIX+cid
    if cid==KRYXIS:fields['deathrattle']=PREFIX+'draw_three'
    if cid==OMU:fields['limited_triggers']=(LimitedTriggerSpec.spellburst(PREFIX+cid),)
    if cid==PROFESSOR:fields['triggers']=(TriggerSpec('attack_declared',PREFIX+cid),)
    if cid==CORNELIUS:fields['triggers']=(TriggerSpec('turn_started',PREFIX+'draw_one'),
        TriggerSpec('turn_ended',PREFIX+'draw_one',EndTurnSpec('either')))
    if cid in(DRED,FLURGL):fields['triggers']=(TriggerSpec('card_played',PREFIX+cid),)
    if cid==OONDASTA:fields['triggers']=(TriggerSpec('health_resolved',PREFIX+cid),)
    if cid==WEAPON:fields['triggers']=(TriggerSpec('attack_finished',PREFIX+cid),)
    if cid in(NAT,CHICKEN_BOT,POULTRYIZER):fields['triggers']=(TriggerSpec('turn_started',PREFIX+cid),)
    if cid in(EMBOLDENER,REPAIR):fields['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec('controller')),)
    return CardDefinition(cid,raw['name'],kind,cost=cost,attack=attack,
        health=raw['health']if kind==CardType.MINION else 0,metadata=metadata_from_record(raw),keywords=keywords,
        **(dict(durability=raw['health'])if kind==CardType.WEAPON else{}),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            d['numeric_normalizations']!=NORMALIZATIONS or len(d['official_observations'])!=38 or
            tuple(d['invention_members'])!=INVENTIONS or d['invention_weights']!=[1,1,1,1]or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Trigger/resource batch lost complete roles, weights or source evidence')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[group]):
            raise TargetValidationError('Trigger/resource changed a complete original raw record')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Trigger/resource changed its complete original reference')
    ref=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Trigger/resource cropped complete past membership')
    return d


def register_past_trigger_resource_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Trigger/resource changed an existing shared definition')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Trigger/resource cannot replace or alter an existing face')
        registry._validate_card(card);prepared.append(card)
    def weapon_buff(c):
        weapon=equipped_weapon(c.state,c.state.players[c.player_id])
        return()if weapon is None else(ModifyWeapon(EquippedWeaponReference.capture(weapon),1,1,c.source_id),)
    def recruit(c,count):return(SummonFromZone(c.player_id,count=count,zone=Zone.HAND,
        query=PoolQuery(tribes_any=('beast',)),source_id=c.source_id,cause=SummonCause.capture(c)),)
    def original_play(c):
        row=play_record(c.state,dict(c.event.data)['play_id'])
        if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
            raise TargetValidationError('Trigger consumer lost its original completed physical play')
        return row
    def dred(c):
        row=original_play(c);target=c.state.entities.get(row.source_id)
        if(row.kind!=CardType.MINION or row.player_id==c.player_id or not living_source(c)or target is None or
                target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed):return()
        return(ForceAttack(BoardPresenceReference.capture(c.state,c.source_id),BoardPresenceReference.capture(c.state,target.id)),)
    def characters(c,player):
        ids=(c.state.players[player].hero_id,*minions(c,registry,player))
        return tuple(i for i in ids if c.state.entities[i].active and c.state.entities[i].health>0 and not c.state.entities[i].doomed)
    def flurgl(c):
        row=original_play(c)
        if(row.kind!=CardType.MINION or row.player_id!=c.player_id or row.source_id==c.source_id or not living_source(c)):return()
        types=submitted_minion_types(row)
        if types is None or not types.matches_any(('murloc',)):return()
        packets=tuple(Damage(i,1,c.source_id,DamageKind.MINION_ABILITY)for i in characters(c,3-c.player_id))
        return(DamageBatch(packets),)if packets else()
    def nat(c):
        if c.event.player_id==c.player_id:return()
        return(ChooseRandomEffects(c.player_id,c.source_id,(ChoiceOption('draw','Extra draw',(
            Draw(3-c.player_id,1,c.source_id),)),ChoiceOption('none','No extra draw'))),)
    def oondasta(c):
        result=health_result(c.event)
        return recruit(c,1)if(result is not None and result.target_kind==CardType.MINION.value and is_overkill(c.event,c.source_id))else()
    def thoridal(c):
        row=completed_attack(c)
        if(row is None or row.source_kind!=CardType.HERO or row.declaration.player_id!=c.player_id or
                row.combat is None or row.combat.weapon_id!=c.source_id):return()
        return(GrantSpellDamage(c.state.players[c.player_id].hero_id,2,c.source_id,expires_turn=c.state.turn),)
    def all_minions(c):return tuple(i for p in(1,2)for i in minions(c,registry,p))
    def random_effect(c,ids,effect):
        options=tuple(ChoiceOption(str(i),registry.card(c.state.entities[i].card_id).name,(effect(i),))for i in ids)
        return(ChooseRandomEffects(c.player_id,c.source_id,options),)if options else()
    def start(c,key):
        if c.event.player_id!=c.player_id:return()
        if key==CHICKEN_BOT:return(Destroy(c.source_id,c.source_id),Draw(c.player_id,3,c.source_id))
        return random_effect(c,all_minions(c),lambda i:Transform(i,CHICKEN))
    def repair(c):
        ids=tuple(i for p in(1,2)for i in characters(c,p)if c.state.entities[i].health<c.state.entities[i].max_health)
        return random_effect(c,ids,lambda i:Heal(i,6,c.source_id,HealingKind.EFFECT))
    def discard(c):return tuple(DiscardCard(CardReference.capture(c.state.entities[i]),c.source_id)
        for i in tuple(c.state.players[c.player_id].hand))
    bodies={GREEN:weapon_buff,PROFESSOR:lambda c:weapon_buff(c)if c.event.source_id==c.source_id else(),
        'draw_one':lambda c:(Draw(c.player_id,1,c.source_id),),'draw_three':lambda c:(Draw(c.player_id,3,c.source_id),),
        OMU:lambda c:(RefreshMana(c.player_id,c.state.players[c.player_id].max_mana),),DRED:dred,FLURGL:flurgl,NAT:nat,
        LEOROXX:lambda c:recruit(c,3),OONDASTA:oondasta,KRYXIS:discard,VEREESA:lambda c:(EquipWeapon(c.player_id,WEAPON),),
        WEAPON:thoridal,GELBIN:lambda c:(SummonByCard(c.player_id,tuple(SummonEntryMaterial(cid)for cid in INVENTIONS),
            SummonCause.capture(c),selection='random'),),
        EMBOLDENER:lambda c:(RandomBuff(all_minions(c),1,1,c.source_id),)if all_minions(c)else(),
        CHICKEN_BOT:lambda c:start(c,CHICKEN_BOT),REPAIR:repair,POULTRYIZER:lambda c:start(c,POULTRYIZER)}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
