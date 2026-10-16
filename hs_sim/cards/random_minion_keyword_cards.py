"""Current Core Coghammer uses one public random recipient producer."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import MinionScope, minion_references
from hs_sim.engine.model import CardDefinition, CardType, Keyword, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_minion_keywords import RandomGrantMinionKeywords
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/random-minion-keywords-v1.json'
BATCH_HASH = '0cd84c105e86f20459fb20bf6ecd29bc5547424cd28d19f6d05466f78e2f7517'
COGHAMMER = 'CORE_GVG_059'
PREFIX = 'cards.random_minion_keywords.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Random keyword card lost its complete reviewed source pin')
    if tuple(row['record']['id'] for row in data['cards']) != (COGHAMMER,) or data['dependencies']:
        raise TargetValidationError('Unreviewed random keyword card family')
    for row in data['cards'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Random keyword complete source row changed')
    return data


def register_random_minion_keyword_cards(registry):
    def battlecry(c):
        refs = minion_references(c.state, registry, c.player_id, MinionScope(zones=(Zone.BOARD,)), c.source_id)
        return (RandomGrantMinionKeywords(refs, (Keyword.DIVINE_SHIELD, Keyword.TAUNT), c.source_id),)

    registry.register_behavior(PREFIX+'coghammer', battlecry)
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'WEAPON' or not raw['collectible'] or raw['tags'].get('BATTLECRY') != 1:
        raise TargetValidationError('Coghammer requires its actual complete weapon face')
    card = CardDefinition(raw['id'], raw['name'], CardType.WEAPON, cost=raw['cost'],
        attack=raw['attack'], durability=raw['health'], battlecry=PREFIX+'coghammer',
        metadata=replace(metadata_from_record(raw), deck_identity=raw['id']))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
