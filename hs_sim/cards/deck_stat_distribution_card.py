"""Vyranoth's original starting-cost gate and balanced current-deck reward."""
import json
from pathlib import Path

from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckMinionCostSumCondition
from hs_sim.engine.deck_stat_distribution import DistributeDeckStatPairs
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_213'
BODY = 'cards.vyranoth.distribute'
CONDITION = DeckMinionCostSumCondition(100,'printed')
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/deck-stat-distribution-v1.json'
BATCH_HASH = 'd8ab95080cc99b8db97e23e545db323969623f4e1b6e4f1234a87f3e4cc866ce'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('CATA_213e','CATA_213e2')):
        raise TargetValidationError('Vyranoth requires its complete reviewed native source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Vyranoth source')
    return data


def register_deck_stat_distribution_card(registry):
    raw = load_batch()['cards'][0]['record']
    def battlecry(c):
        if c.battlecry is None:
            raise ValueError('Vyranoth requires its actual native Battlecry')
        return (CheckDeckCondition(c.player_id,CONDITION,
            (DistributeDeckStatPairs(c.player_id,50,c.source_id),),()),)
    registry.register_behavior(BODY,battlecry)
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
