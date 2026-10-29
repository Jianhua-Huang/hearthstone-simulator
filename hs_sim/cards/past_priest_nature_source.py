"""Whirlpool and complete Priest/independently empty past Nature views."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.minion_copy_destruction import DestroyMinionCopies
from hs_sim.engine.model import CardClass,CardDefinition,CardType,SpellSchool
from hs_sim.engine.pools import PoolCard,PoolMember,resolve_candidates
from hs_sim.targets import TargetValidationError,canonical_digest
from . import past_druid_nature_source as druid
from .metadata import metadata_from_record
from .simple_followup_p89_cards import WO,NATURE_PAST_POOL,QUERIES

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-priest-nature-source-v1.json'
BATCH_HASH='f9aec4e68851cb1b6923f83a9c5a632e22952989d9bd74589a61e288d6badd1a'
POLICY='cn37-local-priest-past-nature-and-empty-views-v1'
CARD='TSC_209'
BODY='cards.past_priest_nature_source.whirlpool'
EMPTY_CLASSES=('death_knight','demon_hunter','mage','paladin','warlock')


def make_definition(raw):
    return CardDefinition(CARD,raw['name'],CardType.SPELL,cost=8,on_play=BODY,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw))


def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            [v['record']['id']for v in d['cards']]!=[CARD]or
            [v['record']['id']for v in d['existing_dependencies']]!=['DEEP_026',WO]or
            len(d['official_observations'])!=6 or d['source_card_id']!=WO or d['pool_id']!=NATURE_PAST_POOL or
            d['original_member_ids']!=druid.load_batch()['member_ids']or
            d['merged_member_ids']!=d['original_member_ids']+[CARD]or
            len(d['full_union_candidate_ids'])!=174 or
            [v['card_id']for v in d['native_pins']]!=d['merged_member_ids']or
            d['empty_classes']!=list(EMPTY_CLASSES)or
            canonical_digest(d['query'])!=canonical_digest(asdict(QUERIES[WO]))or
            any(d[k]for k in('new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Priest Nature requires its complete fixed original and extended views')
    if hashlib.sha256((ROOT/d['original_druid_source_document']).read_bytes()).hexdigest()!=d['original_druid_source_sha256']:
        raise TargetValidationError('Priest Nature lost the full unchanged Druid predecessor')
    for row in d['cards']+d['existing_dependencies']+d['full_union_records']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Priest Nature lost a complete original raw identity')
    if [v['record']['id']for v in d['full_union_records']]!=d['full_union_candidate_ids']:
        raise TargetValidationError('Priest Nature changed its independently reviewed full reference order')
    views={v['current_class']:v['actual_ids']for v in d['views']}
    if views!={'priest':['DEEP_026',CARD],**{cl:[]for cl in EMPTY_CLASSES}}:
        raise TargetValidationError('Priest Nature cannot infer or crop an unreviewed class view')
    for cl,ids in views.items():
        derived=[v['record']['id']for v in d['full_union_records']if
            CardClass(cl)in metadata_from_record(v['record']).classes or
            CardClass.NEUTRAL in metadata_from_record(v['record']).classes]
        if derived!=ids:raise TargetValidationError('Priest Nature view differs from the full fixed reference')
    return d


def register_past_priest_nature_card(registry):
    d=load_batch();row=d['cards'][0];card=make_definition(row['record'])
    if CARD in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
        raise TargetValidationError('Whirlpool cannot replace a native card or lose its full real face')
    printed=PoolCard.from_definition(card)
    if CARD in registry.pool_cards and registry.pool_card(CARD)!=printed:
        raise TargetValidationError('Whirlpool cannot change an existing full metadata row')
    registry.register_behavior(BODY,lambda c:(DestroyMinionCopies(c.source_id),))
    registry.register_card(card)
    if CARD not in registry.pool_cards:registry.register_pool_card(printed)


def checked_native(registry,d):
    for row in d['native_pins']:
        cid=row['card_id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Priest Nature lost complete native material: '+cid)
    for row in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(row['record']['id'])))!=row['definition_sha256']:
            raise TargetValidationError('Priest Nature changed an existing full source/dependency')


def local_pool(registry,context):
    d=load_batch();checked_native(registry,d);original=druid.local_pool(registry,context)
    return replace(original,version=POLICY+':'+original.version,
        members=tuple(PoolMember(cid)for cid in d['merged_member_ids']))


def register_scopes(registry,context,*,reviewed_pool=None):
    d=load_batch();expected=local_pool(registry,context);pool=registry.pool(NATURE_PAST_POOL,context)
    if reviewed_pool is not None:
        if (type(reviewed_pool)is not type(expected)or reviewed_pool.id!=expected.id or
                reviewed_pool.target_id!=context.target_id or reviewed_pool.mode!=context.mode or
                not reviewed_pool.complete or reviewed_pool.excluded_card_ids or
                reviewed_pool.members[:len(expected.members)]!=expected.members or
                not reviewed_pool.version.endswith(':'+expected.version)or
                len({m.card_id for m in reviewed_pool.members})!=len(reviewed_pool.members)):
            raise TargetValidationError('Priest Nature extension must retain its complete original prefix and source roles')
        expected=reviewed_pool
    if pool!=replace(expected,version=context.target_id+':'+expected.version):
        raise TargetValidationError('Priest Nature cannot borrow or crop a rebound original inventory')
    for view in d['views']:
        cl=CardClass(view['current_class'])
        registry.register_generation_scope(GenerationScope(POLICY+':'+WO+':'+cl.value+':'+context.target_id,
            pool.id,context.target_id,context.mode,WO,cl,QUERIES[WO],pool_digest(pool)))
        actual=resolve_candidates(registry,context,pool.id,QUERIES[WO],current_class=cl,
            source_card_id=WO,exclude_source_by_rule=True)
        if [v.card_id for v in actual]!=view['actual_ids']or [v.weight for v in actual]!=[1]*len(actual):
            raise TargetValidationError('Priest Nature actual candidates differ from the complete declared class view')
