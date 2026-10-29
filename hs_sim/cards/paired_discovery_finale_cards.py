"""Vast Wisdom and Infinitize use ordinary discovery, prices and spent returns."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import allocation_from_payload
from hs_sim.engine.discovery_cost_swaps import QUERY as PAIR_QUERY
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,Keyword,PlayerEffectSpec,TriggerSpec,Zone
from hs_sim.engine.player_effects import AddPlayerEffect,ConsumePlayerEffect
from hs_sim.engine.pools import DiscoverFromPool,PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.spent_spells import ReturnSpentSpell
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/paired-discovery-finale-v1.json'
BATCH_HASH='a1435c5a9d53525549ba55c75af7d88bf7d01f476d6ae8e77a2f7d410f80467f'
PAIR,FINALE='RLK_546','ETC_206'
LEAVES=(PAIR,FINALE)
PREFIX='cards.paired_discovery_finale.'
RETURN_ID=PREFIX+'return'
QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current')


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-paired-discovery-finale-v1'or
            tuple(v['record']['id']for v in d['cards'])!=LEAVES or len(d['official_observations'])!=4 or
            any(d[k]for k in('dependencies','new_standard_roots','formal_pool_complete','cn_calibrated'))or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in(*d['cards'],*d['evidence_only']))):
        raise TargetValidationError('Paired discovery/Finale requires complete original source rows and primary faces')
    p=ROOT/d['reference_document'];ref=json.loads(p.read_text(encoding='utf8'))
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256']or not set(LEAVES)<=set(ref['candidate_ids']):
        raise TargetValidationError('Paired discovery lost its full original past-Mage reference')
    return d


def register_paired_discovery_finale_cards(registry):
    data=load_batch()
    def pair(c):return (DiscoverFromPool(c.player_id,'constructed.cards',PAIR_QUERY,source_id=c.source_id,discoveries=2,swap_costs=True),)
    def finale(c):
        if c.cast is None:raise UnsupportedDefinitionError('Finale discovery requires its actual shared spell CAST')
        discovery=DiscoverFromPool(c.player_id,'constructed.cards',QUERY,source_id=c.source_id,cost=CostSpec(delta=-1))
        scheduled=(AddPlayerEffect(c.player_id,RETURN_ID,c.source_id,capture_health_source=True),)if c.cast.finale and c.source.zone==Zone.GRAVEYARD else()
        return (*scheduled,discovery)
    def return_source(c):
        if c.event is None or c.event.player_id!=c.player_id:return ()
        instance=c.player_effect
        if instance is None or instance.spec_id!=RETURN_ID or instance.source_allocation is None or instance.source_player_id!=c.player_id:
            raise UnsupportedDefinitionError('Finale return requires its original captured spell and beneficiary')
        return (ConsumePlayerEffect(c.player_id,instance,(
            ReturnSpentSpell(allocation_from_payload(instance.source_allocation),c.player_id),)),)
    bodies={PAIR:pair,FINALE:finale};cards=[]
    for row in data['cards']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='SPELL'or raw['cost']!=2 or cid in registry.cards:raise TargetValidationError('Unreviewed original paired-discovery face')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=2,on_play=PREFIX+cid,
            keywords=(Keyword.FINALE,)if cid==FINALE else(),metadata=metadata_from_record(raw))
        registry._validate_card(card);cards.append(card)
    for card in cards:
        registry.register_behavior(PREFIX+card.id,bodies[card.id]);registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_behavior(RETURN_ID,return_source)
    registry.register_player_effect(PlayerEffectSpec(RETURN_ID,FINALE,triggers=(TriggerSpec('turn_ended',RETURN_ID),)))
