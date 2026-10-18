"""Flame Guardian composes stored buffs and an original-hand destroy deadline."""
import json
from pathlib import Path

from hs_sim.engine.hand_deadlines import ScheduleHandRemoval
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'FIR_928'
PREFIX = 'cards.hand_buff_deadline.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/hand-buff-deadline-card-v1.json'
BATCH_HASH = '9df33ac0a39d756728b68924a1a0e3bc3eb9d83551778fe3f286698cee15e1e0'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['cards']+data['evidence_only']
    if (canonical_digest(data) != BATCH_HASH or [r['record']['id'] for r in rows] !=
            [CARD,'FIR_928e','FIR_928e2','FIR_928e3']
            or any(data[k] for k in ('dependencies','existing_dependencies','skipped'))
            or any(canonical_digest(r['record']) != r['record_sha256'] for r in rows)):
        raise TargetValidationError('Flame Guardian lost its complete original source')
    return data


def register_hand_buff_deadline_card(registry):
    def improve(c):
        cards = tuple(CardReference.capture(c.state.entities[i])
                      for i in c.state.players[c.player_id].hand
                      if c.state.entities[i].kind == CardType.MINION)
        return (ScheduleHandRemoval(c.player_id,3,c.source_id,'destroy',cards=cards),
                *(BuffStoredCard(card,3,3,c.source_id) for card in cards))
    registry.register_behavior(PREFIX+'improve',improve)
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'MINION' or (raw['cost'],raw['attack'],raw['health']) != (5,5,5):
        raise TargetValidationError('Flame Guardian changed its original face')
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=5,health=5,
        battlecry=PREFIX+'improve',metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
