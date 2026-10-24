"""Original physical Fan links and genuine Growfin terminal forms."""
import json
from pathlib import Path

from hs_sim.engine.attack_policies import GrantAttackPolicy
from hs_sim.engine.model import (AttackPolicySpec,AttackSourceBinding,AttackSourcePolicy,
    CardDefinition,CardType,HandDerivativeSpec,Keyword,SummonStats,TargetMode,TargetSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

FAN,GROWFIN,TINYFIN,GIGANTIC='ETC_109','MIS_307','MIS_307t','MIS_307t1'
DEPENDENCIES=(FAN,GROWFIN,TINYFIN,GIGANTIC)
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_source_bound_battlecries.'
LOCK,GROW=PREFIX+'lock',PREFIX+'grow'
LIVE=AttackSourcePolicy('live','preserve','ignore')
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/past-source-bound-battlecries-v1.json'
BATCH_HASH='0761f25db5f38352c338c87806e7520f628468773aacd115ffed0b4d8232dfb0'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(d['collectible_leaf_ids'])!=(FAN,GROWFIN) or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            any(d[k]for k in ('cards','existing_dependencies','evidence_only','choice_only',
                'skipped','numeric_normalizations','display_normalizations')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Source-bound Battlecries lost complete original cards and forms')
    return d


def register_past_source_bound_battlecries(registry):
    def lock(c):
        if c.target_id is None or c.source.kind!=CardType.MINION or c.source.zone!=Zone.BOARD:
            return ()
        ref=MinionReference.capture(c.state.entities[c.target_id])
        binding=AttackSourceBinding.capture(c.state,c.source_id,LIVE)
        return(GrantAttackPolicy(ref.entity_id,AttackPolicySpec('cannot_attack'),c.source_id,
            source_binding=binding,recipient=ref),)

    def grow(c):
        # Same current-stat convention as the existing native summon consumers;
        # zero Health remains zero and reaches the ordinary death checkpoint.
        stats=SummonStats(c.source.attack,max(0,c.source.health))
        return(SummonByCard(c.player_id,(SummonEntryMaterial(TINYFIN,stats),),SummonCause.capture(c)),)

    registry.register_behavior(LOCK,lock);registry.register_behavior(GROW,grow)
    for item in load_batch()['dependencies']:
        raw=item['record'];cid=raw['id'];extra={};keywords=()
        expected=(1,1,2,12,17)if cid==FAN else((8,8,8,8,14)if cid==GIGANTIC else(1,1,1,8,14))
        if (raw['type']!='MINION' or (raw['cost'],raw['attack'],raw['health'],raw['tags'].get('CLASS'),
                raw['tags'].get('CARDRACE'))!=expected or raw['collectible']!=(cid in(FAN,GROWFIN)) or
                raw['tags'].get('BATTLECRY')!=(None if cid==TINYFIN else 1)):
            raise TargetValidationError('Source-bound Battlecry changed its original printed face')
        if cid==FAN:
            extra=dict(battlecry=LOCK,targeting=TargetSpec(TargetMode.IF_AVAILABLE,
                zones=(Zone.BOARD,),kinds=(CardType.MINION,),exclude_source=False))
        elif cid==TINYFIN:
            if raw['tags'].get('RUSH')!=1:raise TargetValidationError('Tinyfin requires native Rush')
            keywords=(Keyword.RUSH,)
        else:
            marker=Keyword.GIGANTIFY if cid==GROWFIN else Keyword.GIGANTIC
            if raw['tags'].get(marker.value.upper())!=1:
                raise TargetValidationError('Growfin requires the actual printed size marker')
            keywords=(marker,);extra=dict(battlecry=GROW)
            if cid==GROWFIN:extra['hand_derivatives']=(HandDerivativeSpec(Keyword.GIGANTIFY,GIGANTIC),)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=keywords,metadata=metadata_from_record(raw),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
