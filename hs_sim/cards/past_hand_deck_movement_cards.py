"""Safety Inspector and Sea Guide use original physical hand/deck movement."""
import json
from pathlib import Path

from hs_sim.engine.effects import Draw
from hs_sim.engine.hand_deck_movement import ShuffleLowestCostHandCard, exchange_bottom
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

INSPECTOR, FINLEY = 'DMF_125', 'TSC_908'
LEAVES = DEPENDENCIES = (INSPECTOR, FINLEY)
COLLECTIBLE_ROOTS = ()
PREFIX = 'cards.past_hand_deck.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/past-hand-deck-movement-v1.json'
BATCH_HASH = 'e74cf265aff02036f8dcf267fa1d2daa7f776c781f4e077de6c553ee045bda51'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(data['collectible_leaf_ids']) != LEAVES or
            tuple(x['record']['id'] for x in data['dependencies']) != LEAVES or
            any(data[k] for k in ('cards', 'existing_dependencies', 'evidence_only', 'choice_only',
                                 'skipped', 'numeric_normalizations', 'display_normalizations')) or
            any(canonical_digest(x['record']) != x['record_sha256'] for x in data['dependencies'])):
        raise TargetValidationError('Original hand/deck consumers lost their complete source records')
    return data


def register_past_hand_deck_movement_cards(registry):
    data = load_batch()
    registry.register_behavior(PREFIX+INSPECTOR, lambda c: (
        ShuffleLowestCostHandCard(c.player_id, c.source_id), Draw(c.player_id, source_id=c.source_id)))
    registry.register_behavior(PREFIX+FINLEY, exchange_bottom)
    for row in data['dependencies']:
        raw = row['record']; cid = raw['id']
        if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('BATTLECRY')) != ('MINION', 1, 1, 3, 1):
            raise TargetValidationError('Hand/deck consumer lost its native one-mana battlecry face')
        card = CardDefinition(cid, raw['name'], CardType.MINION, cost=1, attack=1, health=3,
            battlecry=PREFIX+cid, metadata=metadata_from_record(raw))
        registry.register_card(card); registry.register_pool_card(PoolCard.from_definition(card))
