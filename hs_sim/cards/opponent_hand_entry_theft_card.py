"""Rat Burglar consumes current physical hand entries in the active own turn."""
import json
from pathlib import Path

from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, TriggerSpec, Zone
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference, MoveCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_205'
BODY = 'cards.opponent_hand_entry_theft.take'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/opponent-hand-entry-theft-v1.json'
BATCH_HASH = 'ddb7010a547330b6020d1d538e24220efc057652220f6959e683279e4659a3f2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(row['record']['id'] for row in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Rat Burglar requires his complete original card record')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original Rat Burglar source')
    return data


def register_opponent_hand_entry_theft_card(registry):
    def take(c):
        interval = current_owner_turn(c.state)
        if interval.player_id != c.player_id:
            return ()
        work = []
        for entity_id in c.state.players[3-c.player_id].hand:
            entity = c.state.entities[entity_id]
            entry = hand_entry(c.state, entity.hand_entry_id)
            if entry.player_id == 3-c.player_id and entry.turn == interval.turn:
                # Current face/residence may differ from the acquired face.
                # A successful original transfer owns all capacity/lifecycle work.
                work.append(MoveCard(CardReference.capture(entity),c.player_id,Zone.HAND,source_id=c.source_id))
        return tuple(work)
    registry.register_behavior(BODY,take)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('TRIGGER_VISUAL')) != ('MINION',4,2,6,1):
        raise TargetValidationError('Rat Burglar changed his actual printed body or native trigger')
    card = CardDefinition(CARD,raw['name'],CardType.MINION,cost=4,attack=2,health=6,
        metadata=metadata_from_record(raw),triggers=(TriggerSpec('turn_ended',BODY,EndTurnSpec()),))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
