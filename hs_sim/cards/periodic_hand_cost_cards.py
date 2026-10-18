"""Two native turn-start hand discounts share one removable cost grant."""
import json
from pathlib import Path

from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.hand_turn_costs import GrantHandTurnDiscount
from hs_sim.engine.model import CardDefinition,CardType,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.zones import CardReference,HAND_TYPES
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARVER,CIRCADIA='CATA_566','TIME_102'
PREFIX='cards.periodic_hand_cost.';POOL_ID='constructed.cards'
EIGHT=PoolQuery(kinds=(CardType.MINION,),min_cost=8,max_cost=8,collectible=True)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/periodic-hand-cost-v1.json'
BATCH_HASH='7da26cdc9b54b7966d6e4153fcdcdeb11dc0932d6cd896c73711cd67b282984c'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARVER,CIRCADIA) or
            tuple(x['record']['id']for x in data['evidence_only'])!=('CATA_566e','TIME_102e') or
            any(data[k]for k in('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Periodic hand costs require their complete native source')
    if any(canonical_digest(x['record'])!=x['record_sha256']for x in(*data['cards'],*data['evidence_only'])):
        raise TargetValidationError('Periodic hand cost source row changed')
    return data


def register_periodic_hand_cost_cards(registry):
    def carve(c):
        if c.target_id is None:return ()
        target=c.state.entities[c.target_id]
        if target.zone!=Zone.HAND or target.controller!=c.player_id:return ()
        return (GrantHandTurnDiscount(CardReference.capture(target),c.source_id),)
    registry.register_behavior(PREFIX+'carve',carve)
    registry.register_behavior(PREFIX+'generate',lambda c:(GenerateFromPool(c.player_id,POOL_ID,EIGHT,
        source_id=c.source_id,minion_grant=CreatedMinionGrant(special='hand_turn_discount')),))
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        expected=(3,3,2)if cid==CARVER else(3,2,2)
        if (raw['type'],raw['tags'].get('BATTLECRY'))!=('MINION',1)or(raw['cost'],raw['attack'],raw['health'])!=expected:
            raise TargetValidationError('Periodic hand cost card changed its original face')
        fields={'targeting':TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.HAND,),kinds=HAND_TYPES,relation='friendly')}if cid==CARVER else{}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            battlecry=PREFIX+('carve'if cid==CARVER else'generate'),metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
