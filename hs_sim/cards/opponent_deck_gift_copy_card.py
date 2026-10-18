"""Nightmare Fuel's actual captured spell Combo and original opponent-deck copy."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.opponent_deck_gift_copy import DiscoverOpponentDeckCopy
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_528';BEHAVIOR='cards.nightmare_fuel.copy'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/opponent-deck-gift-copy-v1.json'
BATCH_HASH='835f15c5c2d027aeb6ade1da866cc54874e251197ee1ad87468b8c94fb45bbea'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or data['dependencies']or data['evidence_only']:
        raise TargetValidationError('Nightmare Fuel complete source pin changed')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Nightmare Fuel original source changed')
    return data


def register_opponent_deck_gift_copy_card(registry):
    def body(c):
        if c.cast is None:raise ValueError('Nightmare Fuel requires its actual spell execution')
        return (DiscoverOpponentDeckCopy(c.player_id,c.source_id,c.spell_conditions.combo),)
    registry.register_behavior(BEHAVIOR,body);raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('COMBO'))!=('SPELL',1,1):raise TargetValidationError('Unexpected Nightmare Fuel source shape')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=1,on_play=BEHAVIOR,keywords=(Keyword.COMBO,),
        metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
