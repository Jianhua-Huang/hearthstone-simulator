"""Platysaur retains its exact native draw-link body on a composed minion."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import NativeDeathrattleSpec
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TLC_603'
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/zombeast-native-draw-memory-v1.json'
BATCH_HASH = '47048afd7cde5549f247c557d6764d00b66cc2a22dc9f3cfd9067ac79463262c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or data['native_part_ids'] != [CARD] or
            len(rows) != 1 or rows[0]['record']['id'] != CARD or
            canonical_digest(rows[0]['record']) != rows[0]['record_sha256'] or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Native draw-link donor lost its full original source')
    return data


def register_zombeast_native_draw_memory(registry):
    data = load_batch(); raw = data['existing_dependencies'][0]['record']; card = registry.card(CARD)
    if (CARD in registry.crafted_minion_parts or
            canonical_digest(asdict(card)) != data['reviewed_native_definition_sha256'] or
            card.metadata != metadata_from_record(raw) or
            (card.cost, card.attack, card.health) != (raw['cost'], raw['attack'], raw['health']) or
            card.native_deathrattle != NativeDeathrattleSpec('draw_link')):
        raise TargetValidationError('Unreviewed complete native Platysaur declaration')
    validate_part_shape(registry, card)
    registry.register_crafted_minion_part(CARD)
