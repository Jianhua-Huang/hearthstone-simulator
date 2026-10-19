"""Briarspawn's original owner-end attack uses the shared combat partition."""
import json
from pathlib import Path

from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, EndTurnSpec, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'EDR_453'
PREFIX = 'cards.briarspawn_drake.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/briarspawn-drake-v1.json'
BATCH_HASH = 'fb9ba5d138ee28b3cfa4ae1dd842997a8c3ec4fa942b845989909777ef4f7972'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Briarspawn requires its complete original face and primary sources')
    row, = data['cards']
    raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags']['CLASS'],
             raw['tags']['RARITY'], raw['tags']['CARDRACE']) != ('MINION', 10, 12, 7, 12, 1, 24)):
        raise TargetValidationError('Briarspawn original Neutral Common Dragon body changed')
    return data


def register_briarspawn_drake_card(registry):
    raw = load_batch()['cards'][0]['record']
    def attack(c):
        source = c.state.entities.get(c.source_id)
        if (source is None or source.kind != CardType.MINION or source.zone != Zone.BOARD or
                not source.active or source.health <= 0 or source.doomed):
            return ()
        return (AttackRandomEnemyMinion(BoardPresenceReference.capture(c.state, source.id),
            c.player_id, c.source_id, excess_to_hero=True),)
    registry.register_behavior(PREFIX+'end', attack)
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=10, attack=12, health=7,
        triggers=(TriggerSpec('turn_ended', PREFIX+'end', end_turn=EndTurnSpec()),),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
