"""Native two-player physical discards consume the ordinary Rewind pipeline."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, Keyword, RewindSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import DiscardMatching
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discard-rewind-v1.json'
BATCH_HASH = '15ef4ea2ab5330cbf67fb7442894a4307c5ad585e08c78099dd56630a19afe15'
DOOMSPEAKER = 'TIME_008'
PREFIX = 'cards.native_discard_rewind.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Native discard/Rewind source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != (DOOMSPEAKER,) or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed native discard/Rewind family')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Native discard/Rewind full source record changed')
    return data


def register_native_discard_rewind_cards(registry):
    registry.register_behavior(PREFIX + 'discard_both', lambda c: (
        DiscardMatching(c.player_id, source_id=c.source_id),
        DiscardMatching(3-c.player_id, source_id=c.source_id),
    ))
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'MINION' or raw['collectible'] is not True or raw['tags'].get('REWIND') != 1:
        raise TargetValidationError('Native discard/Rewind requires its complete actual minion')
    card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        keywords=(Keyword.REWIND,), rewind=RewindSpec(), battlecry=PREFIX + 'discard_both',
        metadata=replace(metadata_from_record(raw), deck_identity=raw['id']))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
