"""Actual simple secondary dependencies; explicit references do not certify CN pools."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.model import CardDefinition, CardType, Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DEFINITIONS = ('DMF_532', 'DRG_066', 'GIL_681', 'ICC_419', 'LOOT_125')
EXISTING = ('TIME_046', 'TSC_065')
PARTS = DEFINITIONS + EXISTING
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/zombeast-secondary-reference-cards-v1.json'
BATCH_HASH = 'da08b77ccd5ed89b7c62ac4700f2be967c89374b5831eadd1c3aa2781b819a8f'
REFERENCE_PATH = BATCH_PATH.with_name('zombeast-local-reference-v1.json')


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = value['cards'] + value['existing_dependencies']
    if (canonical_digest(value) != BATCH_HASH or tuple(value['native_part_ids']) != PARTS or
            tuple(row['record']['id'] for row in rows) != PARTS or
            set(value['reviewed_existing_definition_sha256']) != set(EXISTING) or
            set(value['native_keywords']) != set(DEFINITIONS) or
            value['formal_pool_complete'] is not False or value['cn_calibrated'] is not False or
            any(value[key] for key in ('dependencies', 'evidence_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Secondary reference dependencies lost their full reviewed source')
    reference = json.loads(REFERENCE_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(reference) != value['reference_canonical_sha256'] or
            not set(PARTS) <= set(reference['second_reference_ids']) or
            reference['runtime_bindings_added'] is not False or reference['formal_pool_complete'] is not False):
        raise TargetValidationError('Secondary source reference changed its independently reviewed identities')
    return value


def register_zombeast_secondary_reference_cards(registry):
    value = load_batch()
    if set(PARTS) & set(registry.crafted_minion_parts):
        raise TargetValidationError('Secondary dependencies require one original donor registration')
    definitions = []
    # Validate the complete batch before any new definition or donor is installed.
    for row in value['cards'] + value['existing_dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'] != 'MINION' or raw['collectible'] is not True or
                type(raw['cost']) is not int or not 0 <= raw['cost'] <= 5):
            raise TargetValidationError('Secondary reference requires its full actual low-cost minion face')
        metadata = metadata_from_record(raw)
        if not set(metadata.tribes) & {'beast', 'all'}:
            raise TargetValidationError('Secondary reference lost its Beast or All-type declaration')
        if cid in DEFINITIONS:
            if cid in registry.cards or cid in registry.pool_cards:
                raise TargetValidationError('New secondary dependency collides with an existing identity')
            card = CardDefinition(cid, raw['name'], CardType.MINION, cost=raw['cost'],
                attack=raw['attack'], health=raw['health'], metadata=metadata,
                keywords=tuple(Keyword(k) for k in value['native_keywords'][cid]))
            definitions.append(card)
        else:
            card = registry.card(cid)
            if (canonical_digest(asdict(card)) != value['reviewed_existing_definition_sha256'][cid] or
                    card.metadata != metadata or
                    (card.cost, card.attack, card.health) != (raw['cost'], raw['attack'], raw['health'])):
                raise TargetValidationError('Unreviewed complete existing secondary declaration: ' + cid)
        validate_part_shape(registry, card)
    for card in definitions:
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
    for cid in PARTS:
        registry.register_crafted_minion_part(cid)
