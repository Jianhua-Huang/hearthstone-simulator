"""Archdruid of Thorns gains complete frozen physical Deathrattle material."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.deathrattle_inheritance import GainDeathrattlesFromDeathsThisTurn
from hs_sim.engine.model import CardDefinition,CardType,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/deathrattle-inheritance-v1.json'
BATCH_HASH='5e79493254ce79d0e052a29c342960b7f497d03f7ceb12a349046f80c59db9a0'
THORNS='EDR_491'
PREFIX='cards.deathrattle_inheritance.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Deathrattle inheritance complete source pin changed')
    if tuple(x['record']['id']for x in data['cards'])!=(THORNS,)or data['dependencies']:
        raise TargetValidationError('Unreviewed Deathrattle inheritance card set')
    for row in data['cards']+data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original inheritance source row')
    return data


def register_deathrattle_inheritance_cards(registry):
    def gain(c):
        source=c.source
        if source.kind!=CardType.MINION or source.zone!=Zone.BOARD:return ()
        return(GainDeathrattlesFromDeathsThisTurn(c.player_id,MinionReference.capture(source)),)
    registry.register_behavior(PREFIX+'gain',gain)
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('BATTLECRY'),raw['tags'].get('DEATHRATTLE'))!=('MINION',2,3,2,9,1,None):
        raise TargetValidationError('Unreviewed complete Archdruid of Thorns face')
    card=CardDefinition(THORNS,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        battlecry=PREFIX+'gain',metadata=replace(metadata_from_record(raw),deck_identity=THORNS))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
