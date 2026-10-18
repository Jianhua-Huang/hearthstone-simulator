"""Unshackle Soul uses original held-play progress and the ordinary Shadow body."""
import json
from pathlib import Path

from hs_sim.engine.effects import Destroy
from hs_sim.engine.held_opponent_copies import CONDITION, HISTORY, KIND
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, IntrinsicCostSpec, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

CARD, BODY = 'JAIL_433', 'cards.held_opponent_copy.unshackle_soul'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-held-opponent-copy-v1.json'
BATCH_HASH = 'bbc08f78c6699604c1b0239d387ab874dec9f3dd72c4fce8b6e9764bb1b6eba0'


def load_batch():
    value = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value) != BATCH_HASH or tuple(row['record']['id'] for row in value['cards']) != (CARD,) or
            any(value[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Unshackle Soul requires her complete reviewed source')
    row = value['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Unshackle Soul original source changed')
    return value


def register_native_held_opponent_copy_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'SPELL' or raw['cost'] != 5 or raw['tags'].get('SPELL_SCHOOL') != 6:
        raise TargetValidationError('Unshackle Soul changed her printed Shadow face')
    registry.register_behavior(BODY, lambda c: (Destroy(c.target_id, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)), spell_school=SCHOOLS[6],
        hand_progress=HandProgressSpec(KIND),
        intrinsic_costs=(IntrinsicCostSpec(set_to=1, condition=CONDITION, history_profile_id=HISTORY),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
