"""Actual Core Avatar; the engine owns pack acceptance and native playback."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.card_packs import OpenStandardPack, StandardPackProfile
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CORE_WON_145'
BEHAVIOR = 'cards.avatar_standard_pack.open'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/avatar-standard-pack-v1.json'
BATCH_HASH = 'e3fe658d86646d574ec3e1f9ff76c18b3d0c3df0c3ed1500e4c785f36c397623'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or any(data[key] for key in ('dependencies','existing_dependencies','evidence_only')) or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Avatar requires its complete original Core face and reviewed source')
    return data


def register_avatar_standard_pack_card(registry):
    item = load_batch()['cards'][0]; raw = item['record']; meta = metadata_from_record(raw)
    if canonical_digest(asdict(meta)) != canonical_digest(item['metadata']): raise TargetValidationError('Avatar metadata changed')
    registry.register_behavior(BEHAVIOR, lambda c: (OpenStandardPack(c.player_id,
        SourceAllocationFact.capture(c.state, c.state.entities[c.source_id]), CARD),))
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=BEHAVIOR, metadata=meta)
    registry.register_card(definition)
    member = PoolCard.from_definition(definition)
    if CARD in registry.pool_cards:
        if registry.pool_cards[CARD] != member: raise TargetValidationError('Avatar changed an existing full pool record')
    else: registry.register_pool_card(member)
    registry.register_standard_pack_profile(StandardPackProfile(CARD))
