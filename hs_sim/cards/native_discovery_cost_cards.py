"""Storage Scuffle composes the ordinary price and Arcane damage pipelines."""
import json
from pathlib import Path

from hs_sim.engine.effects import Damage
from hs_sim.engine.model import CardDefinition, CardType, DamageKind, IntrinsicCostSpec, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

CARD, BODY = 'TLC_365', 'cards.discovery_cost.scuffle'
CONDITION, HISTORY = 'card_discovered_this_turn', 'discovery.card-this-turn-v1'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discovery-cost-v1.json'
BATCH_HASH = 'afcba336dba15a322aa140b6e8f697f8c53007b24ff27c5dac08ca4fbc304b6f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Storage Scuffle lost its complete original source')
    return data


def register_native_discovery_cost_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'SPELL' or raw['tags'].get('SPELL_SCHOOL') != 1:
        raise TargetValidationError('Storage Scuffle changed its printed Arcane spell face')
    registry.register_behavior(BODY, lambda c: (Damage(c.target_id, 3, c.source_id, DamageKind.SPELL),))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
        spell_school=SCHOOLS[1], targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)),
        intrinsic_costs=(IntrinsicCostSpec(set_to=0, condition=CONDITION, history_profile_id=HISTORY),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
