"""Real past Legendary static providers; execution remains in shared kernels."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.model import (AttackPolicySpec,AuraSpec,CardDefinition,CardType,CostAuraSpec,CostSpec,
    HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,KeywordAuraSpec,StatRelationLayer,StatRelationOperand,StatRelationSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-static-providers-v1.json'
BATCH_HASH='4b38699090b72aefe06ad9a4450137897b2921dc403816610dcdac2cce6f5e9c'
ROOTS=('AT_045','WON_012','DAL_726','WC_006','BT_187','DED_006','EX1_062','DMF_708','BOT_236','YOP_035')


def declarations(cid):
    if cid in ROOTS[:2]:return dict(cost_auras=(CostAuraSpec(CostSpec(set_to=1,card_types=(CardType.MINION,))),))
    if cid=='DAL_726':return dict(cost_auras=(CostAuraSpec(CostSpec(set_to=1,card_types=(CardType.MINION,)),tribes_any=('murloc',)),))
    if cid=='WC_006':return dict(cost_auras=(CostAuraSpec(CostSpec(delta=-2,card_types=(CardType.SPELL,)),relation='friendly_nature_spells'),))
    if cid=='BT_187':return dict(keywords=(Keyword.CHARGE,),attack_policies=(AttackPolicySpec('friendly_ignore_taunt'),))
    if cid=='DED_006':return dict(keyword_auras=(KeywordAuraSpec(Keyword.CHARGE,'friendly_minions',include_self=True,tribes_any=('pirate',)),))
    if cid=='EX1_062':return dict(keywords=(Keyword.CHARGE,),stat_relations=(StatRelationSpec(
        operand=StatRelationOperand.OTHER_BATTLEFIELD_TRIBE_COUNT,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=1,count_tribe='murloc'),))
    if cid=='DMF_708':return dict(auras=(AuraSpec(attack=2,target='friendly_hero',condition='controller_turn'),),
        keyword_auras=(KeywordAuraSpec(Keyword.WINDFURY,'friendly_hero',condition='controller_turn'),))
    if cid=='BOT_236':return dict(keywords=(Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL),
        health_rules=(HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly'),))
    if cid=='YOP_035':return dict(health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.CAP,1,layer=HealthLayer.TARGET,target_relation='self'),))
    raise TargetValidationError('Unreviewed original Legendary static provider')


def make_definition(raw):
    if (raw['id']not in ROOTS or raw['type']!='MINION'or raw['collectible']is not True or raw['tags'].get('RARITY')!=5 or
            any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Static providers require complete original Legendary minion faces')
    return CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),**declarations(raw['id']))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-past-Legendary-static-providers-v1'or
            tuple(x['record']['id']for x in d['cards'])!=ROOTS or d['dependencies']or
            [x['record']['id']for x in d['existing_dependencies']]!=['TIME_013','CORE_BT_187','EX1_350']or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=24 or
            any(d[k]for k in('complete_past_legendary_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Static providers lost original source roles or claimed a partial domain complete')
    for row in d['cards']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Static provider lost a full original source row')
    p=(ROOT/d['full_reference_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Static providers changed the full original past reference')
    ref=json.loads(p.read_text(encoding='utf8'));records={x['record']['id']:x['record']for x in ref['candidate_records']}
    if len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or any(x['record']!=records[x['record']['id']]for x in d['cards']):
        raise TargetValidationError('Static providers cropped or changed original complete membership')
    return d


def register_past_legendary_static_providers(registry):
    cards=[]
    for row in load_batch()['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Static providers cannot replace or change existing complete faces')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Static provider changed existing complete metadata')
        cards.append(card)
    for card in cards:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
