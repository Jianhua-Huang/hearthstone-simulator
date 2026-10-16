"""Complete ordinary power costs, whole-game minion prices/healing and Ysera."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import (AddCostModifier, ChangeManaCrystals,
    GrantHealthRule, InvokeBehavior, SetManaCap)
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, HealthFlow,
    HealthOp, HealthRule, OpeningHook)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/persistent-economy-effects-v1.json'
BATCH_HASH='d3667e7ba9a9a0e37a0dc7b12d2d17fdd61e6195e843df474d76b6e414ff973f'
PREFIX='cards.persistent_economy.'
HEALING_BONUS=HealthRule(HealthFlow.HEALING,HealthOp.ADD,2,source_relation='friendly')


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Persistent economy content differs from its reviewed source pin')
    return data


SCRIPTS={
    'enemy_next_power':lambda c:(AddCostModifier(3-c.player_id,
        CostSpec(delta=2,card_types=(CardType.HERO_POWER,)),uses_remaining=1,source_id=c.source_id),),
    'next_power_zero':lambda c:(AddCostModifier(c.player_id,
        CostSpec(set_to=0,card_types=(CardType.HERO_POWER,)),uses_remaining=1,source_id=c.source_id),),
    'minions_five':lambda c:(AddCostModifier(c.player_id,
        CostSpec(set_to=5,card_types=(CardType.MINION,)),source_id=c.source_id),),
    'ysera':lambda c:(ChangeManaCrystals(c.player_id,3,filled=True),),
    'ysera_opening':lambda c:tuple(InvokeBehavior(PREFIX+'raise_cap',c.source_id,p) for p in (1,2)),
    'raise_cap':lambda c:(SetManaCap(c.player_id,c.state.players[c.player_id].mana_cap+5),),
    'healing_bonus':lambda c:(InvokeBehavior(PREFIX+'grant_healing',c.source_id,c.player_id),),
    'grant_healing':lambda c:(GrantHealthRule(c.state.players[c.player_id].hero_id,
        HEALING_BONUS,c.source_id),),
}


def register_persistent_economy_cards(registry):
    for name,body in SCRIPTS.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']:
            raise TargetValidationError('Persistent economy original record changed')
        if raw['type']!='MINION' or not raw['collectible'] or recipe['keywords']:
            raise TargetValidationError('Persistent economy requires complete ordinary minion roots')
        if script not in ('enemy_next_power','next_power_zero','minions_five','ysera','healing_bonus'):
            raise TargetValidationError('Unreviewed persistent economy script')
        if any(raw[k]!=recipe[k] for k in ('cost','attack','health')):
            raise TargetValidationError('Persistent economy printed stats changed')
        extra={}
        if script=='next_power_zero':extra['deathrattle']=PREFIX+script
        if script=='ysera':extra['opening_hooks']=(OpeningHook('before_deal',PREFIX+'ysera_opening'),)
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],
            attack=recipe['attack'],health=recipe['health'],battlecry=PREFIX+script,
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
