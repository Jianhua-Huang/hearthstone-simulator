"""Golganneth and Amitus compose existing native value, aura and draw effects."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import Buff,Damage,DamageBatch,Heal,HealBatch,InvokeBehavior,SetStats
from hs_sim.engine.model import (ActivatedAbilitySpec,CardDefinition,CardType,CostAuraSpec,CostSpec,
    DamageKind,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,TargetSpec,Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions
from .past_one_cost_spell_consumer_cards import load_batch as overload_facts

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/titan-value-effects-v1.json'
BATCH_HASH='3f948073666a3ff69736ff8d4dbf6139d0a08983e2658e017bf1c4bb6c0ebf54'
GOLG,AMITUS='TTN_800','TTN_858'
GOLG_SKILLS=('TTN_800t','TTN_800t2','TTN_800t3')
AMITUS_SKILLS=('TTN_858t1','TTN_858t2','TTN_858t3')
ROOTS=(GOLG,AMITUS);SKILLS=GOLG_SKILLS+AMITUS_SKILLS
DEPENDENCIES=SKILLS;COLLECTIBLE_ROOTS=()
PREFIX='cards.titan_values.'
FIRST=CostAuraSpec(CostSpec(delta=-3,card_types=(CardType.SPELL,)),first_per_turn=True)
CAP=HealthRule(HealthFlow.DAMAGE,HealthOp.CAP,2,layer=HealthLayer.TARGET,
    target_relation='friendly',target_kinds=(CardType.MINION,))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=SKILLS or
            tuple(d['choice_only_ids'])!=SKILLS or any(d[k]for k in('existing_dependencies','evidence_only','new_token_ids',
                'source_scope_bound','formal_pool_complete','cn_calibrated','real_excavate_profile_bound')) or
            len(d['official_observations'])!=16 or
            any(canonical_digest(r['record'])!=r['record_sha256']for r in d['cards']+d['dependencies'])):
        raise TargetValidationError('Titan values require their complete original faces and unchanged roles')
    for ref in d['references']:
        if hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise TargetValidationError('Titan values changed their complete original shared reference')
    return d


def register_titan_values(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Titan values cannot overwrite an existing face')
        if cid in ROOTS:
            expected=(6,5,7)if cid==GOLG else(7,1,8)
            if (raw['cost'],raw['attack'],raw['health'])!=expected or raw['tags'].get('TITAN')!=1 or not raw['collectible']:
                raise TargetValidationError('Titan value source lost its true printed body')
            skills=GOLG_SKILLS if cid==GOLG else AMITUS_SKILLS
            extra.update(keywords=(Keyword.TITAN,)if cid==GOLG else(Keyword.TITAN,Keyword.TAUNT),
                activated_abilities=tuple(ActivatedAbilitySpec(skill,PREFIX+skill,card_id=skill,
                    targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if skill==GOLG_SKILLS[1]else None)
                    for skill in skills))
            extra.update(cost_auras=(FIRST,))if cid==GOLG else extra.update(health_rules=(CAP,))
        else:
            if kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']:
                raise TargetValidationError('Titan skills require nonphysical zero-cost descriptions')
            extra['choice_only']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid not in SKILLS and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Titan values differ from original printed pool metadata')
        prepared.append(card)
    overload=tuple(overload_facts()['printed_overload_ids'])
    def storm(c):
        targets=(c.state.players[3-c.player_id].hero_id,)+minions(c,registry,3-c.player_id)
        return(DamageBatch(tuple(Damage(i,3,c.source_id,DamageKind.MINION_ABILITY)for i in targets)),
            InvokeBehavior(PREFIX+'heal',c.source_id,c.player_id))
    def heal(c):
        targets=(c.state.players[c.player_id].hero_id,)+minions(c,registry,c.player_id)
        return(HealBatch(tuple(Heal(i,6,c.source_id)for i in targets)),)
    bodies={GOLG_SKILLS[0]:storm,'heal':heal,
        GOLG_SKILLS[1]:lambda c:(Damage(c.target_id,20,c.source_id,DamageKind.MINION_ABILITY),),
        GOLG_SKILLS[2]:lambda c:(DrawMatching(c.player_id,PoolQuery(card_ids=overload),'skip',count=3,source_id=c.source_id),),
        AMITUS_SKILLS[0]:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),)*2,DrawGroupReward('set_stats_cost_all',2)),),
        AMITUS_SKILLS[1]:lambda c:tuple(Buff(i,2,2,c.source_id)for i in minions(c,registry,c.player_id)if i!=c.source_id),
        AMITUS_SKILLS[2]:lambda c:tuple(SetStats(i,2,2,c.source_id)for i in minions(c,registry,3-c.player_id)),}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
