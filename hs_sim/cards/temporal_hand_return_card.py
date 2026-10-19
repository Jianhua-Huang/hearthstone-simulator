"""Runi preserves original hand minions through the shared future return."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.future_hand_returns import SendHandMinionsFuture
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TIME_EVENT_998'
PREFIX='cards.temporal_hand_return.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/temporal-hand-return-v1.json'
BATCH_HASH='d6a98eb06ca2858fac9c79227ef5122fbaef43103ec0c7a15c63bd7b93440830'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(r['record']['id']for r in data['cards'])!=(CARD,)
            or data['dependencies']or data['evidence_only']):raise TargetValidationError('Runi complete source pin changed')
    row=data['cards'][0]
    if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Runi original row changed')
    return data


def register_temporal_hand_return_card(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',5,5,5):raise TargetValidationError('Unexpected Runi source face')
    registry.register_behavior(PREFIX+'send',lambda c:(SendHandMinionsFuture(c.player_id,c.source_id),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=5,health=5,battlecry=PREFIX+'send',
        metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
