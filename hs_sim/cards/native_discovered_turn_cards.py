"""Unearthed Artifacts consumes a genuine selection fact in this global turn."""
import json
from pathlib import Path

from hs_sim.engine.card_discoveries import discovered_this_turn
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BODY, POOL = 'TLC_462', 'cards.discovered_turn.artifacts', 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discovered-turn-v1.json'
BATCH_HASH = '3af02a04090d9599d5cc581ded6bb6d3bc11364ea3e06f958ac363416de8e4b4'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards'] + data['evidence_only'])):
        raise TargetValidationError('Discovered-turn source lost its complete printed records')
    return data


def register_native_discovered_turn_cards(registry):
    data = load_batch()
    def artifacts(c):
        cost = 4 if discovered_this_turn(c.state, c.player_id) else 2
        return (GenerateFromPool(c.player_id, POOL,
            PoolQuery(kinds=(CardType.MINION,), collectible=True, min_cost=cost, max_cost=cost),
            source_id=c.source_id, destination='board', cause=SummonCause.capture(c)),)
    registry.register_behavior(BODY, artifacts)
    raw = data['cards'][0]['record']
    if raw['type'] != 'SPELL' or 'SPELL_SCHOOL' in raw['tags']:
        raise TargetValidationError('Unearthed Artifacts changed its printed spell face')
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'],
        on_play=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
