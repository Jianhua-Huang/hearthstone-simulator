"""Blast Engineer is a removable native provider for the ordinary damage layer."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition, CardType, HealthFlow, HealthOp, HealthRule
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CAP_104'
RELATION = 'friendly_pirate_minions_on_owner_turn'
RULE = HealthRule(HealthFlow.DAMAGE, HealthOp.ADD, 1, source_relation=RELATION)
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/owner-turn-pirate-damage-v1.json'
BATCH_HASH = 'c2f30e482dedcb3562dd24ed70cbc90d8f706b9052ed4540ad911c4959a82ef2'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or data['dependencies'] or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,)):
        raise TargetValidationError('Unreviewed complete Blast Engineer source')
    row = data['cards'][0]
    if canonical_digest(row['record']) != row['record_sha256']:
        raise TargetValidationError('Incomplete original Blast Engineer face')
    return data


def register_owner_turn_pirate_damage_card(registry):
    raw = load_batch()['cards'][0]['record']
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'],
        metadata=replace(metadata_from_record(raw), deck_identity=CARD), health_rules=(RULE,))
    registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
