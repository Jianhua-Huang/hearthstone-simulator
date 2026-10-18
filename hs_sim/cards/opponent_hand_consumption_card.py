"""Iso'rath uses shared consumed-card parameters and ordinary dormancy."""
import json
from pathlib import Path

from hs_sim.engine.consumed_cards import (ConsumptionProfile, ConsumeOpponentHand,
                                         ResolveConsumedDeathrattle)
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_481'
PREFIX = 'cards.opponent_hand_consumption.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/opponent-hand-consumption-card-v1.json'
BATCH_HASH = '504beaf9cb486483e85c6dc6e09c6905fc3d69136688ad07225b66672ed7bc66'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or [x['record']['id'] for x in data['cards']] != [CARD]
            or [x['record']['id'] for x in data['evidence_only']] != ['CATA_481e']
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256']
                   for x in data['cards']+data['evidence_only'])):
        raise TargetValidationError('Iso\'rath lost its complete original source')
    return data


def register_opponent_hand_consumption_card(registry):
    def devour(c):
        if c.source.zone != Zone.BOARD:
            return ()
        return (ConsumeOpponentHand(MinionReference.capture(c.source), CARD),)
    def payload(c):
        if c.deathrattle is None:
            raise ValueError('Iso\'rath requires its actual Deathrattle')
        if c.deathrattle.ability.consumed_card_id is None:
            return ()
        return (ResolveConsumedDeathrattle(c.deathrattle.id),)
    registry.register_behavior(PREFIX+'devour', devour)
    registry.register_behavior(PREFIX+'payload', payload)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'] != 'MINION' or (raw['cost'],raw['attack'],raw['health']) != (5,5,3)
            or raw['tags'].get('DEATHRATTLE') != 1):
        raise TargetValidationError('Iso\'rath changed its original face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=5, attack=5, health=3,
        battlecry=PREFIX+'devour', deathrattle=PREFIX+'payload', metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_consumption_profile(ConsumptionProfile(CARD, 'opponent_hand'))
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
