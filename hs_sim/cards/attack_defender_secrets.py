"""Bamboozle and Wandering Monster keep the original attacked subject."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.summoned_attack_targets import TransformAttackedMinion
from hs_sim.engine.interrupts import find_window,attack_live
from hs_sim.engine.native_attack_targets import original_event
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/attack-defender-secrets-v1.json'
BATCH_HASH='07b7ce7b3839133932979a4c7152352783c5e15e3c26d9eabfb1f9dc084509ab'
BAMBOOZLE,MONSTER=LEAVES=('BT_042','LOOT_079')
PREFIX='cards.attack_defender_secrets.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-attack-defender-secrets-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            d['evidence_only'] or len(d['official_observations'])!=4 or
            any(d[k]for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Defender Secrets lost complete source and original policy data')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Defender Secrets lost the complete unfiltered reference')
    return d


def pending(c,cid):
    if c.event is None or c.event.kind!='attack_declared':return None
    row=original_event(c.state,c.event);w=find_window(c.state,row.declaration.id)
    if not attack_live(c.state,w):return None
    target=c.state.entities[w.target_id];attacker=c.state.entities[w.source_id]
    if cid==BAMBOOZLE:
        return (w,target) if target.kind==CardType.MINION and target.controller==c.player_id else None
    return (w,target) if target.id==c.state.players[c.player_id].hero_id and attacker.controller!=c.player_id else None


def register_attack_defender_secrets(registry):
    data=load_batch();prepared=[]
    def body(c,cid):
        accepted=pending(c,cid)
        if accepted is None:return ()
        window,target=accepted
        if cid==BAMBOOZLE:
            return (TransformAttackedMinion(window,SourceAllocationFact.capture(c.state,c.source),SourceAllocationFact.capture(c.state,target)),)
        return (SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=3,max_cost=3),
            source_id=c.source_id,cause=SummonCause.capture(c),attack_window=window),)
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Defender Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Defender root must be a real Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('attack_declared',),PREFIX+cid,PREFIX+cid,requires_board_space=cid==MONSTER),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,lambda c,cid=cid:pending(c,cid) is not None)
        registry.register_behavior(PREFIX+cid,lambda c,cid=cid:body(c,cid))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
