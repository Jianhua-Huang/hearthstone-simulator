"""Talya's permanent logical companion quantity, using existing player programs."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,PlayerEffectSpec,ProducerQuantitySpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .fixed_companion_cards import COMPANION_UNIT
from .metadata import metadata_from_record

TALYA='MEND_304'
PROGRAM='cards.companion_quantity.talya'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-companion-quantity-v1.json'
BATCH_HASH='848ec33b33dea8f254ea52356cf54479b350e00015ad6fcc31dfd166499ec217'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(value)!=BATCH_HASH or
            tuple(row['record']['id']for row in value['cards'])!=(TALYA,)or
            value['dependencies']or value['evidence_only']or value['skipped']):
        raise TargetValidationError('Talya requires her complete reviewed native definition')
    for row in value['cards']+value['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Companion quantity original source changed')
    return value


def register_native_companion_quantity_cards(registry):
    data=load_batch();raw=data['cards'][0]['record']
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,TALYA,
        producer_quantities=(ProducerQuantitySpec(COMPANION_UNIT,1),)))
    registry.register_behavior(PROGRAM,lambda c:(AddPlayerEffect(c.player_id,PROGRAM,c.source_id),))
    card=CardDefinition(TALYA,raw['name'],CardType.MINION,cost=raw['cost'],
        attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),battlecry=PROGRAM)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
