"""Agamaggan grants one bounded opponent-health account switch to normal costs."""
import json
from pathlib import Path

from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, PaymentType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_489'
PREFIX = 'cards.agamaggan_health_payment.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/agamaggan-health-payment-v1.json'
BATCH_HASH = 'c1340ad9be7a453cc10bee519e56789d42dc514085f75accdde288234dd71839'
LIMIT = 10


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            tuple(row['record']['id'] for row in data['evidence_only']) != ('EDR_489e1','EDR_489e2') or
            any(data[key] for key in ('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Agamaggan requires his complete reviewed face and original thorns evidence')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Agamaggan source record')
    raw = data['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY')) != ('MINION',10,9,9,1):
        raise TargetValidationError('Agamaggan changed his complete original body')
    return data


def register_agamaggan_health_payment_card(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(PREFIX+'grant', lambda c: (AddCostModifier(c.player_id,
        CostSpec(payment=PaymentType.OPPONENT_HEALTH), uses_remaining=1,
        source_id=c.source_id, maximum_cost=LIMIT),))
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=10,attack=9,health=9,
        battlecry=PREFIX+'grant',metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
