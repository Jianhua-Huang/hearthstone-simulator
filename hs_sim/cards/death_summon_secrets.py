"""Redemption and Emergency Maneuvers over immutable original deaths."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.death_hand_returns import event_death
from hs_sim.engine.death_summon_entries import ResurrectOneHealth,SummonDormantDeathCopy
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/death-summon-entry-policies-v1.json'
BATCH_HASH='b708886b609454395de649b006f92679e47eee97ca8f49e81d7539fd08a5be1f'
REDEMPTION,EMERGENCY=LEAVES=('EX1_136','TSC_929')
PREFIX='cards.death_summon_secrets.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-death-summon-entry-policies-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=LEAVES or
            tuple(x['record']['id'] for x in d['evidence_only'])!=('TSC_929t',) or len(d['official_observations'])!=4 or
            any(d[k] for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in (*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Death summon Secrets lost their complete source and entry evidence')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Death summon Secrets lost their full unfiltered reference')
    return d


def register_death_summon_secrets(registry):
    data=load_batch();prepared=[]
    def condition(c):return event_death(c.state,c.event,c.player_id,require_grave=False) is not None
    def body(c,cid):
        death=event_death(c.state,c.event,c.player_id,require_grave=False)
        if death is None:return ()
        cause=SummonCause.capture(c)
        return ((ResurrectOneHealth(c.player_id,death.id,position=death.position,source_id=c.source_id,cause=cause),)
            if cid==REDEMPTION else (SummonDormantDeathCopy(death.id,cause),))
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Death summon Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Death summon root is not an actual Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('minion_died',),PREFIX+cid,PREFIX+cid,requires_board_space=True),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,condition)
        registry.register_behavior(PREFIX+cid,lambda c,cid=cid:body(c,cid))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
