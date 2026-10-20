"""Victor's actual source; host-curated inventories are not inferred from adapters."""
from hs_sim.engine.crafted_offers import CraftMinion
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from .metadata import metadata_from_record
from .nefarian_crafted_faces import CARD,TEMPLATE,load_batch

DRAGONS='crafted.nefarian.dragons'
UNDEAD='crafted.nefarian.undead'
BEHAVIOR='cards.nefarian.craft'


def register_nefarian_crafting_card(registry):
    raw=load_batch()['cards'][0]['record']
    def body(c):
        return(CraftMinion(c.player_id,TEMPLATE,DRAGONS,UNDEAD,c.source_id,
            max_total_cost=10,discount_tribe='dragon',discount_amount=3),)
    registry.register_behavior(BEHAVIOR,body)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),battlecry=BEHAVIOR)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
