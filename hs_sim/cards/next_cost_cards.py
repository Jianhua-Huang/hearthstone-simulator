"""Reviewed original-neighbor, conditional-account and next-card cost consumers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier,Damage
from hs_sim.engine.hand_neighbors import submitted_hand_neighbors
from hs_sim.engine.model import (CardDefinition,CardType,CostSpec,DamageKind,IntrinsicCostSpec,
    Keyword,TargetMode,TargetSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .health_cards import SCHOOLS
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/next-cost-effects-v1.json'
BATCH_HASH='9e42211f66dc3a71d43bab71160c65801f76f9028b661706259935406e9a4988'
PREFIX='cards.next_costs.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Next-cost content differs from its reviewed source pin')
    return data


def tribal_next(c,tribe,temporary=False):
    return AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.MINION,)),
        uses_remaining=1,source_id=c.source_id,expires_turn=c.state.turn if temporary else None,tribes_any=(tribe,))


SCRIPTS={
 'neighbors':lambda c:tuple(ModifyStoredCost(ref,CostSpec(delta=-1),c.source_id)
                           for ref in submitted_hand_neighbors(c)),
 'next_demon':lambda c:(tribal_next(c,'demon'),),
 'damage_next_beast':lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),tribal_next(c,'beast',True)),
 'preparation':lambda c:(AddCostModifier(c.player_id,CostSpec(delta=-2,card_types=(CardType.SPELL,)),
     uses_remaining=1,source_id=c.source_id,expires_turn=c.state.turn),),
}


def register_next_cost_cards(registry):
    for name,fn in SCRIPTS.items():registry.register_behavior(PREFIX+name,fn)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Next-cost record changed')
        kind=CardType(raw['type'].lower());kwargs={};script=recipe['script']
        if script=='healed_health':
            kwargs.update(pay_health_if_hero_healed=True,intrinsic_costs=(IntrinsicCostSpec(
                condition='hero_healed_this_turn',history_profile_id='healing.hero-this-turn-v1'),))
        elif script in SCRIPTS:kwargs[recipe['entry']]=PREFIX+script
        else:raise TargetValidationError('Unreviewed next-cost script')
        if script=='damage_next_beast':kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        cost=recipe['cost']
        if raw['cost']!=cost and not(raw['id']=='CORE_EX1_145' and raw['cost']is None and cost==0):
            raise TargetValidationError('Unreviewed printed next-card cost')
        definition=CardDefinition(raw['id'],raw['name'],kind,cost=cost,attack=raw['attack']or 0,
            health=raw['health']if kind==CardType.MINION else 0,keywords=tuple(Keyword(k)for k in recipe['keywords']),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
