"""Instant Multiverse uses the original mana-budget summon and resource effects."""
import json
from pathlib import Path

from hs_sim.engine.effects import Overload
from hs_sim.engine.mana_worth_summons import SummonManaWorth
from hs_sim.engine.model import CardDefinition, CardType, Keyword, RewindSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD, BODY = 'TIME_014', 'cards.instant_multiverse.body'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-mana-worth-v1.json'
BATCH_HASH = 'e5d34f6967f9d3328e535db7b0ba4a4ca4f54d8c45f9636b1af4e3afa9e71c61'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Instant Multiverse lost its complete fixed source')
    return data


def register_native_mana_worth_cards(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (SummonManaWorth(c.player_id, 'constructed.cards', 12,
        SummonCause.capture(c)), Overload(c.player_id, 3)))
    card = CardDefinition(CARD, raw['name'], CardType.SPELL, cost=raw['cost'], on_play=BODY,
        keywords=(Keyword.REWIND,), rewind=RewindSpec(retries=1), metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards: registry.register_pool_card(PoolCard.from_definition(card))
