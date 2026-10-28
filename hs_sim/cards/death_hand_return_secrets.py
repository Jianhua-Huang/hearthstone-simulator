"""Two real death Secrets over an original physical graveyard return."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.death_hand_returns import ReturnDeadMinion,event_death
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.secret_conditions import SecretHandSpace
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/death-hand-returns-v1.json'
BATCH_HASH='d808288e352125fab35bb133643bdd6f5291f3e6dd7fcc623c1561de4a2d77bf'
KODO,CHEAT=LEAVES=('CFM_800','LOOT_204')
PREFIX='cards.death_hand_returns.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-death-hand-returns-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id'] for x in d['dependencies'])!=LEAVES or
            tuple(x['record']['id'] for x in d['evidence_only'])!=('LOOT_204e',) or len(d['official_observations'])!=4 or
            any(d[k] for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256'] for x in (*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Death hand Secrets lost their complete source and cost evidence')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Death hand Secrets lost their full unfiltered reference')
    return d


def register_death_hand_return_secrets(registry):
    data=load_batch();prepared=[]
    def condition(c):return SecretHandSpace(event_death(c.state,c.event,c.player_id) is not None)
    def body(c,cut):
        death=event_death(c.state,c.event,c.player_id)
        return () if death is None else (ReturnDeadMinion(death.id,
            SourceAllocationFact.capture(c.state,c.state.entities[death.entity_id]),
            SourceAllocationFact.capture(c.state,c.source),cut),)
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Death hand Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Death hand root is not an actual Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('minion_died',),PREFIX+cid,PREFIX+cid),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid,cut in ((KODO,0),(CHEAT,2)):
        registry.register_secret_condition(PREFIX+cid,condition)
        registry.register_behavior(PREFIX+cid,lambda c,cut=cut:body(c,cut))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
