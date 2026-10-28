"""Misdirection and Sudden Betrayal preserve one accepted original attack."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.attack_redirects import RandomRedirectAttack,pending_attack
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/attack-redirect-secrets-v1.json'
BATCH_HASH='2193490a3c7896fae495ef633596488dc9aa90c85a4a2e2dcd3b4bd4675694de'
MISDIRECTION,BETRAYAL=LEAVES=('EX1_533','LOOT_210')
PREFIX='cards.attack_redirect_secrets.'
COLLECTIBLE_ROOTS=()
PROFILES={MISDIRECTION:'other_character',BETRAYAL:'attacker_neighbor'}


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-attack-redirect-secrets-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            d['evidence_only'] or len(d['official_observations'])!=4 or
            any(d[k]for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])):
        raise TargetValidationError('Attack redirect Secrets lost complete source and finite policies')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Attack redirect Secrets lost the complete unfiltered reference')
    return d


def register_attack_redirect_secrets(registry):
    data=load_batch();prepared=[]
    def body(c,cid):
        window=pending_attack(c.state,c.event,c.player_id,PROFILES[cid])
        if window is None:return ()
        return (RandomRedirectAttack(window,SourceAllocationFact.capture(c.state,c.source),PROFILES[cid]),)
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Attack redirect Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Attack redirect root must be a real Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('attack_declared',),PREFIX+cid,PREFIX+cid),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,lambda c,cid=cid:pending_attack(c.state,c.event,c.player_id,PROFILES[cid]) is not None)
        registry.register_behavior(PREFIX+cid,lambda c,cid=cid:body(c,cid))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
