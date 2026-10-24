"""The reported original Marshal face using shared received-damage pricing."""
from hs_sim.engine.model import CardDefinition,CardType,HeroDamageTakenCostSpec,Keyword
from hs_sim.engine.pools import PoolCard
from .metadata import metadata_from_record
from .mimiron_reported_tech_cards import load_batch

ROOT='AV_135'
PROFILE='cost.hero-previous-opponent-turn-five-set-one-v1'
COLLECTIBLE_ROOTS=()


def register_stormpike_marshal_card(registry):
    raw=next(v['record'] for v in load_batch()['evidence_only'] if v['record']['id']==ROOT)
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.TAUNT,),metadata=metadata_from_record(raw),
        hero_damage_taken_cost=HeroDamageTakenCostSpec(PROFILE))
    registry.register_card(card)
    if ROOT not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
