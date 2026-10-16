"""Actual permanent damage and the opponent's next real turn of spell taxation."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,EndTurnSpec,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect,PlayerEffectDamage,RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/player-period-effects-v1.json'
BATCH_HASH='bdfdc20cab512f89ebdbd3d59fc6e6dee6fea991fa28dc925b1adef46798a044'
PREFIX='cards.player_period.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Player period source content differs from its reviewed pin')
    return data


def damage(c):
    if c.player_effect is None:raise ValueError('Permanent damage lost its player instance')
    return (PlayerEffectDamage(c.player_id,c.player_effect,c.state.players[3-c.player_id].hero_id,3),)


def next_turn(c):
    if c.event.player_id!=c.player_id:return ()
    if c.player_effect is None:raise ValueError('Next-turn spell tax lost its player instance')
    return (AddCostModifier(c.player_id,CostSpec(delta=1,card_types=(CardType.SPELL,)),
        source_id=c.source_id,expires_turn=c.state.turn),RemovePlayerEffect(c.player_id,c.player_effect.id))


def register_player_period_cards(registry):
    scripts={
        'mograine':lambda c:(AddPlayerEffect(c.player_id,PREFIX+'mograine',c.source_id,capture_health_source=True),),
        'neophyte':lambda c:(AddPlayerEffect(3-c.player_id,PREFIX+'neophyte',c.source_id),),
        'damage':damage,'next_turn':next_turn,
    }
    for name,body in scripts.items():registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'mograine','CORE_RLK_706',
        triggers=(TriggerSpec('turn_ended',PREFIX+'damage',EndTurnSpec()),)))
    registry.register_player_effect(PlayerEffectSpec(PREFIX+'neophyte','CORE_SCH_713',
        triggers=(TriggerSpec('turn_started',PREFIX+'next_turn'),)))
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']or any(raw[k]!=recipe[k]for k in ('cost','attack','health')):
            raise TargetValidationError('Player period complete source record or stats changed')
        if raw['type']!='MINION'or recipe['keywords']or recipe['script']not in ('mograine','neophyte'):
            raise TargetValidationError('Unreviewed player period recipe')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],health=recipe['health'],
            battlecry=PREFIX+recipe['script'],metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
