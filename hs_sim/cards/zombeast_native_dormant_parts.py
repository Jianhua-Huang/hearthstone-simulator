"""One reviewed timed Dormant donor; pool and CN calibration remain separate."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TSC_647'
PARTS = (CARD,)
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-native-dormant-parts-v1.json'
BATCH_HASH = '72fc0e6c79fec7fd7c271d0708772098ed53bacbaf6d7cb1c88433816f46fff1'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(row['record']['id'] for row in rows) != PARTS or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows) or
            data['entry_policy']['id'] != 'historical-native-dormant-before-entry-bodies-v1' or
            data['entry_policy']['current_CN_verified'] is not False or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Native timed Dormant donor lost its full reviewed source and policy')
    return data


def register_zombeast_native_dormant_parts(registry):
    raw = load_batch()['existing_dependencies'][0]['record']
    expected = CardDefinition(CARD, raw['name'], CardType.MINION, cost=1, attack=4, health=1,
        keywords=(Keyword.RUSH,), dormant_turns=1, metadata=metadata_from_record(raw))
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('RUSH')) != (
            'MINION', 1, 4, 1, 1) or registry.card(CARD) != expected:
        raise TargetValidationError('Unreviewed native Pelican Diver declaration')
    registry.register_crafted_minion_part(CARD)
