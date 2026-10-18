"""King Maluk and Infinite Banana compose ordinary discard, buff and acquisition."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.effects import AddToHand, Buff
from hs_sim.engine.model import CardDefinition, CardType, TargetSpec, Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CardReference, DiscardCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD = 'TIME_042'
BANANA = 'TIME_042t'
PREFIX = 'cards.retained_banana.'
BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/retained-banana-v1.json'
BATCH_HASH = '44c17778d3424ed237dca71fb89be8c73c6f053c85bf190fa1670f69aa7ae389'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data) != BATCH_HASH or
            tuple(x['record']['id'] for x in data['cards']) != (CARD,) or
            tuple(x['record']['id'] for x in data['dependencies']) != (BANANA,)):
        raise TargetValidationError('Unreviewed complete King Maluk source')
    for row in data['cards'] + data['dependencies'] + data['evidence_only']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Incomplete original King Maluk material')
    return data


def register_retained_banana_cards(registry):
    def maluk(c):
        original = tuple(CardReference.capture(c.state.entities[i])
            for i in c.state.players[c.player_id].hand)
        return (*tuple(DiscardCard(ref, c.source_id) for ref in original),
                AddToHand(c.player_id, BANANA, c.source_id))

    registry.register_behavior(PREFIX+'discard', maluk)
    registry.register_behavior(PREFIX+'banana', lambda c: (
        Buff(c.target_id, 1, 1, c.source_id), AddToHand(c.player_id, BANANA, c.source_id)))
    data = load_batch()
    for row in data['cards'] + data['dependencies']:
        raw = row['record']; root = raw['id'] == CARD
        definition = CardDefinition(raw['id'], raw['name'],
            CardType.MINION if root else CardType.SPELL, cost=raw['cost'],
            attack=raw['attack'] or 0, health=raw['health'] or 0,
            metadata=replace(metadata_from_record(raw), deck_identity=raw['id']),
            battlecry=PREFIX+'discard' if root else None,
            on_play=None if root else PREFIX+'banana',
            targeting=None if root else TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,)))
        registry.register_card(definition)
        registry.register_pool_card(PoolCard.from_definition(definition))
