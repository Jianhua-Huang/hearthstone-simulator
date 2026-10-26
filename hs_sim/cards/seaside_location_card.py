"""Seaside Giant prices actual accepted location uses through shared costs."""
import json
from pathlib import Path
from hs_sim.engine.location_uses import CONDITION, HISTORY_PROFILE
from hs_sim.engine.model import CardDefinition, CardType, IntrinsicCostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='VAC_439'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/seaside-location-cost-v1.json'
BATCH_HASH='6cb14e0436fd3b8230d4c1e9fca10586be7683d13f967731076a0da769f1a1ca'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['dependencies'] or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or len(data['official_faces'])!=2 or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']):
        raise TargetValidationError('Seaside Giant lost its complete original source and primary faces')
    return data


def register_seaside_location_card(registry):
    raw=load_batch()['cards'][0]['record']
    if CARD in registry.cards:raise TargetValidationError('Seaside Giant cannot overwrite an existing identity')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),intrinsic_costs=(IntrinsicCostSpec(delta=-2,condition=CONDITION,
            history_profile_id=HISTORY_PROFILE),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
