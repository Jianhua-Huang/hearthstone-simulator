"""Renferal's actual played-face growth and private one-target-turn traps."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.hand_play_locks import TrapRandomHandCards
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/renferal-native-traps-v1.json'
BATCH_HASH='ffc41fed52dd324fb150c24a4d59295e9af7034bc8b4ba6c75e678a5d05b0b7d'
ROOT='EDR_526';BODY='cards.renferal.trap'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Renferal lost its complete reviewed recipe pin')
    return value


def renferal(c):
    original=c.battlecry.play_id if c.battlecry is not None else None
    prior=sum(p.player_id==c.player_id and p.kind==CardType.MINION and p.card_id==ROOT
        and p.completed and p.id!=original for p in c.state.play_history)
    return(TrapRandomHandCards(3-c.player_id,1+prior,c.source_id),)


def register_renferal_native_cards(registry):
    data=load_batch()
    if len(data['cards'])!=1:raise TargetValidationError('Unreviewed Renferal family')
    row=data['cards'][0];raw=row['record']
    if(raw['id']!=ROOT or canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or
            raw['collectible']is not True or raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')!=1):
        raise TargetValidationError('Renferal differs from its complete reviewed face/base count')
    registry.register_behavior(BODY,renferal)
    card=CardDefinition(ROOT,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=BODY,metadata=replace(metadata_from_record(raw),deck_identity=row['recipe']['deck_identity']))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
