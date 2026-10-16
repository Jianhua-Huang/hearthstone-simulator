"""Complete native providers expressed solely by existing public declarations."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import (AuraSpec,CardDefinition,CardType,HealthFlow,HealthLayer,
    HealthOp,HealthRule,Keyword,StatRelationLayer,StatRelationOperand,StatRelationSpec,SummonQuantitySpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/static-provider-effects-v1.json'
BATCH_HASH='00d6fc4d8f87370353ee7e7c0b5069e66eefdedcfa9166e6cb542ccab6e51fc2'


def conditional_attack(operand,amount):
    return (StatRelationSpec(operand=operand,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=amount),)


DECLARATIONS={
    'rush':dict(keywords=(Keyword.RUSH,)),
    'stealth_spell_damage_1':dict(keywords=(Keyword.STEALTH,),spell_damage=1),
    'spell_damage_2':dict(spell_damage=2),
    'charge_damaged_attack_6':dict(keywords=(Keyword.CHARGE,),
        stat_relations=conditional_attack(StatRelationOperand.SELF_DAMAGED,6)),
    'taunt_damaged_attack_3':dict(keywords=(Keyword.TAUNT,),
        stat_relations=conditional_attack(StatRelationOperand.SELF_DAMAGED,3)),
    'weapon_attack_2':dict(stat_relations=conditional_attack(StatRelationOperand.CONTROLLER_HAS_WEAPON,2)),
    'murloc_attack_2':dict(auras=(AuraSpec(attack=2,tribes_any=('murloc',)),)),
    'pirate_stats_1':dict(auras=(AuraSpec(attack=1,health=1,tribes_any=('pirate',)),)),
    'cleave':dict(cleave=True),
    'card_summons_double':dict(summon_quantities=(SummonQuantitySpec(),)),
    'self_damage_plus_1':dict(keywords=(Keyword.TAUNT,),health_rules=(HealthRule(
        HealthFlow.DAMAGE,HealthOp.ADD,1,layer=HealthLayer.TARGET,target_relation='self',target_kinds=(CardType.MINION,)),)),
}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Static-provider reviewed source pin changed')
    return data


def register_static_provider_cards(registry):
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if (raw['type']!='MINION' or raw['collectible']is not True or
                canonical_digest(raw)!=row['record_sha256'] or
                set(recipe)!={'profile','cost','attack','health','deck_identity'} or
                recipe['profile']not in DECLARATIONS or any(raw[k]!=recipe[k]for k in ('cost','attack','health'))):
            raise TargetValidationError('Unreviewed static-provider full-card recipe')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],health=recipe['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**DECLARATIONS[recipe['profile']])
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
