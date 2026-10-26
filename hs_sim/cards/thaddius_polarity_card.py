"""The actual Thaddius uses one native per-card polarity cost aura."""
import json
from pathlib import Path
from hs_sim.engine.cost_polarities import AURA, CostPolarityProfile
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='NX2_033'
EVIDENCE=('NX2_033e','NX2_033e2')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/thaddius-polarity-v1.json'
BATCH_HASH='b2953863290e3a0bd3c1875b50294f82761bbd7c154579b442240506d85dca49'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['dependencies'] or
            tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in data['evidence_only'])!=EVIDENCE or
            len(data['official_faces'])!=2 or data['formal_pool_complete']is not False or data['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Thaddius polarity lost its complete original forms and primary faces')
    return data


def register_thaddius_polarity_card(registry):
    raw=load_batch()['cards'][0]['record']
    if CARD in registry.cards:raise TargetValidationError('Thaddius cannot overwrite an existing native identity')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.TAUNT,),cost_auras=(AURA,),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_cost_polarity_profile(CostPolarityProfile(CARD))
