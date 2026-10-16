"""Mana Siphon's format-qualified generation and native combined creation."""
from dataclasses import asdict,replace
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/combined-shatter-generation-v1.json'
BATCH_HASH='4c6598feef9f195bfe57b946bf5278412e7e83a7207b9e839b03d52b044e69bc'
SIPHON='CATA_202'
POOL_ID='constructed.cards'
PREFIX='cards.combined_shatter_generation.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(SIPHON,)or data['dependencies']:
        raise TargetValidationError('Unreviewed combined Shatter generation source set')
    for row in data['cards']+data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete combined generation source row')
    return data


def register_combined_shatter_generation_cards(registry):
    data=load_batch()
    # Audit existing executable source families; they are not a replacement pool.
    for row in data['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Reviewed existing Shatter family changed')
    query=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='other',include_neutral=False,keywords_all=(Keyword.SHATTER,))
    registry.register_behavior(PREFIX+'generate',lambda c:(GenerateFromPool(c.player_id,POOL_ID,query,
        source_id=c.source_id,combined_shatter=True),))
    raw=data['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'),raw['collectible'])!=('SPELL',3,7,6,True):
        raise TargetValidationError('Unreviewed complete Mana Siphon face')
    card=CardDefinition(SIPHON,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SpellSchool.SHADOW,
        on_play=PREFIX+'generate',metadata=replace(metadata_from_record(raw),deck_identity=SIPHON))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
