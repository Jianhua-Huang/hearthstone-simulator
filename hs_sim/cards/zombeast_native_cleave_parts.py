"""One current Core native adjacency donor; no curated pool is inferred."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CORE_SCH_605'
LEGACY = 'SCH_605'
PARTS = (CARD,)
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-native-cleave-parts-v1.json'
BATCH_HASH = '2e8fa24f4d04b1b25f66b1d64cee46f523370147f3fc22bca711b4a6b9864955'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies'] + data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(row['record']['id'] for row in rows) != (CARD, LEGACY) or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('cards', 'dependencies', 'skipped', 'numeric_normalizations',
                'display_normalizations')) or any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Native adjacency donor lost its complete current Core source')
    return data


def register_zombeast_native_cleave_parts(registry):
    raw = load_batch()['existing_dependencies'][0]['record']
    metadata = metadata_from_record(raw)
    card = registry.card(CARD)
    expected = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], cleave=True, metadata=metadata)
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 5, 4, 6) or card != expected:
        raise TargetValidationError('Unreviewed native Core Lake Thresher declaration')
    registry.register_crafted_minion_part(CARD)
