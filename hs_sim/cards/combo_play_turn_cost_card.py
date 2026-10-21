"""Aqir Hulk consumes original Combo-card hand roots through ordinary pricing."""
import json
from pathlib import Path

from hs_sim.engine.effects import Draw
from hs_sim.engine.model import CardDefinition, CardType, PlayerPlayedClassCostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_721'
PROFILE = 'cost.player-played-combo-turn-v1'
BODY = 'cards.combo_play_turn_cost.draw'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/combo-play-turn-cost-v1.json'
BATCH_HASH = '18fc395460a101f1a3d5d3bbb2ad6edefd25ccb09abe7366968f04327eac43f7'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped'))):
        raise TargetValidationError('Aqir Hulk lost its complete original Combo-card price source')
    return data


def register_combo_play_turn_cost_card(registry):
    row = load_batch()['cards'][0]; raw = row['record']
    if (canonical_digest(raw) != row['record_sha256'] or
            (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'),
             raw['tags'].get('CARDRACE'), raw['tags'].get('BATTLECRY')) != ('MINION', 8, 4, 5, 7, 20, 1)):
        raise TargetValidationError('Aqir Hulk requires its original eight-cost 4/5 Beast Battlecry')
    registry.register_behavior(BODY, lambda c: (Draw(c.player_id, source_id=c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=8, attack=4, health=5,
        player_played_class_cost=PlayerPlayedClassCostSpec(card_class=None, profile_id=PROFILE),
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
