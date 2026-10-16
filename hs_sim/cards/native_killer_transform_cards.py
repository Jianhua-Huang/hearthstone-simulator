"""Faceless Replicator binds transformation to the original fatal source."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference,TransformCapturedMinion
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-killer-transform-v1.json'
BATCH_HASH='3c186e4cb26787ba5839c0125da4f172cc1b9f1157c8edbed043d4cddffebca6'
REPLICATOR='CATA_185'
PREFIX='cards.native_killer_transform.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or data['dependencies']or tuple(x['record']['id']for x in data['cards'])!=(REPLICATOR,):
        raise TargetValidationError('Unreviewed native killer transform source set')
    row,=data['cards']
    if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete native killer source row')
    return data


def register_native_killer_transform_cards(registry):
    def transform_killer(c):
        if c.death is None:return ()
        cause=c.death.cause
        if (cause.source_id is None or not cause.source_entered_order or
                registry.card(cause.source_card_id).kind!=CardType.MINION):return ()
        reference=MinionReference(cause.source_id,cause.source_controller,cause.source_card_id,
            cause.source_zone_epoch,cause.source_entered_order)
        return(TransformCapturedMinion(reference,REPLICATOR,c.source_id),)
    registry.register_behavior(PREFIX+'transform',transform_killer)
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),raw['tags'].get('DEATHRATTLE'),raw['tags'].get('ELUSIVE'))!=('MINION',3,3,3,12,1,1):
        raise TargetValidationError('Unreviewed complete Faceless Replicator face')
    card=CardDefinition(REPLICATOR,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.ELUSIVE,),deathrattle=PREFIX+'transform',metadata=replace(metadata_from_record(raw),deck_identity=REPLICATOR))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
