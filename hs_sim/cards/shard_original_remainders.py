"""Shard uses the original board-discovery producer and actual offered remainder."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/shard-original-discovery-remainders-v1.json'
BATCH_HASH='ae13c69379aa142c936ab5c99994e273794dc38710672d159767e22afc8f548a'
CARD='DEEP_999t3'
BODY='cards.shard.original_remainders'
POOL='constructed.cards'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',tribes_any=('elemental',))
COLLECTIBLE_ROOTS=()


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    reference=json.loads((ROOT/data['reference_document']).read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            canonical_digest(reference)!=data['reference_canonical_sha256'] or
            tuple(r['record']['id']for r in data['cards'])!=(CARD,) or len(data['official_observations'])!=2 or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','source_scope_bound',
                'real_excavation_profile_bound','formal_pool_complete','cn_calibrated')) or
            canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']):
        raise TargetValidationError('Shard lost its complete original source or unbound Excavation scope')
    return data


def register_shard_original_remainders(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['collectible'],raw['tags'].get('2823'))!=('SPELL',3,False,1) or CARD in registry.cards:
        raise TargetValidationError('Shard requires its true three-mana noncollectible treasure face')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=3,metadata=metadata_from_record(raw),on_play=BODY)
    registry._validate_card(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD)!=PoolCard.from_definition(card):
        raise TargetValidationError('Shard differs from its complete original pool metadata')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL,QUERY,source_id=c.source_id,
        destination='board',cause=SummonCause.capture(c),unselected_to_hand=True),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
