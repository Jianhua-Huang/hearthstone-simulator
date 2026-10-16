"""Source-reviewed metadata projection, independent of historical fixture content."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record,validate_race_pin

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/constructed-metadata-catalog-v1.json'
BATCH_HASH='7cfa3ed3e1afc16d9c610b78dc53268bf9ec673ac732e90b90c185f9483d32cf'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or data['metadata_overrides']!=['CATA_155']:
        raise TargetValidationError('Unreviewed constructed metadata catalog')
    ids=tuple(x['record']['id']for x in data['cards'])
    if len(ids)!=24 or len(set(ids))!=24:raise TargetValidationError('Incomplete reviewed metadata row set')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original metadata source row')
    return data


def metadata_overrides():
    validate_race_pin();data=load_batch();rows={x['record']['id']:x for x in data['cards']};result=[]
    for cid in data['metadata_overrides']:
        row=rows[cid];meta=metadata_from_record(row['record'])
        if canonical_digest(asdict(meta))!=row['expected_metadata_sha256']:
            raise TargetValidationError('Reviewed constructed printed metadata changed')
        result.append((cid,meta))
    return tuple(result)


def register_reviewed_pool_metadata(registry):
    pending=[]
    for row in load_batch()['cards']:
        cid=row['record']['id'];card=registry.card(cid)
        if canonical_digest(asdict(card.metadata))!=row['expected_metadata_sha256']:
            raise TargetValidationError('Executable card disagrees with reviewed printed metadata')
        expected=PoolCard.from_definition(card)
        if cid in registry.pool_cards:
            if registry.pool_card(cid)!=expected:raise TargetValidationError('Existing pool row disagrees with its executable card')
        else:pending.append(expected)
    for expected in pending:registry.register_pool_card(expected)
