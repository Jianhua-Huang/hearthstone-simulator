"""Norgannon's printed values compose native power, future tax and real casts."""
import hashlib,json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier,Damage
from hs_sim.engine.minion_ability_power import DoubleRemainingMinionAbilities,MinionAbilityPowerProfile,value
from hs_sim.engine.model import (ActivatedAbilitySpec,CardDefinition,CardType,CostSpec,DamageKind,
    Keyword,PlayerEffectSpec,TargetSpec,TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect,ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .simple_followup_p54_cards import SECRET_QUERY

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/norgannon-native-power-v1.json'
BATCH_HASH='b68104e0784b4adffe4db26631b0557b429a4c31f7f23f3557e4063232c738a5'
NORGANNON='TTN_075';SKILLS=('TTN_075t','TTN_075t2','TTN_075t3')
ROOTS=(NORGANNON,);DEPENDENCIES=SKILLS;COLLECTIBLE_ROOTS=()
EVIDENCE=('TTN_075e','TTN_075t2e','TTN_075t2e2','TTN_075t3e','TTN_075t3e2')
PREFIX='cards.norgannon_native_power.';PROFILE=PREFIX+'remaining';POOL='constructed.cards'
BASE_VALUES=tuple(zip(SKILLS,(5,1,1)))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or
            tuple(r['record']['id']for r in d['cards'])!=ROOTS or
            tuple(r['record']['id']for r in d['dependencies'])!=SKILLS or
            tuple(r['record']['id']for r in d['evidence_only'])!=EVIDENCE or
            tuple(d['choice_only_ids'])!=SKILLS or tuple(map(tuple,d['printed_base_values']))!=BASE_VALUES or
            any(d[k]for k in('existing_dependencies','new_token_ids','source_scope_bound','formal_pool_complete',
                'cn_calibrated','real_excavate_profile_bound'))or len(d['official_observations'])!=8 or
            any(canonical_digest(r['record'])!=r['record_sha256']for key in('cards','dependencies','evidence_only')for r in d[key])):
        raise TargetValidationError('Norgannon requires complete original native values and face roles')
    for ref in d['references']:
        if hashlib.sha256((ROOT/ref['path']).read_bytes()).hexdigest()!=ref['sha256']:
            raise TargetValidationError('Norgannon changed a complete shared source reference')
    return d


def register_norgannon_native_power(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        raw=row['record'];cid=raw['id'];kind=CardType[raw['type']];extra={}
        if cid in registry.cards:raise TargetValidationError('Norgannon cannot overwrite an existing face')
        if cid==NORGANNON:
            if kind!=CardType.MINION or (raw['cost'],raw['attack'],raw['health'])!=(6,3,8) or raw['tags'].get('TITAN')!=1 or not raw['collectible']:
                raise TargetValidationError('Norgannon lost its original native Titan body')
            extra.update(keywords=(Keyword.TITAN,),activated_abilities=tuple(ActivatedAbilitySpec(
                skill,PREFIX+skill,card_id=skill,targeting=TargetSpec()if skill==SKILLS[0]else None)for skill in SKILLS),
                triggers=(TriggerSpec('minion_ability_used',PREFIX+'after'),))
        else:
            if (kind!=CardType.SPELL or raw['cost']is not None or raw['collectible']or
                    raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')!=dict(BASE_VALUES)[cid]):
                raise TargetValidationError('Norgannon descriptor lost its explicit original script base value')
            extra['choice_only']=True
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost']or 0,attack=raw['attack']or 0,
            health=raw['health']or 0,metadata=metadata_from_record(raw),**extra)
        registry._validate_card(card)
        if cid==NORGANNON and cid in registry.pool_cards and registry.pool_card(cid)!=PoolCard.from_definition(card):
            raise TargetValidationError('Norgannon changed original printed pool metadata')
        prepared.append(card)
    if any(r['record']['type']!='ENCHANTMENT'for r in d['evidence_only']):
        raise TargetValidationError('Norgannon evidence enchantments cannot become executable skills')

    def after(c):
        if c.event.source_id!=c.source_id or dict(c.event.data).get('ability_id')not in SKILLS:return ()
        return(DoubleRemainingMinionAbilities(PROFILE,MinionReference.capture(c.source),c.event),)
    registry.register_behavior(PREFIX+'after',after)
    registry.register_behavior(PREFIX+SKILLS[0],lambda c:(Damage(c.target_id,
        value(registry,c.source,SKILLS[0]),c.source_id,DamageKind.MINION_ABILITY),))
    registry.register_behavior(PREFIX+SKILLS[1],lambda c:(AddPlayerEffect(3-c.player_id,
        PREFIX+'tax'+str(value(registry,c.source,SKILLS[1])),c.source_id),))
    registry.register_behavior(PREFIX+SKILLS[2],lambda c:(CastFromPool(c.player_id,POOL,SECRET_QUERY,
        count=value(registry,c.source,SKILLS[2]),source_id=c.source_id),))
    def tax(c,amount):
        if c.event.player_id!=c.player_id:return ()
        return(ConsumePlayerEffect(c.player_id,c.player_effect,(
            AddCostModifier(c.player_id,CostSpec(delta=amount),source_id=c.source_id,expires_turn=c.state.turn),)),)
    for amount in(1,2,4):registry.register_behavior(PREFIX+'apply_tax'+str(amount),lambda c,amount=amount:tax(c,amount))
    for card in prepared:
        registry.register_card(card)
        if card.id not in SKILLS and card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    for amount in(1,2,4):registry.register_player_effect(PlayerEffectSpec(
        PREFIX+'tax'+str(amount),NORGANNON,triggers=(TriggerSpec('turn_started',PREFIX+'apply_tax'+str(amount)),)))
    registry.register_minion_ability_power_profile(MinionAbilityPowerProfile(PROFILE,NORGANNON,PREFIX+'after',BASE_VALUES))
