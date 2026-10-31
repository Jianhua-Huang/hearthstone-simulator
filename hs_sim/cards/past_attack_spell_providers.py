"""Actual native combat, spell providers and original permanent/stored grants."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.character_attacks import completed_attack
from hs_sim.engine.effects import Damage,DamageBatch,ReturnToHand
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,HealthFlow,Keyword,
    KeywordAuraSpec,PlayerAuraSpec,PlayerEffectSpec,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.stored_spell_damage import GrantStoredSpellDamage
from hs_sim.engine.successful_summons import GrantSummonedKeyword
from hs_sim.engine.zones import CardReference
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-attack-spell-providers-v1.json'
BATCH_HASH='257d3610af2b536950b201e2fb007739000075e19024fae72d79ef6bec144ab8'
SLATE,KREE,REAPER,NORALIA,RISA,KNUCKLES,STONE,LOTH,SARUUN,HALDURON=ROOTS=(
    'SCH_539','SCH_538','GVG_113','TOY_100','JAM_019','CFM_333','REV_921','DMF_240','GDB_304','RLK_820')
DEPENDENCIES=()
EXISTING=('CS2_101t',)
EVIDENCE=('MIS_701',)
PREFIX='cards.past_attack_spell_providers.'
STONE_PROGRAM=PREFIX+'stone_program';LOTH_PROGRAM=PREFIX+'loth_program'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS or raw['type']!='MINION'or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Attack/spell consumers require their complete original minion faces')
    fields={}
    if cid==SLATE:fields['keyword_auras']=(KeywordAuraSpec(Keyword.POISONOUS,'friendly_spells'),)
    if cid==KREE:fields['keyword_auras']=tuple(KeywordAuraSpec(Keyword.IMMUNE_WHILE_ATTACKING,target)
        for target in('friendly_hero','friendly_minions'))
    if cid in(REAPER,NORALIA):fields['cleave']=True
    if cid in(NORALIA,RISA):fields['keywords']=(Keyword.RUSH,)
    if cid==NORALIA:fields['deathrattle']=PREFIX+cid
    if cid==RISA:fields['triggers']=(TriggerSpec('attack_finished',PREFIX+cid),)
    if cid==KNUCKLES:fields['triggers']=(TriggerSpec('health_resolved',PREFIX+cid),)
    if cid in(STONE,LOTH,SARUUN,HALDURON):fields['battlecry']=PREFIX+cid
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**fields)


def programs():
    return(PlayerEffectSpec(STONE_PROGRAM,STONE,auras=(PlayerAuraSpec(attack=2,scope='active_board_totems'),)),
        PlayerEffectSpec(LOTH_PROGRAM,LOTH,triggers=(TriggerSpec('minion_summoned',PREFIX+'recruit'),)))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=24 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Attack/spell source roles or completeness claims changed')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']+d['silver_hand_identity_records']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete attack/spell source row')
    if(tuple(x['record']['id']for x in d['silver_hand_identity_records'])!=tuple(d['silver_hand_recruit_ids'])or
            any(x['record']['type']!='MINION'or x['record']['tags'].get('3444')!=1 for x in d['silver_hand_identity_records'])or
            [canonical_digest(asdict(p))for p in programs()]!=d['program_sha256']):
        raise TargetValidationError('Changed original Silver Hand identity predicate or permanent program')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):raise TargetValidationError('Cropped full past source')
    return d


def register_past_attack_spell_providers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        metadata_pin=row['pool_card_sha256']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                (cid in registry.pool_cards if metadata_pin is None else
                 canonical_digest(asdict(registry.pool_card(cid)))!=metadata_pin)):
            raise TargetValidationError('Permanent Recruit program changed its exact existing token')
    for row in d['cards']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Attack/spell consumers replaced or changed an existing face')
        registry._validate_card(card);prepared.append(card)
    def risa(c):
        row=completed_attack(c)
        if(row is None or not living_source(c)or row.source_kind!=CardType.HERO or row.combat.player_id!=c.player_id):return()
        return(ReturnToHand(c.source_id,cost=CostSpec(set_to=1)),)
    def knuckles(c):
        result=c.health_result
        if(result is None or result.flow!=HealthFlow.DAMAGE.value or result.damage_kind!=DamageKind.COMBAT.value or
                result.source_id!=c.source_id):return()
        rows=[row for row in c.state.character_attack_history if row.combat is not None and row.terminal is None and
            row.declaration.source_id==c.source_id and row.delivery.target_id==result.original_target_id and
            (row.combat.source_zone_epoch,row.combat.source_entered_order)==(result.source_zone_epoch,result.source_entered_order)and
            row.combat.event_cursor<result.batch_id and registry.card(row.combat.target_card_id).kind==CardType.MINION]
        if not rows:return()
        if len(rows)!=1:raise ValueError('Knuckles lost its unique original attacking combat packet')
        return(Damage(c.state.players[3-c.player_id].hero_id,c.source.attack,c.source_id,DamageKind.MINION_ABILITY),)
    def recruit(c):
        if(c.event is None or c.event.kind!='minion_summoned'or c.player_effect is None or c.player_effect.spec_id!=LOTH_PROGRAM):
            raise ValueError('Recruit shield requires its actual installed player-program event')
        rows=[r for r in c.state.successful_summon_history if r.event_sequence==c.event.sequence]
        if len(rows)!=1:raise ValueError('Recruit shield lost its original successful summon')
        row,=rows
        if(row.entity_id,row.player_id,row.action)!=(c.event.target_id,c.event.player_id,c.event.action):
            raise ValueError('Recruit shield borrowed another physical entry')
        return(GrantSummonedKeyword(c.player_id,row.id,c.source_id,Keyword.DIVINE_SHIELD),)if(
            row.player_id==c.player_id and row.card_id in d['silver_hand_recruit_ids'])else()
    def saruun(c):
        refs=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck
            if c.state.entities[i].kind==CardType.MINION and has_any_tribe(registry,c.state.entities[i],('elemental',),basis='current'))
        return tuple(GrantStoredSpellDamage(ref,1,c.source_id,schools=(SpellSchool.FIRE,))for ref in refs)
    def halduron(c):
        p=c.state.players[c.player_id]
        return tuple(GrantStoredSpellDamage(CardReference.capture(c.state.entities[i]),1,c.source_id)
            for i in(*p.hand,*p.deck)if c.state.entities[i].kind==CardType.SPELL and
            registry.card(c.state.entities[i].card_id).spell_school==SpellSchool.ARCANE)
    def noralia(c):
        p=c.state.players[3-c.player_id]
        return(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)for i in(p.hero_id,*p.board)
            if c.state.entities[i].is_character and c.state.entities[i].active and c.state.entities[i].health>0 and not c.state.entities[i].doomed)),)
    bodies={RISA:risa,KNUCKLES:knuckles,NORALIA:noralia,STONE:lambda c:(AddPlayerEffect(c.player_id,STONE_PROGRAM,c.source_id),),
        LOTH:lambda c:(AddPlayerEffect(c.player_id,LOTH_PROGRAM,c.source_id),),SARUUN:saruun,HALDURON:halduron}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    registry.register_behavior(PREFIX+'recruit',recruit)
    for p in programs():registry.register_player_effect(p)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
