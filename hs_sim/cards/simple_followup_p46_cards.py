"""Native current-deck threshold and original attack-declaration acquisition."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,Keyword,StatRelationLayer,StatRelationOperand,StatRelationSpec,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p46-v1.json'
BATCH_HASH='0d15004fb4e3964527b0769dbe49bf78045299d4ebca1e1cb1cfb0be4025966c'
DEFENDER='JAIL_311';SHAKU='CORE_CFM_781';LEGACY='CFM_781';ROOTS=(DEFENDER,SHAKU);DEPENDENCIES=();EVIDENCE_ONLY=(LEGACY,);POOL_ID='constructed.cards';PREFIX='cards.simple_followup_p46.'
RELATION=StatRelationSpec(operand=StatRelationOperand.CONTROLLER_DECK_COUNT,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=5,card_count=25,comparison='at_least')
QUERY=PoolQuery(collectible=True,class_mode='other',include_neutral=False)

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if(canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=ROOTS or tuple(x['record']['id']for x in data['evidence_only'])!=EVIDENCE_ONLY or any(data[k]for k in('dependencies','existing_dependencies','skipped'))):raise TargetValidationError('P46 complete reviewed recipe set changed')
    for row in data['cards']+data['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P46 original row')
    return data

def register_simple_followup_p46_cards(registry):
    data=load_batch();old=data['evidence_only'][0]['record'];raw_shaku=data['cards'][1]['record']
    if(old['id'],old['dbf_id'],raw_shaku['tags'].get('858'),raw_shaku['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'))!=(LEGACY,40905,40905,40905):raise TargetValidationError('Shaku requires its explicit complete legacy copy identity')
    def attack(c):
        if c.event is None or c.event.kind!='attack_declared'or c.event.source_id!=c.source_id:return()
        rows=[row for row in c.state.character_attack_history if row.declaration.id==dict(c.event.data)['window_id']]
        if len(rows)!=1:raise ResolutionError('Shaku lost its original character attack')
        row=rows[0];w=row.declaration
        if(c.event.player_id!=c.player_id or(w.source_id,w.target_id,w.player_id,row.declaration_event_cursor+1)!=(c.source_id,c.event.target_id,c.player_id,c.event.sequence)):raise ResolutionError('Shaku borrowed another attack declaration')
        return(GenerateFromPool(c.player_id,POOL_ID,QUERY,source_id=c.source_id),)
    registry.register_behavior(PREFIX+'attack',attack)
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];meta=metadata_from_record(raw)
        if raw['type']!='MINION'or raw['collectible']is not True or any(type(raw[k])is not int for k in('cost','attack','health')):raise TargetValidationError('P46 requires complete collectible minion faces')
        if cid==DEFENDER:kwargs=dict(keywords=(Keyword.TAUNT,),stat_relations=(RELATION,))
        else:meta=replace(meta,deck_identity=LEGACY);kwargs=dict(keywords=(Keyword.STEALTH,),triggers=(TriggerSpec('attack_declared',PREFIX+'attack'),))
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=meta,**kwargs);registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
