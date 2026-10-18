"""Maloriak copies the minion at the original successful discard event."""
import json
from pathlib import Path

from hs_sim.engine.discard_summons import capture
from hs_sim.engine.model import CardDefinition, CardType, TriggerSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'CATA_494'
BODY = 'cards.native_discard_summon.maloriak'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-discard-summon-v1.json'
BATCH_HASH = 'c7b8c3ea3c870c47ffc7b93654bbc4abeafaf9554f6df4cf81a7f1cef8b35a42'


def load_batch():
    data = json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or data['dependencies'] or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Maloriak requires its complete reviewed original source')
    return data


def register_native_discard_summon_cards(registry):
    def maloriak(c):
        if c.source.zone != Zone.BOARD or not c.source.active or c.source.health <= 0:
            return ()
        material = capture(c, registry)
        return () if material is None else (
            SummonByCard(c.player_id, (material,), SummonCause.capture(c)),)
    registry.register_behavior(BODY, maloriak)
    raw = load_batch()['cards'][0]['record']
    if (raw['type'], raw['cost'], raw['attack'], raw['health'], raw['collectible'],
            raw['tags'].get('CLASS'), raw['tags'].get('CARDRACE'), raw['tags'].get('RARITY')) != (
            'MINION', 7, 7, 7, True, 9, 24, 5):
        raise TargetValidationError('Maloriak printed face changed')
    card = CardDefinition(CARD, raw['name'], CardType.MINION, cost=7, attack=7, health=7,
                          metadata=metadata_from_record(raw),
                          triggers=(TriggerSpec('card_discarded', BODY),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
