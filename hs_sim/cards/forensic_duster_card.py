"""Actual Duster body through the original next-turn price program."""
from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,PlayerEffectSpec,TriggerSpec
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from .metadata import metadata_from_record
from .mimiron_reported_tech_cards import load_batch

ROOT='REV_378'
PREFIX='cards.forensic_duster.'
TAX=PREFIX+'minion-tax'
COLLECTIBLE_ROOTS=()


def register_forensic_duster_card(registry):
    # The K503 evidence-only row and its full faces retain their historical scope.
    raw=next(v['record'] for v in load_batch()['evidence_only'] if v['record']['id']==ROOT)
    def activate(c):
        if c.event.player_id!=c.player_id:return ()
        return (RemovePlayerEffect(c.player_id,c.player_effect.id),
            AddCostModifier(c.player_id,CostSpec(delta=1,card_types=(CardType.MINION,)),
                source_id=c.source_id,expires_turn=c.state.turn))
    registry.register_behavior(PREFIX+'activate',activate)
    registry.register_player_effect(PlayerEffectSpec(TAX,ROOT,
        triggers=(TriggerSpec('turn_started',PREFIX+'activate'),)))
    registry.register_behavior(PREFIX+'battlecry',lambda c:(AddPlayerEffect(3-c.player_id,TAX,c.source_id),))
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),battlecry=PREFIX+'battlecry')
    registry.register_card(card)
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
