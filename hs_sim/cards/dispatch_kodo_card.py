"""Dispatch Kodo uses the ordinary captured Battlecry and damage pipelines."""
import json
from pathlib import Path

from hs_sim.engine.crafted_faces import validate_part_shape
from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, TargetMode, TargetSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CFM_335'
BODY = 'cards.dispatch_kodo.battlecry'
COLLECTIBLE_ROOTS = ()
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/dispatch-kodo-v1.json'
BATCH_HASH = 'bc5ab85d32f93cca2839d887a07b5bc4a9e2aee689c623debd03f46a3cb62837'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards']
    if (canonical_digest(data) != BATCH_HASH or len(rows) != 1 or
            rows[0]['record']['id'] != CARD or
            canonical_digest(rows[0]['record']) != rows[0]['record_sha256'] or
            tuple(data['native_part_ids']) != (CARD,) or
            len(data['official_observations']) != 2 or
            {x['locale'] for x in data['official_observations']} != {'zh_CN', 'en_US'} or
            any(x['card_id'] != CARD for x in data['official_observations']) or
            data['attack_basis'] != 'ordinary-battlecry-begin-detached-source-attack' or
            data['target_policy'] != 'ordinary-if-available-minion-or-hero' or
            data['formal_pool_complete'] is not False or data['cn_calibrated'] is not False or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only',
                'skipped', 'numeric_normalizations', 'display_normalizations'))):
        raise TargetValidationError('Dispatch Kodo requires its complete reviewed face and explicit entry policy')
    return data


def register_dispatch_kodo_card(registry):
    raw = load_batch()['cards'][0]['record']
    if ((raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('BATTLECRY')) != ('MINION', True, 4, 2, 4, 1) or
            CARD in registry.cards or CARD in registry.pool_cards or CARD in registry.crafted_minion_parts):
        raise TargetValidationError('Dispatch Kodo requires its exact new original identity')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=2, health=4,
        battlecry=BODY, metadata=metadata_from_record(raw),
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, kinds=(CardType.MINION, CardType.HERO)))
    registry.register_behavior(BODY, lambda c: () if c.target_id is None else (
        Damage(c.target_id, c.source.attack, c.source_id, DamageKind.MINION_ABILITY),))
    validate_part_shape(registry, card)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_crafted_minion_part(CARD)
