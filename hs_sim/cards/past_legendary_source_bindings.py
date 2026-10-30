"""Original legendary sources over existing generation, Infuse and pack kernels."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.card_packs import OpenStandardPack
from hs_sim.engine.model import CardType
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-source-bindings-v1.json'
BATCH_HASH='f7ad0e9acdeffab50e15937606fb432e31da1d11d774b974e175b7c76f6d84b7'
BRIGHT,SNEED,DENATHRIUS,AVATAR=ROOTS=('EX1_189','GVG_114','REV_906','WON_145')
INFUSED='REV_906t'
DEPENDENCIES=()
PREFIX='cards.past_legendary_sources.'


def semantic_pair(original,core):
    if original['id']not in ROOTS or core['id']!='CORE_'+original['id']:
        raise TargetValidationError('Original source requires its exact named Core printing')
    if any(original[k]!=core[k]for k in('name','name_en','text','text_en','cost','attack','health',
            'type','collectible','power_keyword_tags')):
        raise TargetValidationError('Original source changed complete printed semantics')
    changes={k for k in set(original['tags'])|set(core['tags'])if original['tags'].get(k)!=core['tags'].get(k)}
    if(not changes<={'CARD_SET','858','DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'}or
            core['tags'].get('858')!=original['dbf_id']or
            core['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID',original['dbf_id'])!=original['dbf_id']):
        raise TargetValidationError('Original source has an unreviewed gameplay-tag difference')


def make_definition(raw,counterpart):
    if(raw['id']not in ROOTS or counterpart.id!='CORE_'+raw['id']or
            raw['type']!='MINION'or counterpart.kind!=CardType.MINION or not raw['collectible']or
            raw['tags'].get('RARITY')!=5 or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Original source requires a complete actual Legendary minion')
    card=replace(counterpart,id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw))
    return replace(card,battlecry=PREFIX+'pack')if raw['id']==AVATAR else card


def infuse_profile(registry):
    return replace(registry.infused_battlecry_profiles['CORE_REV_906'],card_id=DENATHRIUS)


def pack_profile(registry):
    return replace(registry._standard_pack_profiles['CORE_WON_145'],source_card_id=AVATAR)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-legendary-source-bindings-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or
            [x['record']['id']for x in data['existing_dependencies']]!=['CORE_'+x for x in ROOTS]+[INFUSED,'TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701']or
            len(data['official_observations'])!=12 or
            any(data[k]for k in('new_counterpart_or_child_primary_faces_verified','complete_past_legendary_source_bound',
                'new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Original sources lost complete identities, roles or domain boundaries')
    for group in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Original source changed a complete raw row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Original source changed a complete retained dependency')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    records={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Original sources cropped the complete past inventory')
    for original,core in zip(data['cards'],data['existing_dependencies']):semantic_pair(original['record'],core['record'])
    faces=[x['face']for x in data['official_observations']if x['card_id']==DENATHRIUS]
    child=next(x['record']for x in data['existing_dependencies']if x['record']['id']==INFUSED)
    core=next(x['record']for x in data['existing_dependencies']if x['record']['id']=='CORE_REV_906')
    if len(faces)!=2 or any(child['dbf_id']not in f['childIds']or core['dbf_id']not in f['copyOfCardId']for f in faces):
        raise TargetValidationError('Original Denathrius lost its actual complete Core/child association')
    return data


def register_past_legendary_source_bindings(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Original source changed a complete existing dependency')
    for row in data['cards']:
        raw=row['record'];card=make_definition(raw,registry.card('CORE_'+raw['id']))
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Original source cannot replace or silently alter an existing face')
        registry._validate_card(card);prepared.append(card)
    profiles=data['existing_source_profiles']
    for cid,profile in profiles['infused_battlecry_profiles'].items():
        if canonical_digest(asdict(registry.infused_battlecry_profiles[cid]))!=canonical_digest(profile):
            raise TargetValidationError('Original source changed its complete existing Infuse declaration')
    for cid,profile in profiles['standard_pack_profiles'].items():
        if canonical_digest(asdict(registry._standard_pack_profiles[cid]))!=canonical_digest(profile):
            raise TargetValidationError('Original source changed its complete existing pack declaration')
    infusion,pack=infuse_profile(registry),pack_profile(registry)
    if(canonical_digest(asdict(infusion))!=canonical_digest(data['original_infuse_profile'])or
            canonical_digest(asdict(pack))!=canonical_digest(data['original_pack_profile'])):
        raise TargetValidationError('Original sources lost their independent exact native bindings')
    registry.register_behavior(PREFIX+'pack',lambda c:(OpenStandardPack(c.player_id,
        SourceAllocationFact.capture(c.state,c.source),AVATAR),))
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_infused_battlecry_profile(infusion)
    registry.register_standard_pack_profile(pack)
