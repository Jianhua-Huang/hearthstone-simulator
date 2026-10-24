"""Scourge Tamer consumes the existing original two-stage Zombeast craft."""
import json
from pathlib import Path

from hs_sim.engine.crafted_offers import CraftMinion
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .storm_gates_card import TEMPLATE, FIRST, SECOND, PARTS

CARD = 'RLK_821'
DEPENDENCIES = (CARD,)
COLLECTIBLE_ROOTS = ()
BODY = 'cards.past_scourge_tamer.craft'
EXISTING = (TEMPLATE, *PARTS)
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/past-scourge-tamer-v1.json'
BATCH_HASH = '30ab8b50d0f9eee0bf52dc614a54700f3385a5037c6f5df059861e1cd3ca9e03'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows = data['dependencies'] + data['existing_dependencies']
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != DEPENDENCIES or
            tuple(row['record']['id'] for row in rows) != (CARD, *EXISTING) or
            any(data[key] for key in ('cards', 'evidence_only', 'choice_only', 'skipped',
                'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(row['record']) != row['record_sha256'] for row in rows)):
        raise TargetValidationError('Scourge Tamer lost its complete original source and Zombeast dependencies')
    return data


def register_past_scourge_tamer_card(registry):
    data = load_batch()
    # These are existing native donation capabilities, never an eligibility list.
    for row in data['existing_dependencies'][1:]:
        raw = row['record']; old = registry.card(raw['id'])
        if (old.cost, old.attack, old.health, old.metadata) != (
                raw['cost'], raw['attack'], raw['health'], metadata_from_record(raw)):
            raise TargetValidationError('Scourge Tamer changed an existing original Beast component')
    blueprint = registry.crafted_minion_blueprints[TEMPLATE]
    if (blueprint.first_tribe, blueprint.second_tribe) != ('beast', 'beast'):
        raise TargetValidationError('Scourge Tamer requires its original Beast/Beast blueprint')
    registry.register_behavior(BODY, lambda c: (
        CraftMinion(c.player_id, TEMPLATE, FIRST, SECOND, c.source_id, max_part_cost=5),))
    raw = data['dependencies'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
            raw['tags'].get('RARITY'), raw['tags'].get('BATTLECRY')) != ('MINION', 1, 1, 2, 3, 4, 1):
        raise TargetValidationError('Scourge Tamer requires its real Hunter epic 1/2 Battlecry face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
