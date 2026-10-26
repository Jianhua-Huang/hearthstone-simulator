"""Reviewed native followups can donate; candidate membership is independent."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PARTS = ('BE_731', 'CORE_UNG_912', 'EDR_849', 'TLC_245', 'TLC_246',
    'TLC_250', 'TLC_256', 'JAIL_878', 'TIME_058')
CHILDREN = ('UNG_999t2t1', 'UNG_999t10', 'UNG_999t5', 'UNG_999t7')
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/zombeast-native-followup-parts-v1.json'
BATCH_HASH = 'daa607d391164a237653cc606c12787734eedee960047ad57e293c8e93e947cc'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = value['existing_dependencies']
    ids = PARTS + CHILDREN
    if (canonical_digest(value) != BATCH_HASH or tuple(value['native_part_ids']) != PARTS or
            tuple(value['child_ids']) != CHILDREN or
            tuple(row['record']['id'] for row in rows) != ids or
            set(value['reviewed_native_definition_sha256']) != set(ids) or
            set(value['deck_identities']) != set(ids) or
            value['declaration_profiles'] != dict.fromkeys(PARTS, 'complete-existing-native-followup-v1') or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            any(value[key] for key in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Native followup donors lost their full reviewed source')
    return value


def register_zombeast_native_followup_parts(registry):
    value = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Native followup donors require one original registration')
    # Validate the whole batch, including native options and the summoned Plants,
    # before changing the donor registry. An adapter does not establish eligibility.
    for row in value['existing_dependencies']:
        raw = row['record']; cid = raw['id']; card = registry.card(cid)
        metadata = replace(metadata_from_record(raw), deck_identity=value['deck_identities'][cid])
        if (canonical_digest(asdict(card)) != value['reviewed_native_definition_sha256'][cid] or
                card.metadata != metadata or card.name != raw['name'] or
                any(getattr(card, key) != raw[key] for key in ('cost', 'attack', 'health')
                    if raw.get(key) is not None)):
            raise TargetValidationError('Unreviewed native followup declaration: ' + cid)
        if cid in PARTS:
            if (card.kind != CardType.MINION or raw['collectible'] is not True or
                    'beast' not in metadata.tribes or type(raw['cost']) is not int or
                    not 0 <= raw['cost'] <= 5):
                raise TargetValidationError('Native followup donor requires its actual low-cost Beast face')
            validate_part_shape(registry, card)
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
