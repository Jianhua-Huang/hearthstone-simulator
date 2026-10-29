"""Complete local past Mage/Arcane inventories over ordinary generation."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,SpellSchool
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolDefinition,PoolMember,PoolQuery,resolve_candidates
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .simple_followup_p89_cards import ALTER,ARCANE_PAST_POOL,QUERIES

ROOT=Path(__file__).resolve().parents[2]
CARD='NX2_001'
MAGE_POOL='constructed.past.mage.spells'
BODY='cards.past_mage_arcane_sources.tear'
POLICY='cn37-local-complete-past-mage-arcane-sources-v1'
BATCH_PATH=ROOT/'data/cards/past-mage-arcane-sources-v1.json'
BATCH_HASH='0664f70d7b2230e8dc1fb3af00514ce5d66f95c5caca4892a1fc213176f51aed'
MAGE_QUERY=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.MAGE,),include_neutral=False)
SOURCE_QUERIES={CARD:MAGE_QUERY,ALTER:QUERIES[ALTER]}


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            [v['record']['id']for v in d['cards']]!=[CARD]or
            [v['record']['id']for v in d['existing_dependencies']]!=['REV_601','RLK_843']or
            len(d['official_observations'])!=6 or d['metadata_ids']!=['REV_601','RLK_843']or
            any(d[k]for k in('dependencies','evidence_only','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in d['cards']+d['existing_dependencies'])):
        raise TargetValidationError('Past spell sources require complete original rows, primary faces and explicit local scope')
    if [(v['source_card_id'],v['pool_id'],len(v['member_ids']))for v in d['domains']]!=[(CARD,MAGE_POOL,179),(ALTER,ARCANE_PAST_POOL,84)]:
        raise TargetValidationError('Past spell sources lost an original domain or source role')
    union=[]
    for domain in d['domains']:
        p=ROOT/domain['reference_document'];ref=json.loads(p.read_text(encoding='utf8'))
        if (hashlib.sha256(p.read_bytes()).hexdigest()!=domain['reference_sha256']or
                domain['member_ids']!=ref['candidate_ids']or len(set(domain['member_ids']))!=len(domain['member_ids'])or
                domain['original_reference_pool_id']!=ref['pool_id']or domain['source_card_id']!=ref['source_card_id']or
                canonical_digest(domain['query'])!=canonical_digest(asdict(SOURCE_QUERIES[domain['source_card_id']]))or
                domain['weight']!=1 or domain['complete_for_declared_inventory']is not True or domain['formal_pool_complete']is not False):
            raise TargetValidationError('Past spell source changed original full identities, order, query or weights')
        classes=[v['current_class']for v in domain['views']]
        if classes!=([None]if domain['source_card_id']==CARD else list(ref['class_metadata_views'])):
            raise TargetValidationError('Past Arcane source must preserve every playable class view, including empty views')
        union.extend(cid for cid in domain['member_ids']if cid not in union)
    if [v['card_id']for v in d['native_pins']]!=union:
        raise TargetValidationError('Past spell source lost a full original executable or metadata pin')
    return d


def missing_metadata(registry):
    d=load_batch();prepared=[];pins={v['card_id']:v for v in d['native_pins']}
    for row in d['existing_dependencies']:
        raw=row['record'];cid=raw['id'];card=registry.card(cid);printed=PoolCard.from_definition(card)
        if (metadata_from_record(raw)!=card.metadata or canonical_digest(asdict(card))!=pins[cid]['definition_sha256']or
                canonical_digest(asdict(printed))!=pins[cid]['pool_card_sha256']or
                cid in registry.pool_cards and registry.pool_card(cid)!=printed):
            raise TargetValidationError('Past spell metadata disagrees with its complete unchanged native definition: '+cid)
        if cid not in registry.pool_cards:prepared.append(printed)
    return tuple(prepared)


def register_tear_reality(registry):
    d=load_batch();raw=d['cards'][0]['record']
    card=CardDefinition(CARD,raw['name'],CardType.SPELL,cost=4,spell_school=SpellSchool.ARCANE,on_play=BODY,metadata=metadata_from_record(raw))
    if CARD in registry.cards or canonical_digest(asdict(card))!=d['source_definition_sha256']:
        raise TargetValidationError('Tear Reality requires its complete original four-mana Arcane source')
    registry.register_behavior(BODY,lambda c:(GenerateFromPool(c.player_id,MAGE_POOL,MAGE_QUERY,
        count=2,replacement=True,source_id=c.source_id,cost=CostSpec(delta=-2)),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))


def register_past_mage_arcane_sources(registry):
    prepared=missing_metadata(registry)
    register_tear_reality(registry)
    for row in prepared:registry.register_pool_card(row)


def validate_native(registry,d):
    if canonical_digest(asdict(registry.card(ALTER)))!=d['arcane_source_definition_sha256']:
        raise TargetValidationError('Past Arcane binding changed its original native source definition')
    for row in d['native_pins']:
        cid=row['card_id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Past spell source lost original complete native material: '+cid)


def local_pools(registry,context):
    d=load_batch();validate_native(registry,d)
    return tuple(PoolDefinition(v['pool_id'],POLICY+':'+v['source_card_id'],context.target_id,context.mode,
        tuple(PoolMember(cid,v['weight'])for cid in v['member_ids']),complete=True)for v in d['domains'])


def register_scopes(registry,context):
    d=load_batch();validate_native(registry,d)
    for domain,expected_pool in zip(d['domains'],local_pools(registry,context)):
        pool=registry.pool(domain['pool_id'],context);source=domain['source_card_id'];query=SOURCE_QUERIES[source]
        if pool.members!=expected_pool.members or pool.excluded_card_ids or not pool.complete:
            raise TargetValidationError('Past spell source cannot crop or reweight an original inventory')
        for view in domain['views']:
            cl=None if view['current_class']is None else CardClass(view['current_class'])
            role=view['current_class']or'fixed-mage'
            registry.register_generation_scope(GenerationScope(POLICY+':'+source+':'+role+':'+context.target_id,
                pool.id,context.target_id,context.mode,source,cl,query,pool_digest(pool)))
            actual=resolve_candidates(registry,context,pool.id,query,current_class=cl,source_card_id=source,exclude_source_by_rule=True)
            if [v.card_id for v in actual]!=view['actual_ids']or [v.weight for v in actual]!=view['actual_weights']:
                raise TargetValidationError('Actual past spell candidates differ from their independently reviewed original policy view')
