"""Five ordinary Secret CASTs from the complete declared local past reference."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.secret_expirations import QUERY,SecretExpiryProfile
from hs_sim.engine.spell_history import CastFromPool
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/disco-past-secrets-v1.json'
BATCH_HASH='405fc26b32dd79923adf9ad4239e2f8149e594e3eefe77037dd2177288e7f1ce'
CARD='WON_040'
POOL='constructed.local-past-secrets.full-reference-v1'
POLICY='cn37-local-disco-full-past-secrets-v1'
BODY='cards.disco_past_secrets.WON_040'
METADATA_IDS=('EX1_130','EX1_287','EX1_289','EX1_294','EX1_610','EX1_611','MAW_006','tt_010')


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            d['source_card_id']!=CARD or d['pool_id']!=POOL or d['count']!=5 or d['weight']!=1 or
            d['complete_for_declared_inventory']is not True or len(d['official_observations'])!=2 or
            any(d[k]for k in('formal_pool_complete','cn_calibrated','membership_uses_executable_coverage','new_standard_roots'))):
        raise TargetValidationError('Disco requires its complete original local Secret source and explicit limits')
    refpath=ROOT/d['reference_document'];ref=json.loads(refpath.read_text(encoding='utf8'))
    if (hashlib.sha256(refpath.read_bytes()).hexdigest()!=d['reference_sha256'] or d['member_ids']!=ref['candidate_ids'] or
            len(d['member_ids'])!=72 or len(set(d['member_ids']))!=72 or d['source_record']!=ref['source_producer'] or
            d['evidence_only']!=ref['evidence_only'] or tuple(v['card_id']for v in d['native_pins'])!=tuple(d['member_ids'])or
            tuple(d['metadata_ids'])!=METADATA_IDS or canonical_digest(d['query'])!=canonical_digest(asdict(QUERY))):
        raise TargetValidationError('Disco lost an original candidate, source face, role, weight or query')
    return d,ref


def validate_native(registry,d):
    for row in d['native_pins']:
        cid=row['card_id']
        if canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']:
            raise TargetValidationError('Disco original Secret definition changed: '+cid)
        if cid in registry.pool_cards and canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']:
            raise TargetValidationError('Disco original Secret generation metadata changed: '+cid)


def register_disco_past_secrets(registry):
    d,ref=load_batch();validate_native(registry,d);raw=d['source_record']['record'];prepared=[]
    rows={v['record']['id']:v['record']for v in ref['candidate_records']}
    for cid in METADATA_IDS:
        card=registry.card(cid);printed=PoolCard.from_definition(card)
        if metadata_from_record(rows[cid])!=card.metadata or canonical_digest(asdict(printed))!=next(v['pool_card_sha256']for v in d['native_pins']if v['card_id']==cid):
            raise TargetValidationError('Disco missing metadata disagrees with the complete original definition: '+cid)
        if cid not in registry.pool_cards:prepared.append(printed)
    if CARD in registry.cards or raw['type']!='SPELL' or raw['cost']!=6:
        raise TargetValidationError('Disco requires its actual new six-mana spell')
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=BODY,metadata=metadata_from_record(raw))
    if canonical_digest(asdict(card))!=d['source_definition_sha256']:raise TargetValidationError('Disco producer definition changed')
    registry._validate_card(card)
    registry.register_behavior(BODY,lambda c:(CastFromPool(c.player_id,POOL,QUERY,5,c.source_id),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for printed in prepared:registry.register_pool_card(printed)
    registry.register_secret_expiry_profile(SecretExpiryProfile(CARD,POOL,tuple(d['member_ids'])))


def local_pool(registry,context):
    d,_=load_batch();validate_native(registry,d)
    if canonical_digest(asdict(registry.card(CARD)))!=d['source_definition_sha256']:
        raise TargetValidationError('Disco bound pool lost its actual original producer')
    if any(cid not in registry.pool_cards for cid in d['member_ids']):
        raise TargetValidationError('Disco cannot crop missing original Secret metadata')
    return PoolDefinition(POOL,POLICY,context.target_id,context.mode,tuple(PoolMember(cid,d['weight'])for cid in d['member_ids']),complete=True)


def register_scope(registry,context):
    d,_=load_batch();pool=registry.pool(POOL,context)
    expected=local_pool(registry,context)
    if pool.members!=expected.members or pool.excluded_card_ids or not pool.complete:
        raise TargetValidationError('Disco changed its complete original Secret inventory or weights')
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,POOL,context.target_id,context.mode,CARD,None,QUERY,pool_digest(pool)))
    actual=resolve_candidates(registry,context,POOL,QUERY,source_card_id=CARD,exclude_source_by_rule=True)
    expected_ids=sorted(d['member_ids'],key=lambda cid:registry.pool_card(cid).generation_identity)
    if [v.card_id for v in actual]!=expected_ids or any(v.weight!=d['weight']for v in actual):
        raise TargetValidationError('Disco actual candidates differ from the full unfiltered original reference')
