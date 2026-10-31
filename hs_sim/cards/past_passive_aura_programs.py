"""Actual past providers and permanent programs, preserving full source identities."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier,AddToHand
from hs_sim.engine.model import (CardAbilityCondition,CardDefinition,CardType,CostAuraSpec,CostSpec,
    Keyword,KeywordAuraSpec,PlayerAuraSpec,PlayerEffectSpec,SpellSchool,TriggerSpec)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-passive-aura-programs-v1.json'
BATCH_HASH='9f448c2276772d34dd6293fd9c759e69739a7079f0607ef2510df5c0af7b5187'
GLINDA,AVIANA,HALL,WON_HALL,POPGAR,THEO,KAEL,TOPIOR,ELIZA,INZAH=ROOTS=(
    'GIL_618','GIL_800','OG_209','WON_336','WW_091','WW_430','REV_021','REV_314','VAC_426','ETC_371')
WHELP='REV_314t';SLUDGE='WW_044t'
DEPENDENCIES=(WHELP,)
EXISTING=(SLUDGE,)
EVIDENCE=('MIS_701',)
PREFIX='cards.past_passive_aura_programs.'
TOPIOR_PROGRAM=PREFIX+'topior_program';ELIZA_PROGRAM=PREFIX+'eliza_program'


def make_definition(raw):
    cid=raw['id']
    if cid not in ROOTS+DEPENDENCIES or raw['type']!='MINION'or any(type(raw[k])is not int for k in('cost','attack','health')):
        raise TargetValidationError('Passive/program consumers require full actual minion faces')
    fields={};meta=metadata_from_record(raw)
    if cid==GLINDA:fields['keyword_auras']=(KeywordAuraSpec(Keyword.ECHO,'friendly_hand_minions'),)
    if cid==AVIANA:fields['cost_auras']=(CostAuraSpec(CostSpec(set_to=0),relation='any_first_card',first_per_turn=True),)
    if cid in(HALL,WON_HALL):fields.update(spell_damage=1,keyword_auras=(KeywordAuraSpec(Keyword.LIFESTEAL,'friendly_spells'),))
    if cid==POPGAR:fields.update(battlecry=PREFIX+cid,keyword_auras=(KeywordAuraSpec(Keyword.LIFESTEAL,'friendly_fel_spells'),),
        cost_auras=(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.SPELL,),ability=CardAbilityCondition('fel_spell',basis='printed'))),))
    if cid==THEO:fields['cost_auras']=(CostAuraSpec(CostSpec(delta=-4,minimum=1),relation='friendly_outside_starting_deck'),)
    if cid==KAEL:fields['cost_auras']=(CostAuraSpec(CostSpec(set_to=0,card_types=(CardType.MINION,)),every_nth_per_turn=3),)
    if cid in(TOPIOR,INZAH):fields['battlecry']=PREFIX+cid
    if cid==ELIZA:fields['deathrattle']=PREFIX+cid
    if cid==WHELP:
        if(raw['dbf_id'],raw['cost'],raw['attack'],raw['health'],raw['collectible'],raw['tags'].get('RUSH'),raw['tags'].get('WHELP'))!=(77703,3,3,3,False,1,1):
            raise TargetValidationError('Topior requires its exact actual Rush Whelp')
        fields['keywords']=(Keyword.RUSH,)
        if'whelp'not in meta.subtypes:meta=replace(meta,subtypes=meta.subtypes+('whelp',))
    return CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=meta,**fields)


def programs():
    return(PlayerEffectSpec(TOPIOR_PROGRAM,TOPIOR,triggers=(TriggerSpec('spell_cast_finished',PREFIX+'nature'),)),
        PlayerEffectSpec(ELIZA_PROGRAM,ELIZA,auras=(PlayerAuraSpec(attack=1),)))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=26 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Passive/program consumers changed full roles or claimed full support')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']+d['overload_identity_records']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete passive/program original row')
    if(tuple(x['record']['id']for x in d['overload_identity_records'])!=tuple(d['overload_card_ids'])or len(d['overload_card_ids'])!=98 or
            any(type(x['record']['tags'].get('OVERLOAD'))is not int or x['record']['tags']['OVERLOAD']<=0 for x in d['overload_identity_records'])or
            [canonical_digest(asdict(p))for p in programs()]!=d['program_sha256']):
        raise TargetValidationError('Permanent consumers lost full original identity predicates or program declarations')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(
            x['record']!=rows[x['record']['id']]for x in d['cards']):raise TargetValidationError('Cropped full past reference')
    return d


def register_past_passive_aura_programs(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']:
            raise TargetValidationError('Popgar changed the exact existing Barrel of Sludge')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']:
            raise TargetValidationError('Passive/program consumers replaced or changed an existing face')
        registry._validate_card(card);prepared.append(card)
    def nature(c):
        if c.event is None or c.event.kind!='spell_cast_finished'or c.player_effect is None or c.player_effect.spec_id!=TOPIOR_PROGRAM:
            raise ValueError('Topior requires its actual original player-program CAST notification')
        cast=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(cast.player_id!=c.player_id or registry.card(cast.card_id).spell_school!=SpellSchool.NATURE or not cast.completed or
                not cast.payload_started or cast.interrupted or cast.failure is not None):return()
        return(SummonByCard(c.player_id,(SummonEntryMaterial(WHELP),),SummonCause.capture(c)),)
    bodies={POPGAR:lambda c:(AddToHand(c.player_id,SLUDGE,c.source_id),AddToHand(c.player_id,SLUDGE,c.source_id)),
        TOPIOR:lambda c:(AddPlayerEffect(c.player_id,TOPIOR_PROGRAM,c.source_id),),
        ELIZA:lambda c:(AddPlayerEffect(c.player_id,ELIZA_PROGRAM,c.source_id),),
        INZAH:lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-1,card_ids=tuple(d['overload_card_ids'])),source_id=c.source_id),)}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    registry.register_behavior(PREFIX+'nature',nature)
    for p in programs():registry.register_player_effect(p)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
