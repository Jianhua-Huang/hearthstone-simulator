"""Raith Van Geist consumes actual successful Reborns, then attacks as a group."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.successful_summons import successful_reborns
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import Resurrect
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BODY = 'CAP_806', 'cards.raith_van_geist.body'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-actual-reborn-v1.json'
BATCH_HASH = '581a575d2e7dcab9b60a915420896619e4297a0da08e028820c3bc44f2b8cebe'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Raith Van Geist requires its complete fixed source')
    return data


def register_native_actual_reborn_cards(registry):
    raw = load_batch()['cards'][0]['record']
    def body(c):
        ids = tuple(row.reborn_death_id for row in successful_reborns(c.state, c.player_id))
        return (Resurrect(c.player_id, len(ids), source_id=c.source_id, cause=SummonCause.capture(c),
            death_ids=ids, attack_after_all=True),)
    registry.register_behavior(BODY, body)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
