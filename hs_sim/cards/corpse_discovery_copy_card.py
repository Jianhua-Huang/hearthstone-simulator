"""Blood Clone keeps its selected hand card and corpse-pays for its copy."""
import json
from pathlib import Path

from hs_sim.engine.model import CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

CARD='JAIL_451'
POOL_ID='constructed.cards'
BODY='cards.corpse_discovery_copy.clone'
QUERY=PoolQuery(kinds=(CardType.MINION,),min_cost=5,max_cost=5,collectible=True,class_mode='current')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/corpse-discovery-copy-card-v1.json'
BATCH_HASH='69beba50fef7e6c730d2e3fab6bb3b277498124d1479542953d05323254de4d4'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or [r['record']['id']for r in data['cards']]!=[CARD]
            or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped'))
            or any(canonical_digest(r['record'])!=r['record_sha256']for r in data['cards'])):
        raise TargetValidationError('Blood Clone lost its complete original source')
    return data


def register_corpse_discovery_copy_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['tags'].get('SPELL_SCHOOL'),raw['tags'].get('COST_BLOOD'),
            raw['tags'].get('CORPSE_SPENDER'))!=('SPELL',3,6,2,1):
        raise TargetValidationError('Blood Clone requires its original Shadow/Blood-rune face')
    registry.register_behavior(BODY,lambda c:(DiscoverFromPool(c.player_id,POOL_ID,QUERY,
        source_id=c.source_id,cause=SummonCause.capture(c),summon_copy_corpse_cost=5),))
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=3,spell_school=SpellSchool.SHADOW,
        metadata=metadata_from_record(raw),on_play=BODY)
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
