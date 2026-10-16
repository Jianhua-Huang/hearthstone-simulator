"""Mirrex's real original HAND source, separate from its copied printed face."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,HandMirrorSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/mirrex-native-hand-mirror-v1.json'
BATCH_HASH='451af403a810092757aa1e1b54c6ba16258efa42be68a3453d8d9244141e548a'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Mirrex lost its complete reviewed native-source pin')
    return value


def register_mirrex_native_cards(registry):
    data=load_batch()
    if len(data['cards'])!=1:raise TargetValidationError('Unreviewed native mirror family')
    row=data['cards'][0];raw=row['record'];recipe=row['recipe']
    if raw['id']!='DINO_407'or canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']is not True:
        raise TargetValidationError('Mirrex differs from its complete frozen minion face')
    evidence={x['record']['id']:x for x in data['enchantment_evidence']}
    if(evidence['DINO_407e']['record']['tags']['DEFINING_ENCHANTMENT']!=raw['dbf_id']or
            evidence['DINO_407e2']['record']['text_en']!='3/4.'):
        raise TargetValidationError('Mirrex lost its original source or separate3/4 evidence')
    card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        hand_mirror=HandMirrorSpec(recipe['attack'],recipe['health']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
