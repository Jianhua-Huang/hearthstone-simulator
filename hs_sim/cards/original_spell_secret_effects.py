"""Ice Trap and Oh My Yogg use original physical hand spell windows."""
import hashlib,json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.countered_spell_secrets import CounterReturnSpell,CounterReplaceSpell,pending_spell
from hs_sim.engine.model import CardDefinition,CardType,Keyword,SecretSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/original-spell-secret-effects-v1.json'
BATCH_HASH='d6b4480b486ab569d900578d54417d3016abfa5fb4a2ad4741c92f88af937d38'
ICE,YOGG=LEAVES=('AV_226','DMF_236')
PREFIX='cards.original_spell_secret_effects.'
COLLECTIBLE_ROOTS=()


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!='cn37-local-original-spell-secret-effects-v1' or
            tuple(d['collectible_leaf_ids'])!=LEAVES or tuple(x['record']['id']for x in d['dependencies'])!=LEAVES or
            tuple(x['record']['id']for x in d['evidence_only'])!=('AV_226e',) or len(d['official_observations'])!=4 or
            any(d[k]for k in ('cards','new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in (*d['dependencies'],*d['evidence_only']))):
        raise TargetValidationError('Original spell Secrets lost complete source and policy data')
    p=ROOT/d['reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['reference_sha256'] or not set(LEAVES)<=set(json.loads(p.read_text(encoding='utf8'))['candidate_ids']):
        raise TargetValidationError('Original spell Secrets lost their full unfiltered reference')
    return d


def register_original_spell_secret_effects(registry):
    data=load_batch();prepared=[]
    def condition(c):return pending_spell(c.state,c.event,c.player_id) is not None
    def body(c,cid):
        original=pending_spell(c.state,c.event,c.player_id)
        if original is None:return ()
        window,play,card=original;kind=CounterReturnSpell if cid==ICE else CounterReplaceSpell
        return (kind(window.id,play.id,SourceAllocationFact.capture(c.state,card),SourceAllocationFact.capture(c.state,c.source)),)
    for item in data['dependencies']:
        raw=item['record'];cid=raw['id']
        if cid in registry.cards or cid in registry.pool_cards:raise TargetValidationError('Original spell Secret already registered')
        if raw['type']!='SPELL' or raw['tags'].get('SECRET')!=1:raise TargetValidationError('Original spell root must be a real Secret')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,('card_committed',),PREFIX+cid,PREFIX+cid),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    for cid in LEAVES:
        registry.register_secret_condition(PREFIX+cid,condition)
        registry.register_behavior(PREFIX+cid,lambda c,cid=cid:body(c,cid))
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
