"""One reviewed All-type native Kindred donor, without inferred offer pools."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'DINO_435'
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-native-kindred-part-v1.json'
BATCH_HASH = '4317b88cd68bf5a4a7bc08800d5284091150fc5603d077e3a0a4e2e611a95fd2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != (CARD,) or
            len(rows) != 1 or rows[0]['record']['id'] != CARD or
            canonical_digest(rows[0]['record']) != rows[0]['record_sha256'] or
            len(data['official_observations']) != 2 or
            {x['locale'] for x in data['official_observations']} != {'zh_CN', 'en_US'} or
            any(x['card_id'] != CARD for x in data['official_observations']) or
            data['condition_policy'] != 'exact-native-composition-with-unchanged-complete-printed-query' or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Native Kindred donor lost its complete reviewed evidence')
    return data


def register_zombeast_native_kindred_part(registry):
    data = load_batch(); raw = data['existing_dependencies'][0]['record']; card = registry.card(CARD)
    if (CARD in registry.crafted_minion_parts or card.kind != CardType.MINION or
            (raw['cost'], raw['attack'], raw['health'], raw['tags'].get('KINDRED')) != (5, 3, 4, 1) or
            canonical_digest(asdict(card)) != data['reviewed_definition_sha256'] or
            card.metadata != metadata_from_record(raw) or card.metadata.tribes != ('all',) or
            CARD not in registry.kindred_profiles or
            asdict(registry.kindred_profiles[CARD]) != data['reviewed_kindred_profile']):
        raise TargetValidationError('Native Kindred donor requires its exact original face and profile')
    validate_part_shape(registry, card)
    registry.register_crafted_minion_part(CARD)
