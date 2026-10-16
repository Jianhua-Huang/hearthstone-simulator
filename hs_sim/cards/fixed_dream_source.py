"""Hopeful Dryad gets one of all five complete, exact Dream cards."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import GenerateFromCandidates, PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

DRYAD = 'EDR_001'
DREAMS = ('DREAM_01', 'DREAM_02', 'DREAM_03', 'DREAM_04', 'DREAM_05')
PREFIX = 'cards.fixed_dream_source.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/fixed-dream-source-v1.json'
BATCH_HASH = '70d6dda295fcc8e9077650c5c2d923028dac7e062b38c770ed8e628aec119525'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Fixed Dream source lost its complete pin')
    if (tuple(x['record']['id'] for x in data['cards']) != (DRYAD,) or data['dependencies']
            or tuple(x['record']['id'] for x in data['existing_dependencies']) != DREAMS):
        raise TargetValidationError('Unreviewed complete Dream recipe')
    for row in data['cards'] + data['existing_dependencies']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete fixed Dream source row')
    return data


def register_fixed_dream_source(registry):
    data = load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id']))) != row['definition_sha256']:
            raise TargetValidationError('Fixed Dream source requires all five exact complete definitions')
    registry.register_behavior(PREFIX + 'dryad', lambda c: (GenerateFromCandidates(c.player_id, DREAMS, c.source_id),))
    raw = data['cards'][0]['record']
    if (raw['type'], raw['collectible'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', True, 3, 3, 3, 1):
        raise TargetValidationError('Unreviewed native Hopeful Dryad face')
    card = CardDefinition(DRYAD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        battlecry=PREFIX+'dryad', metadata=replace(metadata_from_record(raw), deck_identity=DRYAD))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
