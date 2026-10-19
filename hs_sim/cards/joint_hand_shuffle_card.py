"""Togwaggle delegates the real hand mix to the public physical zone layer."""
import json
from pathlib import Path

from hs_sim.engine.joint_hand_shuffle import ShuffleHandsTogether
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_852'
BODY = 'cards.joint_hand_shuffle.mix'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/joint-hand-shuffle-v1.json'
BATCH_HASH = '3d5a20f7b5220854d0f84fad638609b5b4fffac76c62bbf3b69e015d037598ac'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Togwaggle requires his complete original card record')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Togwaggle source')
    return data


def register_joint_hand_shuffle_card(registry):
    registry.register_behavior(BODY, lambda c: (ShuffleHandsTogether(c.player_id, c.source_id),))
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 8, 5, 5, 1):
        raise TargetValidationError('Togwaggle changed his actual printed body or Battlecry')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=8, attack=5, health=5,
        metadata=metadata_from_record(raw), battlecry=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
