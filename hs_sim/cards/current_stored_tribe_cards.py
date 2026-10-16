"""Dinositter reads actual current hand tribes through the existing random buff."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.model import CardDefinition, CardType, CostSpec, EndTurnSpec, TriggerSpec
from hs_sim.engine.pools import PoolCard, PoolQuery
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/current-stored-tribe-v1.json'
BATCH_HASH = 'f0467ded698960c804ebc4a5e7ccaa575b56e21987ca124ccfc27866cc2ff41d'
DINOSITTER = 'TLC_822'
PREFIX = 'cards.current_stored_tribe.'


def load_batch():
    data = json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data) != BATCH_HASH:
        raise TargetValidationError('Current stored tribe source pin changed')
    if tuple(row['record']['id'] for row in data['cards']) != (DINOSITTER,) or data['dependencies'] or data['evidence_only']:
        raise TargetValidationError('Unreviewed current stored tribe family')
    for row in data['cards']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise TargetValidationError('Current stored tribe full source row changed')
    return data


def register_current_stored_tribe_cards(registry):
    def end(c):
        if c.event is None or c.event.player_id != c.player_id:
            return ()
        return (RandomBuffStoredMinion(c.player_id, query=PoolQuery(tribes_any=('beast',)),
            source_id=c.source_id, cost=CostSpec(delta=-1), tribe_basis='current'),)

    registry.register_behavior(PREFIX+'dinositter', end)
    raw = load_batch()['cards'][0]['record']
    if raw['type'] != 'MINION' or raw['collectible'] is not True:
        raise TargetValidationError('Dinositter requires its complete real minion')
    card = CardDefinition(raw['id'], raw['name'], CardType.MINION, cost=raw['cost'], attack=raw['attack'],
        health=raw['health'], triggers=(TriggerSpec('turn_ended', PREFIX+'dinositter', EndTurnSpec()),),
        metadata=replace(metadata_from_record(raw), deck_identity=raw['id']))
    registry.register_card(card)
    registry.register_pool_card(PoolCard.from_definition(card))
