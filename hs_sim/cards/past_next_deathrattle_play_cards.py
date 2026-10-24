"""Shattershambler uses a sourced next-Deathrattle price and original play tail."""
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier
from hs_sim.engine.model import CardDefinition,CardType,CostSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

SHAMBLER='TID_078'
DEPENDENCIES=(SHAMBLER,)
COLLECTIBLE_ROOTS=()
BODY='cards.past_next_deathrattle_play.shambler'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-next-deathrattle-play-v1.json'
BATCH_HASH='7e90c952563f0a6aaa6a258f0138c325759f5e6e1e23dbdb775e682b852e830d'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            any(d[k]for k in('cards','existing_dependencies','evidence_only','choice_only','skipped',
                'numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Next Deathrattle play lost its complete source and scope')
    return d


def register_past_next_deathrattle_play_cards(registry):
    registry.register_behavior(BODY,lambda c:(AddCostModifier(c.player_id,
        CostSpec(delta=-1,card_types=(CardType.MINION,)),uses_remaining=1,source_id=c.source_id,
        deathrattle_only=True,destroy_after_play=True),))
    raw=load_batch()['dependencies'][0]['record']
    if(raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
            raw['tags'].get('CARDRACE'),raw['tags'].get('BATTLECRY'))!=('MINION',1,1,3,7,18,1):
        raise TargetValidationError('Shattershambler requires its actual complete Rogue Elemental face')
    card=CardDefinition(SHAMBLER,raw['name'],CardType.MINION,cost=1,attack=1,health=3,
        battlecry=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
