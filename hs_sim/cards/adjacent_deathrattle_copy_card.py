"""Primal Rockfang gains complete current adjacent Deathrattle material."""
import json
from pathlib import Path

from hs_sim.engine.deathrattle_copies import GainAdjacentDeathrattles
from hs_sim.engine.model import CardDefinition, CardType, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'BE_731'
BODY = 'cards.adjacent_deathrattle_copy.rockfang'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/adjacent-deathrattle-copy-v1.json'
BATCH_HASH = '1bb81f7e687420f567aaf752ef89682fe022e774e30b60dc877dcf3af5851206'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            any(data[k] for k in ('dependencies', 'existing_dependencies', 'evidence_only', 'choice_only', 'skipped')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Rockfang lost its complete reviewed original face')
    return data


def register_adjacent_deathrattle_copy_card(registry):
    registry.register_behavior(BODY, lambda c: (GainAdjacentDeathrattles(MinionReference.capture(c.source)),)
        if c.source.kind == CardType.MINION and c.source.zone == Zone.BOARD else ())
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['tags'].get('CLASS'), raw['tags'].get('BATTLECRY')) != (
            'MINION', 3, 3, 2, 3, 1):
        raise TargetValidationError('Rockfang requires its actual 3-cost 3/2 Hunter Battlecry face')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=3, attack=3, health=2,
        battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
