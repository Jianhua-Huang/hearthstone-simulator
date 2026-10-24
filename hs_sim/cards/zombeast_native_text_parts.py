"""Reviewed existing native text donors; offer membership remains separate."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PARTS = ('CORE_EX1_014', 'CORE_EX1_162', 'CORE_GIL_622', 'CORE_LOOT_413', 'CORE_UNG_084', 'BE_993', 'TIME_601', 'EDR_492', 'BE_255', 'BE_734', 'TIME_042', 'TLC_242')
CHILDREN = ('EX1_014t', 'EDR_492t', 'TIME_042t')
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/zombeast-native-text-parts-v1.json'
BATCH_HASH = 'edd59cd623bb6fa6d57e88ca66a4688552226f3d103065587f7e0aed5982e242'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(data['child_ids']) != CHILDREN or
            tuple(row['record']['id'] for row in rows) != (*PARTS, *CHILDREN) or
            set(data['reviewed_native_definition_sha256']) != set(PARTS+CHILDREN) or
            set(data['declaration_profiles']) != set(PARTS) or
            set(data['deck_identities']) != set(PARTS+CHILDREN) or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Native text donors lost their complete reviewed source')
    return data


def register_zombeast_native_text_parts(registry):
    data = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Native text donors require their one original registration')
    # Pin complete original definitions, including targeting and every native body.
    # Check all dependencies and shapes before adding any donor capability.
    for row in data['existing_dependencies']:
        raw = row['record']; cid = raw['id']; card = registry.card(cid)
        metadata = replace(metadata_from_record(raw), deck_identity=data['deck_identities'][cid])
        if (canonical_digest(asdict(card)) != data['reviewed_native_definition_sha256'][cid] or
                card.metadata != metadata or card.name != raw['name'] or
                any(getattr(card, field) != raw[field] for field in
                    ('cost', 'attack', 'health') if raw.get(field) is not None)):
            raise TargetValidationError('Unreviewed complete native text declaration: ' + cid)
        if cid in PARTS:
            if (card.kind != CardType.MINION or raw['collectible'] is not True or
                    type(raw['cost']) is not int or not 0 <= raw['cost'] <= 5):
                raise TargetValidationError('Native donor requires its reviewed low-cost minion')
            validate_part_shape(registry, card)
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
