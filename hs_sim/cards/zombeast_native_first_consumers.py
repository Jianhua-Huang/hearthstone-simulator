"""Reviewed first-role native consumers reuse original nested effect pipelines."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.dark_gifts import DARK_GIFTS, DARK_GIFT_VERSION
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PARTS = ('BE_044', 'CORE_LOE_039', 'EDR_014', 'END_013', 'JAIL_EVENT_100', 'TLC_102')
CHILDREN = ('JAIL_EVENT_100t',)
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/zombeast-native-first-consumers-v1.json'
BATCH_HASH = 'cefcb235e25a42883d41ec7fe9e88fcfc2e77fe884a23bce5babbbfe17098a54'
REFERENCE_PATH = BATCH_PATH.with_name('zombeast-local-reference-v1.json')


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['existing_dependencies']; ids = PARTS + CHILDREN
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(data['child_ids']) != CHILDREN or
            tuple(row['record']['id'] for row in rows) != ids or
            set(data['reviewed_definition_sha256']) != set(ids) or set(data['deck_identities']) != set(ids) or
            data['gift_version'] != DARK_GIFT_VERSION or
            data['gift_recipes_sha256'] != canonical_digest([asdict(x) for x in DARK_GIFTS]) or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[key] for key in ('cards', 'dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Native first consumers lost their full reviewed source')
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(reference) != data['reference_canonical_sha256'] or
            not set(PARTS) <= set(reference['first_reference_ids']) or
            reference['formal_pool_complete'] is not False):
        raise TargetValidationError('First-consumer reference changed its independently reviewed identities')
    return data


def register_zombeast_native_first_consumers(registry):
    data = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Native first consumers require one original donor registration')
    profile = registry._suspicious_discovery_profiles.get('JAIL_EVENT_100')
    if profile is None or canonical_digest(asdict(profile)) != data['watfin_profile_sha256']:
        raise TargetValidationError('Native Watfin donor lost its complete original discovery profile')
    for row in data['existing_dependencies']:
        raw = row['record']; cid = raw['id']; card = registry.card(cid)
        metadata = replace(metadata_from_record(raw), deck_identity=data['deck_identities'][cid])
        if (canonical_digest(asdict(card)) != data['reviewed_definition_sha256'][cid] or
                card.metadata != metadata or card.name != raw['name'] or
                (card.cost, card.attack, card.health) != (raw['cost'], raw['attack'], raw['health'])):
            raise TargetValidationError('Unreviewed complete native first-consumer declaration: ' + cid)
        if cid in PARTS:
            if (card.kind != CardType.MINION or raw['collectible'] is not True or
                    'beast' not in metadata.tribes or type(raw['cost']) is not int or
                    not 0 <= raw['cost'] <= 5):
                raise TargetValidationError('Native first consumer requires its actual low-cost Beast face')
            validate_part_shape(registry, card)
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
