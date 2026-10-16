"""Ward of Earth forwards its actual entry grant into the shared pool summon."""
import json
from pathlib import Path
from hs_sim.engine.effects import GainArmor
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SpellSchool
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/pool-entry-keyword-v1.json'
BATCH_HASH='49b68f679ec123fbb5b0caaea386c96bf95b7c51f8706d6e97965a778fd4a13e'
WARD='EDR_060';POOL_ID='constructed.cards';BODY='cards.pool_entry_keyword.ward'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=5,max_cost=5)

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(WARD,) or
            tuple(x['record']['id']for x in data['evidence_only'])!=('EDR_060e',) or
            any(data[k]for k in('dependencies','existing_dependencies','skipped'))):
        raise TargetValidationError('Unreviewed complete pool entry keyword source')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete pool entry keyword raw row')
    return data

def register_pool_entry_keyword_cards(registry):
    raw=load_batch()['cards'][0]['record']
    if(raw['type'],raw['cost'],raw['tags'].get('CLASS'),raw['tags'].get('SPELL_SCHOOL'))!=('SPELL',5,2,4):
        raise TargetValidationError('Ward requires its current full spell face')
    registry.register_behavior(BODY,lambda c:(GainArmor(c.player_id,5),SummonFromPool(c.player_id,POOL_ID,QUERY,
        source_id=c.source_id,cause=SummonCause.capture(c),entry_keywords=(Keyword.TAUNT,))))
    card=CardDefinition(WARD,raw['name'],CardType.SPELL,cost=5,spell_school=SpellSchool.NATURE,
        metadata=metadata_from_record(raw),on_play=BODY)
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
