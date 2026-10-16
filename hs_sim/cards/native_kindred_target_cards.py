"""Ravasaur Matriarch's pure Kindred body has a native conditional target."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.kindred_targets import KindredTargetProfile
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, KindredProfile, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

MATRIARCH = 'TLC_825'
PREFIX = 'cards.native_kindred_target.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-kindred-target-v1.json'
BATCH_HASH = 'ced33c2fafe217fb58413fb506959ab3a4890205fdcd50cdfc437d9adea7448c'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['dependencies']
            or tuple(x['record']['id'] for x in data['cards']) != (MATRIARCH,)):
        raise TargetValidationError('Unreviewed native targeted Kindred source')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Incomplete original Matriarch source')
    return data


def register_native_kindred_target_cards(registry):
    registry.register_behavior(PREFIX+'wrapper', lambda c: ())
    registry.register_behavior(PREFIX+'active', lambda c: () if c.target_id is None else (
        Damage(c.target_id, c.source.attack, c.source_id, DamageKind.MINION_ABILITY),))
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health'],
            raw['tags'].get('KINDRED'), raw['tags'].get('BATTLECRY', 0)) != ('MINION', True, 4, 5, 4, 1, 0):
        raise TargetValidationError('Unreviewed native Matriarch face')
    card = CardDefinition(MATRIARCH, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=replace(metadata_from_record(raw), deck_identity=MATRIARCH), on_play=PREFIX+'wrapper',
        targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(MATRIARCH, 'body', wrapper=PREFIX+'wrapper', active=PREFIX+'active'))
    registry.register_kindred_target_profile(KindredTargetProfile(MATRIARCH))
