"""Full one-cost reference inventory and the real Disciple Invoke request."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.invoke import GalakrondFamily,Invoke,InvokeProfile
from hs_sim.engine.model import CardClass,CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_past_entry_grant_cards import QUERY

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/one-cost-past-pool-v1.json'
BATCH_HASH='6bed2969d67f913b187329b21c893687ebb512053ee922bec1f446d6b0cc1428'
CARD='DRG_303';SOURCE='TIME_711';BODY='cards.galakrond_disciple.invoke'
POOL_ID='constructed.past.one_cost_minions'
POLICY='cn37-local-flashback-one-cost-inventory-v1'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or data['policy_id']!=POLICY or
            data['pool_id']!=POOL_ID or data['source_card_id']!=SOURCE or
            tuple(r['record']['id']for r in data['cards'])!=(CARD,) or
            data['dependencies']or data['skipped']or len(data['existing_dependencies'])!=282 or
            len(data['evidence_only'])!=20 or len(data['official_faces'])!=4 or
            data['formal_pool_complete']is not False or data['cn_calibrated']is not False):
        raise TargetValidationError('One-cost past scope requires its complete pinned native source and inventory')
    for key in ('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(r['record'])!=r['record_sha256']for r in data[key]):
            raise TargetValidationError('One-cost past scope lost a complete original record')
    if (data['candidate_ids']!=data['candidate_reference']['reference']['complete_candidate_ids'] or
            len(data['candidate_ids'])!=282 or len(set(data['candidate_ids']))!=282):
        raise TargetValidationError('One-cost past candidate identities were cropped or duplicated')
    return data


def native_profile():
    data=load_batch();evidence={r['record']['id']:r['record']for r in data['evidence_only']}
    for family in data['galakrond_families']:
        hero_class=CardClass(family['hero_class']);power=evidence[family['power_card_id']]
        if metadata_from_record(power).classes!=(hero_class,):raise TargetValidationError('Galakrond power has another declared class')
        for cid in family['forms']:
            raw=evidence[cid]
            if (raw['type']!='HERO' or metadata_from_record(raw).classes!=(hero_class,) or
                    raw['tags']['HERO_POWER']!=power['dbf_id']):
                raise TargetValidationError('Galakrond declaration changed original class, family or power')
    return InvokeProfile(data['invoke_profile_version'],tuple(GalakrondFamily(CardClass(f['hero_class']),
        tuple(f['forms']),f['gift_behavior'])for f in data['galakrond_families']))


def register_one_cost_past_card(registry):
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags']['CLASS'],raw['tags']['BATTLECRY'])!=('MINION',1,1,2,6,1):
        raise TargetValidationError('Disciple requires its original 1-mana 1/2 Priest Invoke Battlecry')
    # A host may already provide an explicit complete Invoke profile. The normal
    # constructed host has none; install real family declarations, never stubs.
    if registry.invoke_profile is None:registry.register_invoke_profile(native_profile())
    registry.register_behavior(BODY,lambda c:(Invoke(c.player_id,c.source_id),))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=1,attack=1,health=2,battlecry=BODY,
        keywords=(Keyword.INVOKE,),metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))


def local_pool(registry,context):
    data=load_batch();existing={r['record']['id']:r for r in data['existing_dependencies']}
    for cid in data['candidate_ids']:
        card=registry.card(cid)
        if cid!=CARD and canonical_digest(asdict(card))!=existing[cid]['definition_sha256']:
            raise TargetValidationError('One-cost past member definition changed: '+cid)
        if card.kind!=CardType.MINION or card.cost!=1 or card.metadata.collectible is not True:
            raise TargetValidationError('One-cost past member lost its actual printed role: '+cid)
        raw=data['cards'][0]['record']if cid==CARD else existing[cid]['record']
        if card.metadata!=metadata_from_record(raw):
            raise TargetValidationError('One-cost past metadata differs from the independent fixed record: '+cid)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    return PoolDefinition(POOL_ID,POLICY,context.target_id,context.mode,
        tuple(PoolMember(cid,1)for cid in data['candidate_ids']),complete=True)


def register_scope(registry,context):
    pool=registry.pool(POOL_ID,context)
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,POOL_ID,context.target_id,
        context.mode,SOURCE,None,QUERY,pool_digest(pool)))
