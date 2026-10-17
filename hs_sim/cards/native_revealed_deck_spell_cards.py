"""Spire Guard reads its actual revealed deck spell and original stored cost."""
import json
from pathlib import Path

from hs_sim.engine.deck_reveals import RevealRandomDeckCard, deck_reveal_result
from hs_sim.engine.model import CardDefinition, CardType, DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE, RandomSplitDamage, SplitDamageScope
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'JAIL_379'
BODY = 'cards.spire_guard.reveal'
REWARD = 'cards.spire_guard.original_reveal_reward'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/native-revealed-deck-spell-v1.json'
BATCH_HASH = 'b7b3f5c9107449f33f78cdb2ab9676c806916d4524bef8ee0b5ff70e02e90d1f'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or len(data['cards']) != 1 or
            data['cards'][0]['record']['id'] != CARD or
            canonical_digest(data['cards'][0]['record']) != data['cards'][0]['record_sha256']):
        raise TargetValidationError('Spire Guard requires its complete reviewed source pin')
    return data


def register_native_revealed_deck_spell_cards(registry):
    raw = load_batch()['cards'][0]['record']
    registry.register_behavior(BODY, lambda c: (RevealRandomDeckCard(c.player_id,
        source_id=c.source_id, on_result=REWARD),))
    def reward(c):
        result = deck_reveal_result(c.event)
        if result is None or result.player_id != c.player_id or c.event.source_id != c.source_id:
            raise ValueError('Spire Guard requires its actual original deck reveal')
        if result.card is None or result.card.cost < 5:
            return ()
        return (RandomSplitDamage(c.player_id, None, c.source_id, 5,
            scope=SplitDamageScope(kinds=(CardType.MINION,)),
            profile=NON_SPELL_PROFILE, kind=DamageKind.MINION_ABILITY),)
    registry.register_behavior(REWARD, reward)
    definition = CardDefinition(CARD, raw['name'], CardType.MINION, cost=raw['cost'],
        attack=raw['attack'], health=raw['health'], battlecry=BODY, metadata=metadata_from_record(raw))
    registry.register_card(definition)
    registry.register_pool_card(PoolCard.from_definition(definition))
