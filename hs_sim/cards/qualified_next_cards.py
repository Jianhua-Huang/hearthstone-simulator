"""Actual next-card structural/temporary/tribal prices and next-own-start healing lock."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier,GrantHealthRule,InvokeBehavior
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,HealthFlow,HealthLayer,
    HealthOp,HealthRule,Keyword,KeywordAuraSpec,PaymentType)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/qualified-next-effects-v1.json'
BATCH_HASH='e46d79b12ac28e75a35e6d93e82100265bc9bcc66beea5eda0d37c5154cc052d'
PREFIX='cards.qualified_next.'
NO_HEAL=HealthRule(HealthFlow.HEALING,HealthOp.PREVENT,layer=HealthLayer.TARGET,
    target_relation='self',target_kinds=(CardType.HERO,))


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Qualified next-card source pin changed')
    return data


SCRIPTS={
    'next_combo':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2),uses_remaining=1,
        source_id=c.source_id,expires_turn=c.state.turn,combo_only=True),),
    'next_temporary':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2),uses_remaining=1,
        source_id=c.source_id,temporary_only=True),),
    'next_demon_zero':lambda c:(AddCostModifier(c.player_id,CostSpec(set_to=0,card_types=(CardType.MINION,)),
        uses_remaining=1,source_id=c.source_id,expires_turn=c.state.turn,tribes_any=('demon',)),),
    'small_murloc_health':lambda c:(AddCostModifier(c.player_id,CostSpec(payment=PaymentType.HEALTH,card_types=(CardType.MINION,)),
        uses_remaining=1,source_id=c.source_id,tribes_any=('murloc',),maximum_cost=3),),
    'no_enemy_healing':lambda c:(InvokeBehavior(PREFIX+'grant_no_healing',c.source_id,c.player_id),),
    'grant_no_healing':lambda c:(GrantHealthRule(c.state.players[3-c.player_id].hero_id,NO_HEAL,
        c.source_id,until_owner_turn_start=c.player_id),),
}


def register_qualified_next_cards(registry):
    for name,body in SCRIPTS.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']or any(raw[k]!=recipe[k]for k in ('cost','attack','health')):
            raise TargetValidationError('Qualified next-card full source or printed stats changed')
        if raw['type']!='MINION'or recipe['keywords']or script not in SCRIPTS or script=='grant_no_healing':
            raise TargetValidationError('Unreviewed qualified next-card recipe')
        extra={'keyword_auras':(KeywordAuraSpec(Keyword.IMMUNE),)}if script=='next_demon_zero'else{}
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],health=recipe['health'],
            battlecry=PREFIX+script,metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
