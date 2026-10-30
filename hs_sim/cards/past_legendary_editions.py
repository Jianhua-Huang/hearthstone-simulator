"""Original physical editions sharing already reviewed real native effects."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path

from hs_sim.engine.model import CardType
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-legendary-editions-v1.json'
BATCH_HASH='8c2879ca555b232d883286ff68501a5be191ca26214875bd8c611e3d2c710987'
ROOTS=('CFM_670','CFM_781','DAL_575','DRG_256','EX1_198','MAW_034','NEW1_010',
    'RLK_706','SCH_181','SCH_717','SW_047','TRL_345','TRL_900','ULD_178')
DEPENDENCIES=()
PREFIX='cards.past_legendary_editions.'
MOGRAINE='RLK_706'
PROGRAM=PREFIX+'mograine'
EXISTING_PROGRAM='cards.player_period.mograine'


def semantic_pair(original,core):
    if original['id']not in ROOTS or core['id']!='CORE_'+original['id']:
        raise TargetValidationError('Original edition requires its explicit named counterpart')
    for key in('name','name_en','text','text_en','cost','attack','health','type','collectible','power_keyword_tags'):
        if original[key]!=core[key]:
            raise TargetValidationError('Original edition changed actual printed semantics: '+key)
    differences={key for key in set(original['tags'])|set(core['tags'])
        if original['tags'].get(key)!=core['tags'].get(key)}
    if(not differences<={'CARD_SET','858','DECK_RULE_COUNT_AS_COPY_OF_CARD_ID'}or
            core['tags'].get('858')!=original['dbf_id']or
            core['tags'].get('DECK_RULE_COUNT_AS_COPY_OF_CARD_ID',original['dbf_id'])!=original['dbf_id']):
        raise TargetValidationError('Original edition has an unreviewed gameplay tag difference')


def make_definition(raw,counterpart):
    if(raw['id']not in ROOTS or counterpart.id!='CORE_'+raw['id']or
            raw['type']!='MINION'or not raw['collectible']or raw['tags'].get('RARITY')!=5 or
            counterpart.kind!=CardType.MINION or any(type(raw[k])is not int for k in('cost','attack','health'))):
        raise TargetValidationError('Original edition requires its complete actual Legendary minion face')
    card=replace(counterpart,id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],
        health=raw['health'],metadata=metadata_from_record(raw))
    return replace(card,battlecry=PREFIX+'mograine')if raw['id']==MOGRAINE else card


def mograine_program(registry):
    return replace(registry.player_effect(EXISTING_PROGRAM),id=PROGRAM,card_id=MOGRAINE)


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(data)!=BATCH_HASH or data['schema']!=1 or
            data['policy_id']!='cn37-local-past-legendary-editions-v1'or
            tuple(x['record']['id']for x in data['cards'])!=ROOTS or data['dependencies']or
            [x['record']['id']for x in data['existing_dependencies']]!=['CORE_'+cid for cid in ROOTS]+['TRL_348t','TIME_013']or
            [x['record']['id']for x in data['evidence_only']]!=['MIS_701']or
            len(data['official_observations'])!=32 or
            any(data[k]for k in('new_counterpart_primary_faces_verified','complete_past_legendary_source_bound',
                'new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Original editions lost complete identities, roles or source boundaries')
    for group in('cards','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in data[group]):
            raise TargetValidationError('Original edition changed a complete pinned source row')
    for item in data['retained_documents'].values():
        path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Original edition changed a retained complete reference')
    full=json.loads((ROOT/data['full_reference_document']).read_text(encoding='utf8'))
    records={x['record']['id']:x['record']for x in full['candidate_records']}
    if(len(full['candidate_ids'])!=732 or data['original_candidate_ids']!=full['candidate_ids']or
            any(x['record']!=records[x['record']['id']]for x in data['cards'])):
        raise TargetValidationError('Original editions cropped the original complete past domain')
    for row,core in zip(data['cards'],data['existing_dependencies']):semantic_pair(row['record'],core['record'])
    return data


def register_past_legendary_editions(registry):
    data=load_batch();prepared=[]
    for row in data['existing_dependencies']:
        cid=row['record']['id'];card=registry.card(cid)
        if canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Original edition changed an existing complete dependency')
        if canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']:
            raise TargetValidationError('Original edition changed an existing complete pool metadata face')
    for row in data['cards']:
        raw=row['record'];card=make_definition(raw,registry.card('CORE_'+raw['id']))
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Original edition cannot replace or silently alter a physical face')
        registry._validate_card(card);prepared.append(card)
    program=mograine_program(registry)
    if(canonical_digest(asdict(registry.player_effect(EXISTING_PROGRAM)))!=canonical_digest(data['existing_mograine_program'])or
            canonical_digest(asdict(program))!=canonical_digest(data['original_mograine_program'])):
        raise TargetValidationError('Original Mograine lost its complete separate source program')
    registry.register_behavior(PREFIX+'mograine',lambda c:(
        AddPlayerEffect(c.player_id,PROGRAM,c.source_id,capture_health_source=True),))
    registry.register_player_effect(program)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_random_target_card('CFM_670')
