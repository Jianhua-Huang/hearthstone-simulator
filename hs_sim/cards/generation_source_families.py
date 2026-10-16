"""Reviewed edition links; no name-prefix inference or executable placeholders."""
import json
from pathlib import Path
from hs_sim.targets import TargetValidationError,canonical_digest

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/generation-source-families-v1.json'
BATCH_HASH='3a5ed3deac56281b0e505c34cf46e13d2422a038aa55515dd395280b316105d6'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Reviewed generation edition links changed')
    return data


def register_generation_source_families(registry):
    data=load_batch()
    for row in data['records']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Incomplete generation edition evidence')
    for family in data['families']:
        registry.register_generation_family(tuple(family))
