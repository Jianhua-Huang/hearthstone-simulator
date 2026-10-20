"""Actual Mayor source; target acceptance belongs to the shared engine paths."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='CORE_CFM_670'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/noggenfogger-random-targets-v1.json'
BATCH_HASH='71c4823fc7674e5ee22b5cda4722a88b3feb71528842caa55e45c699cfb303d8'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,) or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')) or
            canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']):
        raise TargetValidationError('Mayor requires its complete reviewed original source')
    return data


def register_noggenfogger_card(registry):
    row=load_batch()['cards'][0];raw=row['record'];metadata=metadata_from_record(raw)
    if (raw['type']!='MINION' or raw['collectible']is not True or
            canonical_digest(asdict(metadata))!=canonical_digest(row['metadata'])):
        raise TargetValidationError('Mayor changed its complete printed type or metadata')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata)
    registry.register_card(card)
    registry.register_random_target_card(CARD)
    pool=PoolCard.from_definition(card)
    if CARD in registry.pool_cards:
        if registry.pool_cards[CARD]!=pool:raise TargetValidationError('Mayor changed an existing pool declaration')
    else:registry.register_pool_card(pool)
