"""Medivh's real Fabled trio consumes controlled-card costs and shared effects."""
import json
from pathlib import Path

from hs_sim.engine.effects import DestroyBatch,SilenceBatch
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import (CardDefinition,CardType,DamageKind,HealingKind,HealthFlow,
    HealthOp,HealthRule,IntrinsicCostSpec)
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

CARD='TIME_890';STAFF='TIME_890t';KARAZHAN='TIME_890t2'
PREFIX='cards.medivh.';POOL_ID='constructed.minions'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/medivh-fabled-v1.json'
BATCH_HASH='5495a256e0253a4147f16980b7475f7210144aaa3ba4aeb421cbe1f9de62838e'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=8,max_cost=8)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows=(*data['cards'],*data['dependencies'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in rows)!=(CARD,STAFF,KARAZHAN) or
            any(data[k]for k in('existing_dependencies','evidence_only','choice_only','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Medivh requires the complete actual priest Fabled trio')
    root,staff,location=(x['record']for x in rows)
    if ((root['type'],root['cost'],root['attack'],root['health'],root['tags'].get('FABLED'))!=('MINION',10,7,7,1) or
            (staff['type'],staff['cost'],staff['attack'],staff['health'])!=('WEAPON',10,1,3) or
            (location['type'],location['cost'],location['health'])!=('LOCATION',10,2) or
            any(x['tags'].get('IS_FABLED_BUNDLE_CARD')!=1 for x in(staff,location))):
        raise TargetValidationError('Medivh original bodies or Fabled companion material changed')
    return data


def register_medivh_fabled_cards(registry):
    def battlecry(c):
        targets=tuple(eid for player in(1,2)for eid in minions(c,registry,player)if eid!=c.source_id)
        return(SilenceBatch(targets),DestroyBatch(targets,c.source_id))
    def location(c):
        return tuple(SummonFromPool(c.player_id,POOL_ID,QUERY,source_id=c.source_id,
            cause=SummonCause.capture(c))for _ in range(2))
    registry.register_behavior(PREFIX+'battlecry',battlecry)
    registry.register_behavior(PREFIX+'location',location)
    data=load_batch()
    for row in(*data['cards'],*data['dependencies']):
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower())
        selector={CARD:KARAZHAN,STAFF:CARD,KARAZHAN:STAFF}[cid]
        fields={'intrinsic_costs':(IntrinsicCostSpec(set_to=0,condition='controlled_card',
            history_profile_id='controlled.current-card-v1',card_ids=(selector,)),)}
        if cid==CARD:fields.update(attack=7,health=7,battlecry=PREFIX+'battlecry')
        elif cid==STAFF:fields.update(attack=1,durability=3,health_rules=(
            HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,source_relation='friendly',damage_kinds=(DamageKind.SPELL,)),
            HealthRule(HealthFlow.HEALING,HealthOp.SCALE,2,source_relation='friendly',healing_kinds=(HealingKind.SPELL,))))
        else:fields.update(durability=2,on_use=PREFIX+'location')
        card=CardDefinition(cid,raw['name'],kind,cost=10,metadata=metadata_from_record(raw),**fields)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(CARD,(STAFF,KARAZHAN)))
