"""Spire's original hand-sized entry followed by existing bound random combat."""
import json
from pathlib import Path

from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.model import CardDefinition, CardType, SummonStats
from hs_sim.engine.named_summon_followups import original_named_reference
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-hand-size-summon-attack-v1.json'
BATCH_HASH = '97283381e94008b1ec3fd31cb99451e79809660cc39f70975d1daaf317831131'
SPIRE, DEMON = 'JAIL_511', 'JAIL_511t'
PREFIX = 'cards.native_hand_size_summon_attack.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (SPIRE,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (DEMON,)):
        raise TargetValidationError('Hand-sized summon lost its complete native source')
    for row in data['cards'] + data['dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Hand-sized summon complete original row changed')
    return data


def register_native_hand_size_summon_attack_cards(registry):
    data = load_batch()
    def activate(c):
        size = len(c.state.players[c.player_id].hand)
        return (SummonByCard(c.player_id, (SummonEntryMaterial(DEMON,
            stats=SummonStats(size, size), on_summon=PREFIX+'attack'),), SummonCause.capture(c)),)
    registry.register_behavior(PREFIX+'activate', activate)
    registry.register_behavior(PREFIX+'attack', lambda c: (AttackRandomEnemyMinion(
        original_named_reference(c), c.player_id, c.source_id),))
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; kind = CardType(raw['type'].lower())
        kwargs = dict(on_use=PREFIX+'activate', durability=raw['health']) if kind == CardType.LOCATION else {}
        card = CardDefinition(raw['id'], raw['name'], kind, cost=raw['cost'],
            attack=raw['attack'] if kind == CardType.MINION else 0,
            health=raw['health'] if kind == CardType.MINION else 0,
            metadata=metadata_from_record(raw), **kwargs)
        registry.register_card(card)
        registry.register_pool_card(PoolCard.from_definition(card))
