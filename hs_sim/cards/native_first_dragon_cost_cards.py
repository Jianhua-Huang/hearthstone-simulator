"""Naralex uses original submitted current tribes and the common price pipeline."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, CostAuraSpec, CostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_844'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-first-dragon-cost-v1.json'
BATCH_HASH = '9d0b03db4c7fc85aeb2f1d8912df7889725a4667b5b1d8b3ecdcbcf6cf7c6ea4'
AURA = CostAuraSpec(CostSpec(set_to=1,card_types=(CardType.MINION,)),
    tribes_any=('dragon',),first_per_turn=True)


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id'] for r in data['cards'])!=(CARD,):
        raise TargetValidationError('First Dragon source content differs from its complete reviewed pin')
    if canonical_digest(data['cards'][0]['record'])!=data['cards'][0]['record_sha256']:
        raise TargetValidationError('First Dragon complete original row changed')
    return data


def register_native_first_dragon_cost_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',7,7,7):
        raise TargetValidationError('Unreviewed Naralex physical face')
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw),cost_auras=(AURA,))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
