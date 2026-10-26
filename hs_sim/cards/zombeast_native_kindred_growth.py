"""Reviewed native Kindred bodies and one original hand/deck growth donor."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import CardType
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

PARTS = ('END_015', 'TLC_825', 'TLC_827')
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/zombeast-native-kindred-growth-v1.json'
BATCH_HASH = '2aef51bac5276c161449499a7b078d41d7af9f523f0070d091c15e5fdef02318'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['native_part_ids']) != PARTS or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != PARTS or
            set(data['reviewed_definition_sha256']) != set(PARTS) or
            set(data['deck_identities']) != set(PARTS) or
            set(data['kindred_profiles']) != set(PARTS[:2]) or
            data['numeric_normalizations'] != {'TLC_827': {'attack': 0}} or
            data['condition_policy'] != 'reviewed-native-donor-original-profile-and-complete-composed-type-query' or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[k] for k in ('cards', 'dependencies', 'evidence_only', 'skipped', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['existing_dependencies'])):
        raise TargetValidationError('Native Kindred/growth donors lost complete reviewed evidence')
    reference = json.loads(BATCH_PATH.with_name('zombeast-local-reference-v1.json').read_text(encoding='utf-8'))
    if (canonical_digest(reference) != data['reference_canonical_sha256'] or
            not set(PARTS) <= set(reference['first_reference_ids'])):
        raise TargetValidationError('Native Kindred/growth donors changed independent role identities')
    return data


def register_zombeast_native_kindred_growth(registry):
    data = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Native Kindred/growth requires one original donor registration')
    for cid, profile in data['kindred_profiles'].items():
        if cid not in registry.kindred_profiles or asdict(registry.kindred_profiles[cid]) != profile:
            raise TargetValidationError('Native Kindred donor lost its complete original body profile')
    target = registry.kindred_target_profiles.get('TLC_825')
    if target is None or asdict(target) != data['kindred_target_profile']:
        raise TargetValidationError('Native Matriarch donor lost its complete original target profile')
    for row in data['existing_dependencies']:
        raw = row['record']; cid = raw['id']; card = registry.card(cid)
        attack = raw['attack']
        if cid == 'TLC_827':
            if attack is not None or 'ATK' in raw['tags']:
                raise TargetValidationError('Native growth zero must retain its exact omitted raw attack')
            attack = 0
        metadata = replace(metadata_from_record(raw), deck_identity=data['deck_identities'][cid])
        if (canonical_digest(asdict(card)) != data['reviewed_definition_sha256'][cid] or
                card.metadata != metadata or card.name != raw['name'] or
                (card.cost, card.attack, card.health) != (raw['cost'], attack, raw['health']) or
                card.kind != CardType.MINION or raw['collectible'] is not True or
                'beast' not in metadata.tribes or type(raw['cost']) is not int or not 0 <= raw['cost'] <= 5):
            raise TargetValidationError('Unreviewed complete native Kindred/growth donor: ' + cid)
        validate_part_shape(registry, card)
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
