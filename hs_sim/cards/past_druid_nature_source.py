"""One complete fixed past Nature view; other classes remain unbound."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardClass,CardType,SpellSchool
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-druid-nature-source-v1.json'
BATCH_HASH='560887a09a6ca04f19a590682dd42511c958ae99650d6d0ba84bdbe9546e0ab2'
POLICY='cn37-local-druid-past-nature-source-v1'
METADATA_IDS=('CS2_009','EX1_154','EX1_158','EX1_169','WW_823')


def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            (d['source_card_id'],d['pool_id'],d['current_class'])!=(WO,NATURE_PAST_POOL,'druid')or
            d['member_weight']!=1 or d['member_role']!='past_collectible_Druid_Nature_spell'or
            len(d['member_ids'])!=85 or len(set(d['member_ids']))!=85 or
            d['metadata_ids']!=list(METADATA_IDS)or
            canonical_digest(d['query'])!=canonical_digest(asdict(QUERIES[WO]))or
            d['full_declared_query_inventory']is not True or
            any(d[k]for k in('membership_uses_executable_coverage','new_standard_roots','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Druid Nature requires its complete fixed source and explicit local view')
    for path_key,pin_key in(('original_inventory_document','original_inventory_document_sha256'),
            ('set_policy_reference_document','set_policy_reference_document_sha256')):
        if hashlib.sha256((ROOT/d[path_key]).read_bytes()).hexdigest()!=d[pin_key]:
            raise TargetValidationError('Druid Nature lost a complete unchanged reference document')
    original=json.loads((ROOT/d['original_inventory_document']).read_text('utf-8'))
    if (original['complete_druid_Nature_inventory']!=d['member_ids']or
            [v['card_id']for v in d['native_pins']]!=d['member_ids']or
            [v['record']['id']for v in d['member_records']]!=d['member_ids']or
            [v['record']['id']for v in d['cards']]!=[WO]or len(d['official_observations'])!=16 or
            [v['record']['id']for v in d['existing_dependencies']]!=
                ['CS2_009','EX1_154','EX1_158','EX1_158t','EX1_169','WW_823','CS2_007','EX1_164']):
        raise TargetValidationError('Druid Nature changed original identities, roles or order')
    for row in d['cards']+d['existing_dependencies']+d['member_records']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Druid Nature lost a complete fixed raw record')
    return d


def checked_metadata(registry,d,*,allow_missing=False):
    if canonical_digest(asdict(registry.card(WO)))!=d['source_definition_sha256']:
        raise TargetValidationError('Druid Nature changed its original native source')
    for row in d['cards']+d['existing_dependencies']:
        c=registry.card(row['record']['id'])
        if metadata_from_record(row['record'])!=c.metadata or canonical_digest(asdict(c))!=row['definition_sha256']:
            raise TargetValidationError('Druid Nature source/dependency changed its complete original face')
    prepared=[]
    for row,raw in zip(d['native_pins'],d['member_records']):
        cid=row['card_id'];c=registry.card(cid);printed=PoolCard.from_definition(c)
        if (canonical_digest(asdict(c))!=row['definition_sha256']or
                canonical_digest(asdict(printed))!=row['pool_card_sha256']or
                metadata_from_record(raw['record'])!=c.metadata or c.kind!=CardType.SPELL or
                c.spell_school!=SpellSchool.NATURE or not c.metadata.collectible or
                CardClass.DRUID not in c.metadata.classes):
            raise TargetValidationError('Druid Nature lost a full qualified native member: '+cid)
        if cid in registry.pool_cards:
            if registry.pool_card(cid)!=printed:raise TargetValidationError('Druid Nature metadata changed: '+cid)
        elif allow_missing and cid in METADATA_IDS:prepared.append(printed)
        else:raise TargetValidationError('Druid Nature has an unimplemented metadata member: '+cid)
    return tuple(prepared)


def register_past_druid_nature_metadata(registry):
    prepared=checked_metadata(registry,load_batch(),allow_missing=True)
    for row in prepared:registry.register_pool_card(row)


def local_pool(registry,context):
    d=load_batch();checked_metadata(registry,d)
    return PoolDefinition(NATURE_PAST_POOL,POLICY,context.target_id,context.mode,
        tuple(PoolMember(cid,d['member_weight'])for cid in d['member_ids']),complete=True)


def register_scope(registry,context,*,reviewed_pool=None):
    d=load_batch();expected=local_pool(registry,context);pool=registry.pool(NATURE_PAST_POOL,context)
    if reviewed_pool is not None:
        if (type(reviewed_pool)is not PoolDefinition or reviewed_pool.id!=expected.id or
                reviewed_pool.target_id!=context.target_id or reviewed_pool.mode!=context.mode or
                not reviewed_pool.complete or reviewed_pool.excluded_card_ids or
                reviewed_pool.members[:len(expected.members)]!=expected.members or
                not reviewed_pool.version.endswith(':'+POLICY)or
                len({m.card_id for m in reviewed_pool.members})!=len(reviewed_pool.members)):
            raise TargetValidationError('Druid Nature extension must retain its complete original prefix and source role')
        expected=reviewed_pool
    expected=replace(expected,version=context.target_id+':'+expected.version)
    if asdict(pool)!=asdict(expected):
        raise TargetValidationError('Druid Nature cannot crop, replace, reweight or borrow an inventory')
    registry.register_generation_scope(GenerationScope(POLICY+':'+WO+':druid:'+context.target_id,
        pool.id,context.target_id,context.mode,WO,CardClass.DRUID,QUERIES[WO],pool_digest(pool)))
    actual=resolve_candidates(registry,context,pool.id,QUERIES[WO],current_class=CardClass.DRUID,
        source_card_id=WO,exclude_source_by_rule=True)
    if [v.card_id for v in actual]!=d['member_ids']or [v.weight for v in actual]!=[1]*85:
        raise TargetValidationError('Druid Nature actual candidates lost the original ordered local policy')
