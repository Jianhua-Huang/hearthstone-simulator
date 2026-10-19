"""Alarm-o-Matic uses one physical opposing-hand swap at its owner's start."""
import json
from pathlib import Path

from hs_sim.engine.minion_hand_swaps import SwapWithOpponentHand
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_502'
PREFIX = 'cards.alarm_hand_swap.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/alarm-hand-swap-v1.json'
BATCH_HASH = 'e3f8006c6ce5d31ade33fe77d2fb5dd09a0f4bd1c50471aee6f47a830429b694'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            tuple(x['record']['id'] for x in data['evidence_only']) != ('JAIL_502e',) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'skipped')) or
            data['task']['numeric_normalizations'] != {CARD: {'attack': 0}}):
        raise TargetValidationError('Alarm swap lost its reviewed original scope')
    for row in (*data['cards'], *data['evidence_only']):
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Alarm swap requires complete unchanged source rows')
    raw = data['cards'][0]['record']
    if ((raw['type'], raw['cost'], raw['attack'], raw['health']) != ('MINION', 3, None, 3)
            or 'ATK' in raw['tags'] or len(data['official_observations']) != 2
            or any(x['face']['attack'] != 0 for x in data['official_observations'])):
        raise TargetValidationError('Alarm swap lost its strictly reviewed printed zero')
    return data


def register_alarm_hand_swap_card(registry):
    def swap(c):
        if (c.event.player_id != c.player_id or c.source.zone != Zone.BOARD or
                c.source.controller != c.player_id):
            return ()
        return (SwapWithOpponentHand(MinionReference.capture(c.source), SummonCause.capture(c)),)
    registry.register_behavior(PREFIX + 'swap', swap)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=0, health=3,
        metadata=metadata_from_record(raw),
        triggers=(TriggerSpec('turn_started', PREFIX + 'swap'),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
