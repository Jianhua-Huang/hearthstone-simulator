"""Ashamane uses current physical deck copies and original hand admission."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,CostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import FillHandWithDeckCopies
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_527'
BODY='cards.opponent_deck_fill.ashamane'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-opponent-deck-fill-v1.json'
BATCH_HASH='379bd8a3ad18977eb91616556b5494dd6cb3c3acdae37883e98f4028a93a7030'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(value)!=BATCH_HASH or tuple(x['record']['id']for x in value['cards'])!=(CARD,)or
            any(value[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))):
        raise TargetValidationError('Ashamane requires her complete reviewed native source')
    row=value['cards'][0]
    if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Ashamane original source changed')
    return value


def register_native_opponent_deck_fill_cards(registry):
    raw=load_batch()['cards'][0]['record']
    registry.register_behavior(BODY,lambda c:(FillHandWithDeckCopies(c.player_id,3-c.player_id,
        c.source_id,CostSpec(delta=-3)),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
