"""Raincaller consumes one native budget on actual friendly spell damage each turn."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealthFlow,LimitedTriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p24-v1.json'
BATCH_HASH='5aefc322b60bacbe695079daef53e28687d1a31b54d697978989770aab8212f9'
RAIN='CATA_487';FIREBALL='CS2_029';ROOTS=(RAIN,);DEPENDENCIES=();PREFIX='cards.simple_followup_p24.'

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('P24 complete reviewed source pin changed')
    if(tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or tuple(x['record']['id']for x in data['existing_dependencies'])!=(FIREBALL,)or data['evidence_only']or data['skipped']):raise TargetValidationError('Unreviewed P24 root/dependency set')
    for row in data['cards']+data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete P24 original row')
    return data

def register_simple_followup_p24_cards(registry):
    data=load_batch();existing,=data['existing_dependencies']
    if canonical_digest(asdict(registry.card(FIREBALL)))!=existing['definition_sha256']:raise TargetValidationError('P24 complete existing Fireball definition changed')
    def eligible(c):
        result=c.health_result
        return(result is not None and result.flow==HealthFlow.DAMAGE.value and result.damage_dealt>0 and
               result.damage_kind==DamageKind.SPELL.value and result.source_controller==c.player_id)
    registry.register_trigger_condition(PREFIX+'actual_spell_damage',eligible)
    registry.register_behavior(PREFIX+'gain',lambda c:(BuffCapturedMinion(MinionReference.capture(c.source),2,0,c.source_id),))
    row,=data['cards'];raw=row['record']
    if raw['type']!='MINION'or raw['collectible']is not True:raise TargetValidationError('Raincaller requires its complete native minion face')
    card=CardDefinition(RAIN,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        metadata=replace(metadata_from_record(raw),deck_identity=RAIN),limited_triggers=(LimitedTriggerSpec('health_resolved',PREFIX+'gain',condition_id=PREFIX+'actual_spell_damage',uses=1,reset='turn'),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
