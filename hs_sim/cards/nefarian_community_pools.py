"""A declared local Nefarius inventory from the saved community observations."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import CraftedMinionRecipe, validate_part_shape
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.targets import TargetValidationError, canonical_digest
from .nefarian_crafted_faces import TEMPLATE

BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/nefarian-community-pools-v1.json'
BATCH_HASH = 'f46640e2c04cf6f4bebfd6de57f30b7c0042ff7b1fd8fec6341e44e53f6d5ef6'
SOURCE_TARGET = 'local-nefarian-community-v1'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or value['schema'] != 1 or
            value['official_completeness_verified'] is not False or
            [len(role['members']) for role in value['roles']] != [19, 20] or
            tuple(row['record']['id'] for row in value['cards']) != tuple(value['native_part_ids']) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in value['cards'])):
        raise TargetValidationError('Nefarius community inventory lost its complete reviewed data')
    return value


def register_nefarian_community_pools(registry):
    value = load_batch()
    for row in value['cards']:
        card = registry.card(row['record']['id'])
        if canonical_digest(asdict(card)) != row['reviewed_native_definition_sha256']:
            raise TargetValidationError('Nefarius donor lost its complete reviewed native definition: '+card.id)
        validate_part_shape(registry, card)
        if card.id not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
    if {cid for cid in value['native_part_ids'] if cid in registry.crafted_minion_parts} != set(value['existing_part_ids']):
        raise TargetValidationError('Nefarius inventory changed its original reviewed adapter boundary')
    for cid in value['native_part_ids']:
        if cid not in registry.crafted_minion_parts:
            registry.register_crafted_minion_part(cid)
    # Check every actually affordable composition. This is validation of the
    # full inventory, never a filter replacing an unimplemented native donor.
    first, second = value['roles']
    for a in first['members']:
        for b in second['members']:
            if b['card_id'] in second['excluded_card_ids']:
                continue
            if registry.card(a['card_id']).cost+registry.card(b['card_id']).cost <= 10:
                registry.card(CraftedMinionRecipe(TEMPLATE, a['card_id'], b['card_id']).card_id)
    for role in value['roles']:
        registry.register_pool(PoolDefinition(role['pool_id'], value['policy_id'], SOURCE_TARGET,
            'experimental', tuple(PoolMember(row['card_id'], row['weight']) for row in role['members']),
            excluded_card_ids=tuple(role['excluded_card_ids']), complete=False))
