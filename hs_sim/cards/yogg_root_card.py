"""Actual Yogg Battlecry and four native abilities; actor ranking awaits M6."""
from hs_sim.engine.controlled_turns import RequestControlledTurn
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from .metadata import metadata_from_record
from .yogg_skills import ROOT,load_batch,skill_specs

PREFIX='cards.yogg_root.'
COLLECTIBLE_ROOTS=(ROOT,)


def register_yogg_root_card(registry):
    # The original skill package marked its parent evidence-only at K501.
    # Its immutable raw row remains the source; this adapter adds the parent.
    data=load_batch();raw=data['evidence_only'][0]['record']
    def battlecry(c):
        if c.battlecry is None:raise ValueError('Yogg requires its real accepted Battlecry')
        return (RequestControlledTurn(c.battlecry.id),)
    registry.register_behavior(PREFIX+'battlecry',battlecry)
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],keywords=(Keyword.OLD_GOD,),metadata=metadata_from_record(raw),
        battlecry=PREFIX+'battlecry',activated_abilities=skill_specs())
    registry.register_card(card)
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
