"""Age of Oblivion delegates actual hand capacity and local payment to the core."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, CostSpec, PaymentType
from hs_sim.engine.pools import FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-pool-hand-fill-v1.json'
BATCH_HASH = '1fcca312145e5ac86ea4ce417e5c10dc8ec254f22fa39c600f5c9adc9fbb25ad'
OBLIVION = 'TIME_615'
BODY = 'cards.native_pool_hand_fill.oblivion'
POOL_ID = 'constructed.cards'
UNDEAD = PoolQuery(kinds=(CardType.MINION,), collectible=True, tribes_any=('undead',))


def load_batch():
    d = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d) != BATCH_HASH or tuple(x['record']['id'] for x in d['cards']) != (OBLIVION,) or
            any(d[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped')) or
            canonical_digest(d['cards'][0]['record']) != d['cards'][0]['record_sha256']):
        raise TargetValidationError('Age of Oblivion requires its complete pinned source')
    return d


def register_native_pool_hand_fill_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'SPELL' or raw['cost'] != 8 or 'SPELL_SCHOOL' in raw['tags']:
        raise TargetValidationError('Age of Oblivion requires its actual eight-cost spell face')
    registry.register_behavior(BODY, lambda c: (FillHandFromPool(GenerateFromPool(c.player_id,
        POOL_ID, UNDEAD, source_id=c.source_id,
        cost=CostSpec(payment=PaymentType.HEALTH, card_types=(CardType.MINION,)),
        expires_turn=c.state.turn)),))
    card = CardDefinition(OBLIVION, raw['name'], CardType.SPELL, cost=raw['cost'],
        metadata=metadata_from_record(raw), on_play=BODY)
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
