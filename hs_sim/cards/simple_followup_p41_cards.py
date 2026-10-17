"""Two native self-transform triggers over captured original minion references."""
import json
from pathlib import Path
from hs_sim.engine.cross_zone import TransformMinionFromPool
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,HealthFlow,TriggerSpec
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p41-v1.json'
BATCH_HASH='74b58d2f06248a7da591f0edfe8a05f5a0790ccb12a13a21fd88e7188c14de89'
VARIANT='TIME_049';VOYAGER='TIME_055';ROOTS=(VARIANT,VOYAGER);DEPENDENCIES=();POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p41.'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True)

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or any(data[k]for k in('dependencies','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P41 complete reviewed recipe set changed')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P41 original row')
    return data

def register_simple_followup_p41_cards(registry):
    def transform(c,delta):return(TransformMinionFromPool(MinionReference.capture(c.source),POOL_ID,delta,query=QUERY,cost_basis='printed',retain_cost_basis=None,source_id=c.source_id),)
    def variant(c):
        return transform(c,3)if living_source(c)and c.event.player_id==c.player_id else()
    def voyager(c):
        result=c.health_result
        if result is None:raise ResolutionError('Unknown Voyager requires its original settled health result')
        if(not living_source(c)or result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0 or
           result.target_id!=c.source_id or result.health_after<=0 or result.doomed_after or
           (result.target_card_id,result.target_controller,result.target_zone_epoch,result.target_entered_order)!=
           (c.source.card_id,c.player_id,c.source.zone_epoch,c.source.entered_order)):return()
        return transform(c,2)
    registry.register_behavior(PREFIX+VARIANT,variant);registry.register_behavior(PREFIX+VOYAGER,voyager)
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='MINION'or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):raise TargetValidationError('P41 requires complete collectible minion faces')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),triggers=(TriggerSpec('turn_started'if cid==VARIANT else'health_resolved',PREFIX+cid),))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
