"""Actual native damage, Taunt-bypass and no-other-minion providers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import (AttackPolicySpec,CardDefinition,CardType,HealthFlow,HealthLayer,HealthOp,HealthRule,Keyword,KeywordAuraSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-health-attack-providers-v1.json'
BATCH_HASH='8283f71a30433d76e061cdf4a7c2586ed744ae3dbe87a86a430bb403344733a1'
QUANTUM='TIME_060';BRALMA='TLC_228';GOLDRINN='EDR_480';KAYN='CORE_BT_187';SURVIVALIST='CATA_613'
ROOTS=(QUANTUM,BRALMA,GOLDRINN,KAYN,SURVIVALIST)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Native providers lost their complete reviewed source pin')
    return data


def register_native_health_attack_provider_cards(registry):
    data=load_batch()
    if tuple(row['record']['id']for row in data['cards'])!=ROOTS or data['dependencies']:raise TargetValidationError('Unreviewed native provider set')
    declarations={
        QUANTUM:dict(health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,layer=HealthLayer.TARGET,target_relation='self'),)),
        BRALMA:dict(health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.ADD,1,source_relation='friendly_elemental_minions'),)),
        GOLDRINN:dict(keywords=(Keyword.RUSH,),health_rules=(HealthRule(HealthFlow.DAMAGE,HealthOp.SCALE,2,source_relation='friendly_beast_minions'),)),
        KAYN:dict(keywords=(Keyword.CHARGE,),attack_policies=(AttackPolicySpec('friendly_ignore_taunt'),)),
        SURVIVALIST:dict(keyword_auras=(KeywordAuraSpec(Keyword.IMMUNE,'self',condition='controller_no_other_minions'),)),
    }
    legacy=next(row['record']for row in data['evidence_only']if row['record']['id']=='BT_187')
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']is not True:raise TargetValidationError('Native provider face is incomplete')
        if cid==KAYN and(raw['tags'].get('858')!=legacy['dbf_id']or legacy['dbf_id']!=58202):raise TargetValidationError('Kayn lost its original canonical identity')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity='BT_187'if cid==KAYN else cid),**declarations[cid])
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
