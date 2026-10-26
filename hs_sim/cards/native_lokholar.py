"""The actual past-pool identity uses the existing finite hero-health price."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, HeroMissingHealthCostSpec, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='AV_141t'
PROFILE='cost.hero-health-at-most-fifteen-v1'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-lokholar-v1.json'
BATCH_HASH='b5bb99bf06f1655e3895280cd4e88cd23a243ffd713e2f7625c1c596215c5cce'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or value['dependencies'] or
            tuple(x['record']['id']for x in value['cards'])!=(CARD,) or len(value['official_faces'])!=2 or
            value['formal_pool_complete']is not False or value['cn_calibrated']is not False or
            canonical_digest(value['cards'][0]['record'])!=value['cards'][0]['record_sha256']):
        raise TargetValidationError('Native Lokholar lost its complete original identity and source')
    return value


def register_native_lokholar(registry):
    raw=load_batch()['cards'][0]['record']
    if CARD in registry.cards:raise TargetValidationError('Native Lokholar cannot overwrite an existing identity')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.RUSH,Keyword.WINDFURY),metadata=metadata_from_record(raw),
        hero_missing_health_cost=HeroMissingHealthCostSpec(PROFILE))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
