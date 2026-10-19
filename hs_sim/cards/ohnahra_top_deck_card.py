"""Ohn'ahra delegates her owner-end top three to physical deck executors."""
import json
from pathlib import Path

from hs_sim.engine.deck_card_plays import PlayTopDeckCards
from hs_sim.engine.model import CardDefinition, CardType, EndTurnSpec, TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='EDR_031'
PREFIX='cards.ohnahra_top_deck.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/ohnahra-top-deck-v1.json'
BATCH_HASH='1dbefd0bdb2215ca986994a635a557c5de663b1f35453b50c1e4a8b3ef9b5b51'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or len(data['cards'])!=1 or
            data['cards'][0]['record']['id']!=CARD or
            any(data[key] for key in ('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Ohnahra requires her complete reviewed original face')
    row=data['cards'][0];raw=row['record']
    if (canonical_digest(raw)!=row['record_sha256'] or
            (raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',9,5,11)):
        raise TargetValidationError('Ohnahra changed her complete original body')
    return data


def register_ohnahra_top_deck_card(registry):
    registry.register_behavior(PREFIX+'play',lambda c:(PlayTopDeckCards(
        c.player_id,c.source_id,SummonCause.capture(c),3),))
    raw=load_batch()['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=9,attack=5,health=11,
        metadata=metadata_from_record(raw),
        triggers=(TriggerSpec('turn_ended',PREFIX+'play',EndTurnSpec()),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:
        registry.register_pool_card(PoolCard.from_definition(card))
