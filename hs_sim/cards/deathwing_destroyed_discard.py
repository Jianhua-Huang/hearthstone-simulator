"""Deathwing the Destroyer joins original destruction causes to ordinary discard."""
import json
from pathlib import Path

from hs_sim.engine.destruction_resources import DestroyMinionsForDiscard
from hs_sim.engine.model import CardDefinition, CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD='CS3_036'
ALIAS='LEG_CS3_036'
PREFIX='cards.deathwing_destroyed_discard.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/deathwing-destroyed-discard-v1.json'
BATCH_HASH='86eb018613f887122f2b2db9e2b033b834efb6d0362c243d09f0266771b17b58'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or value['dependencies'] or
            tuple(x['record']['id']for x in value['cards'])!=(CARD,) or
            tuple(x['record']['id']for x in value['evidence_only'])!=(ALIAS,) or
            len(value['official_faces'])!=2 or len(value['missing_direct_primary_faces'])!=2 or
            value['formal_pool_complete']is not False or value['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in value['cards']+value['evidence_only'])):
        raise TargetValidationError('Counted Deathwing destruction lost its complete original source')
    root=value['cards'][0]['record'];alias=value['evidence_only'][0]['record']
    if (any(root[k]!=alias[k]for k in ('name','text','text_en','cost','attack','health','type','collectible')) or
            any(root['dbf_id']not in x['face'].get('copyOfCardId',[])for x in value['official_faces'])):
        raise TargetValidationError('Full primary Deathwing association changed its original identity or body')
    return value


def register_deathwing_destroyed_discard(registry):
    raw=load_batch()['cards'][0]['record']
    if CARD in registry.cards:raise TargetValidationError('Counted Deathwing cannot overwrite an original identity')
    registry.register_behavior(PREFIX+'body',lambda c:(
        DestroyMinionsForDiscard(c.player_id,c.source_id,c.battlecry.id),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=metadata_from_record(raw),battlecry=PREFIX+'body')
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
