"""Violet Punisher's real enemy-targeted Bonus Effects theft."""
import json
from pathlib import Path

from hs_sim.engine.bonus_effects import StealBonusEffects
from hs_sim.engine.model import CardDefinition, CardType, TargetMode, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_101'
BODY = 'cards.violet_punisher.steal'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/violet-tormentor-v1.json'
BATCH_HASH = '61bf5427557d87954b924a5c0bbb6beb29bf4fcb4876be3acbe587cbe71a1f7d'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'skipped'))):
        raise TargetValidationError('Violet Punisher requires its complete original source and primary faces')
    row, = data['cards']; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
             raw['tags']['CLASS'], raw['tags']['RARITY'], raw['tags']['BATTLECRY']) !=
            ('MINION', 3, 4, 3, True, 12, 1, 1)):
        raise TargetValidationError('Original neutral three-cost 4/3 Battlecry changed')
    return data


def register_violet_tormentor_card(registry):
    def body(c):
        victim = c.state.entities.get(c.target_id)
        if (victim is None or victim.kind != CardType.MINION or victim.zone != Zone.BOARD or
                not victim.active or victim.health <= 0 or victim.doomed):
            return ()
        source = c.source
        beneficiary = MinionReference.capture(source) if source.kind == CardType.MINION and source.zone == Zone.BOARD else None
        return (StealBonusEffects(MinionReference.capture(victim), beneficiary, c.source_id),)
    registry.register_behavior(BODY, body)
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=4, health=3,
        battlecry=BODY, targeting=TargetSpec(TargetMode.IF_AVAILABLE, zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'),
        metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
