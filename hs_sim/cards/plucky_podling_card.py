"""The real Podling declares one finite native transformation replacement."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, NativeSourceCondition
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_529'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/plucky-podling-v1.json'
BATCH_HASH = 'dc350344ca065ae3f263beab006da868153eabae6ca48686f81b0f6376c887c7'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id'] for x in d['cards'])!=(CARD,)
            or any(d[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Podling requires its complete original source')
    row,=d['cards']
    if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Podling source row changed')
    return d


def register_plucky_podling_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'],raw['tags']['RARITY']) != ('MINION',1,1,2,8,4):
        raise TargetValidationError('Podling original Shaman Epic body changed')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=1,attack=1,health=2,
        native_condition=NativeSourceCondition('transform_destination_plus_two'),metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
