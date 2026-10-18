"""Captain Crowley adds physical native Cannoneer shots and summons existing tokens."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, ProducerQuantitySpec
from hs_sim.engine.native_producer_quantities import CANNONEER_SHOT, NativeProducerQuantityProfile
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, CANNON = 'CAP_106', 'CAP_107t'
PREFIX = 'cards.cannoneer_shot_quantity.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/cannoneer-shot-quantity-v1.json'
BATCH_HASH = '88945dbe94d58dbb06c9445c6abd2d200f0d8f944023045b80e8a2c6dc0d4534'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['dependencies'] or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['existing_dependencies']) != (CANNON,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('CAP_106e',)):
        raise TargetValidationError('Unreviewed complete Captain Crowley source')
    for row in data['cards'] + data['existing_dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Captain Crowley source')
    return data


def register_cannoneer_shot_quantity_card(registry):
    def summon(c):
        request = SummonByCard(c.player_id, (SummonEntryMaterial(CANNON),), SummonCause.capture(c))
        return (request, request)
    registry.register_behavior(PREFIX+'summon', summon)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=PREFIX+'summon',
        metadata=replace(metadata_from_record(raw), deck_identity=CARD))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_native_producer_quantity_profile(NativeProducerQuantityProfile(
        CARD, CANNON, ProducerQuantitySpec(CANNONEER_SHOT)))
