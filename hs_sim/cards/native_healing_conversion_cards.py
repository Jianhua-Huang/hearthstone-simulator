"""Ruby Sanctum installs a source-independent next whole Healing effect."""
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec
from hs_sim.engine.next_healing_conversion import KIND
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_301'
BODY = 'cards.native_healing_conversion.sanctum'
PROGRAM = BODY + '_next'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-healing-conversion-v1.json'
BATCH_HASH = 'c74973568a66bf91998a2245a6c737de3a79d2ca865858746ce5ccdf4acfb883'


def load_batch():
    d = json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(d) != BATCH_HASH or len(d['cards']) != 1 or
            d['cards'][0]['record']['id'] != CARD or
            canonical_digest(d['cards'][0]['record']) != d['cards'][0]['record_sha256']):
        raise TargetValidationError('Ruby Sanctum requires its complete reviewed original source')
    return d


def register_native_healing_conversion_cards(registry):
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health']) != ('LOCATION', 1, None, 3):
        raise TargetValidationError('Ruby Sanctum printed face changed')
    registry.register_player_effect(PlayerEffectSpec(PROGRAM, CARD, kind=KIND))
    registry.register_behavior(BODY, lambda c: (AddPlayerEffect(c.player_id, PROGRAM, c.source_id),))
    card = CardDefinition(CARD, raw['name'], CardType.LOCATION, cost=1, durability=3,
                          on_use=BODY, metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
