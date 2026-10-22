"""Shadowcrafter's real Combo and explicitly declared other-class primary."""
import json
from pathlib import Path

from hs_sim.engine.assemble_offers import Assemble
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='BE_702'
BODY='cards.shadowcrafter.assemble-other-class'
POOL='constructed.assemble'
QUERY=PoolQuery(kinds=(CardType.MINION,),class_mode='other',include_neutral=False)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/shadowcrafter-v1.json'
BATCH_HASH='a7d548534045640d7f913b3a4e432ee1e894be346372dba0e763e2305fa6a72f'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,)or
            any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))or
            data['official_faces_verified']!=2 or data['policy']['formal_pool_installed']is not False or
            data['policy']['no_ordinary_minion_pool_fallback']is not True):
        raise TargetValidationError('Shadowcrafter requires its complete source and explicit open curated-domain policy')
    row=data['cards'][0]
    if canonical_digest(row['record'])!=row['record_sha256']:
        raise TargetValidationError('Shadowcrafter complete original record changed')
    return data


def register_shadowcrafter_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=('MINION',2,3,2,True):
        raise TargetValidationError('Shadowcrafter lost its real two-cost 3/2 Combo face')
    def body(c):
        if c.combo is None or c.combo.payload.card_id!=CARD:
            raise ResolutionError('Shadowcrafter requires its actual original Combo')
        return (Assemble(c.player_id,POOL,c.source_id,primary_query=QUERY),)
    registry.register_behavior(BODY,body)
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=2,attack=3,health=2,
        keywords=(Keyword.COMBO,),combo=BODY,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
