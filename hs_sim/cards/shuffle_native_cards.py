"""The real whole-game semantic shuffle-count intrinsic consumer."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.deck_shuffles import CONDITION,HISTORY
from hs_sim.engine.model import CardDefinition,CardType,IntrinsicCostSpec,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/shuffle-native-effects-v1.json'
BATCH_HASH='05bf00183d26128d1a6856fc974e2ad0f203c915136b60b868750319f6d7a29d'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Shuffle consumer complete reviewed pin changed')
    return data


def register_shuffle_native_cards(registry):
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if(raw['id']!='TLC_520'or recipe['script']!='tracker'or raw['type']!='MINION'or not raw['collectible']
                or raw['tags'].get('RUSH')!=1 or canonical_digest(raw)!=row['record_sha256']):raise TargetValidationError('Unreviewed real shuffle price face')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=(Keyword.RUSH,),intrinsic_costs=(IntrinsicCostSpec(delta=-1,condition=CONDITION,history_profile_id=HISTORY),),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
