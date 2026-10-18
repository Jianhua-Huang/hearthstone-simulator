"""Toreth's native friendly three-hit shields reuse ordinary shield abilities."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.shield_durability import RULE
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='EDR_258'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/divine-shield-hit-provider-v1.json'
BATCH_HASH='1454f7e9b734fa7f42623bf2be2433bb0d2f43dad4597268f2bfa37d2358adb9'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or data['dependencies']or data['evidence_only']:
        raise TargetValidationError('Toreth complete source pin changed')
    row=data['cards'][0]
    if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Toreth original source changed')
    return data


def register_divine_shield_hit_provider_card(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'])!=('MINION',5,3,4):raise TargetValidationError('Unexpected Toreth source shape')
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=5,attack=3,health=4,keywords=(Keyword.DIVINE_SHIELD,Keyword.TAUNT),
        health_rules=(RULE,),metadata=replace(metadata_from_record(raw),deck_identity=CARD))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
