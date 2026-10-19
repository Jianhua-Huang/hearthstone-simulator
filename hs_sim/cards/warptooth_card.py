"""Warptooth composes original damage facts and physical stored entry."""
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.damage_history import damage_records
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import CardDefinition, CardType, HandProgressSpec, HealthFlow, Keyword, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_421'
PREFIX = 'cards.warptooth.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/warptooth-v1.json'
BATCH_HASH = '4beb445337749c75e85878c326d5f66779e4b1bca3dcae4517b7c3deb7e2df6a'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Warptooth requires its complete original source and primary faces')
    row, = data['cards']; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
             raw['tags']['CLASS'], raw['tags']['RARITY'], raw['tags']['CHARGE']) !=
            ('MINION', 4, 3, 3, True, 10, 5, 1)):
        raise TargetValidationError('Original Warrior Legendary Charge Beast changed')
    return data


def four_damaged(c):
    result = health_result(c.event)
    if (result is None or result.flow != HealthFlow.DAMAGE.value or result.damage_dealt <= 0 or
            result.target_controller != c.player_id or result.active_player != c.player_id or
            result.turn != c.state.turn):
        return False
    seen = set()
    # A whole batch is already committed before its first event. Stop at this
    # original packet rather than granting credit for later notification work.
    for row in damage_records(c.state, target_player=c.player_id, turn=result.turn, target_own_turn=True):
        original = row.health_result
        if original.damage_dealt > 0:
            seen.add((original.target_id, original.target_zone_epoch, original.target_entered_order))
        if original == result:
            return len(seen) >= 4
    raise ResolutionError('Warptooth requires its complete original damage-result prefix')


def register_warptooth_card(registry):
    progress = HandProgressSpec('event', 1, on_complete=PREFIX+'summon', repeat=True,
        event='health_resolved', condition_id=PREFIX+'four_damaged', zone=(Zone.HAND, Zone.DECK))

    def summon(c):
        if c.trigger is None or c.trigger.hand_progress != progress:
            raise ResolutionError('Warptooth requires its original stored listener')
        source = c.source
        if source.card_id != CARD or source.kind != CardType.MINION or source.zone not in progress.zones:
            return ()
        return (SummonStoredCard(CardReference.capture(source), c.player_id, cause=SummonCause.capture(c)),)

    registry.register_trigger_condition(PREFIX+'four_damaged', four_damaged)
    registry.register_behavior(PREFIX+'summon', summon)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=4, attack=3, health=3,
        keywords=(Keyword.CHARGE,), hand_progress=progress, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
