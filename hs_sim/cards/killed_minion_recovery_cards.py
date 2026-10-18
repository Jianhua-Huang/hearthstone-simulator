"""Frostmourne and Ursoc consume original lethal attribution and normal revival."""
import json
from pathlib import Path

from hs_sim.engine.forced_attack_sequences import AttackAllOtherMinions
from hs_sim.engine.model import BoardPresenceReference, CardDefinition, CardType, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.source_kills import KillSourceReference, ResurrectKilledMinions
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

FROSTMOURNE, URSOC = 'CORE_RLK_086', 'EDR_819'
PREFIX = 'cards.killed_minion_recovery.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/killed-minion-recovery-native-v1.json'
BATCH_HASH = '07103a6aacd6fa5ae11d87327f242fe9d0044a59216e518b76e5259cdad3c3dc'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH
            or tuple(x['record']['id'] for x in data['cards']) != (FROSTMOURNE, URSOC)
            or any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))
            or any(canonical_digest(x['record']) != x['record_sha256'] for x in data['cards'])):
        raise TargetValidationError('Kill recovery lost its complete native sources')
    return data


def register_killed_minion_recovery_cards(registry):
    def resurrect(c):
        if c.deathrattle is None:
            raise ValueError('Native kill recovery requires its Deathrattle invocation')
        position = deathrattle_position(c) if c.source.kind == CardType.MINION else None
        return (ResurrectKilledMinions(c.player_id, KillSourceReference.capture(c),
            c.deathrattle.id, SummonCause.capture(c), position),)
    def attack_all(c):
        if c.source.zone != Zone.BOARD or c.source.kind != CardType.MINION:
            return ()
        return (AttackAllOtherMinions(BoardPresenceReference.capture(c.state, c.source_id)),)
    registry.register_behavior(PREFIX + 'resurrect', resurrect)
    registry.register_behavior(PREFIX + 'attack_all', attack_all)
    for item in load_batch()['cards']:
        row = item['record']
        cid = row['id']
        if row['tags'].get('DEATHRATTLE') != 1:
            raise TargetValidationError('Kill recovery source lost its printed Deathrattle')
        if cid == FROSTMOURNE:
            if (row['type'], row['cost'], row['attack'], row['health']) != ('WEAPON', 6, 4, 3):
                raise TargetValidationError('Frostmourne changed its original weapon face')
            card = CardDefinition(cid, row['name'], CardType.WEAPON, cost=6, attack=4,
                durability=3, deathrattle=PREFIX + 'resurrect', metadata=metadata_from_record(row))
        else:
            if (row['type'], row['cost'], row['attack'], row['health']) != ('MINION', 9, 6, 14):
                raise TargetValidationError('Ursoc changed its original minion face')
            card = CardDefinition(cid, row['name'], CardType.MINION, cost=9, attack=6, health=14,
                battlecry=PREFIX + 'attack_all', deathrattle=PREFIX + 'resurrect', metadata=metadata_from_record(row))
        registry.register_card(card)
        if cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
