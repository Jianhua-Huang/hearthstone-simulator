"""A printed Frost Rune Map uses the existing original-card followup."""
import json
from pathlib import Path

from hs_sim.engine.hand_choice_followups import DiscoverForPlayFollowup
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import DiscoverFromPool, PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BODY, POOL = 'TLC_435', 'cards.cavern_map.body', 'constructed.cards'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-cavern-map-v1.json'
BATCH_HASH = '9095a2ae1b3d2d67953fb8456f83563967f268a3368df7c6308cb9f95d471356'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            any(canonical_digest(x['record']) != x['record_sha256']
                for x in data['cards'] + data['evidence_only'])):
        raise TargetValidationError('Cavern map lost its complete printed source')
    return data


def register_native_cavern_map_cards(registry):
    data = load_batch()
    registry.register_behavior(BODY, lambda c: (DiscoverForPlayFollowup(DiscoverFromPool(
        c.player_id, POOL, PoolQuery(collectible=True, runes_any=('frost',)), source_id=c.source_id)),))
    raw = data['cards'][0]['record']
    if raw['type'] != 'SPELL' or 'SPELL_SCHOOL' in raw['tags']:
        raise TargetValidationError('Cavern map requires its original spell identity')
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
                          metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
