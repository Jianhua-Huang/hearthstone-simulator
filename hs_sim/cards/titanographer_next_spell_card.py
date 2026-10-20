"""Osk's actual missing next-spell branch; the rolling root is not installed."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec
from hs_sim.engine.next_spell_bonuses import KIND
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='TLC_452t2';ROOT='TLC_452';SPEC='cards.osk.next_spell_bonus';BODY=SPEC+'.install'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/titanographer-next-spell-v1.json'
BATCH_HASH='65e57b091abc3a37d966490b6d493b77a41008ccccc8596a44546529281d24c1'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'));rows=(*data['cards'],*data['evidence_only'])
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,ROOT)or
            any(data[k]for k in('dependencies','existing_dependencies','skipped'))or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Osk next-spell branch requires its complete native form and original root')
    raw=data['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'))!=('MINION',6,6,6,1):
        raise TargetValidationError('Osk next-spell branch changed its original printed body')
    return data


def register_titanographer_next_spell_card(registry):
    raw=load_batch()['cards'][0]['record']
    registry.register_behavior(BODY,lambda c:(AddPlayerEffect(c.player_id,SPEC,c.source_id),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=6,attack=6,health=6,
        metadata=metadata_from_record(raw),battlecry=BODY)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_player_effect(PlayerEffectSpec(SPEC,CARD,kind=KIND,spell_damage=3,next_spell_cost_reduction=3))
