"""An opt-in CN37 host with reviewed, source-bound special pool inventories.

The original launch factory remains reproducible. This factory retains its
ordinary inventories and deck policy, but gives all installed local pools one
new target. Inventory completeness is local; formal CN certification is false.
"""
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from .engine.pools import GenerationContext
from .launch_candidate_format import build_cn37_launch_candidate_format
from .targets import TargetValidationError, canonical_digest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'data/cards/local-special-pool-bindings-v16.json'
MANIFEST_HASH = '60db9965fe4c5e9757546c66995b2c4c385d27a19ca794495c7b1b9a086fd4cc'
FORMAT_VERSION = 'cn37-local-special-pools-v16'
ORDINARY_POOLS = ('constructed.cards', 'constructed.minions')


def load_bindings():
    value = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    from .cards.past_druid_nature_source import BATCH_PATH as NATURE_PATH,load_batch as load_nature
    nature=load_nature()
    if value['druid_nature_binding']!=dict(source_document=NATURE_PATH.relative_to(ROOT).as_posix(),
            source_document_canonical_sha256=canonical_digest(nature),source_card_id='TIME_013',
            pool_id=nature['pool_id'],current_class='druid',member_count=85,
            complete_for_declared_inventory=True,formal_pool_complete=False):
        raise TargetValidationError('Druid Nature source document changed')
    if (canonical_digest(value) != MANIFEST_HASH or value['schema'] != 1 or
            value['formal_pool_complete'] is not False or not value['bindings']):
        raise TargetValidationError('Local special pools require their reviewed complete manifest')
    names = [item['pool_id'] for item in value['bindings']]
    if (len(names) != len(set(names)) or set(names) & set(ORDINARY_POOLS) or
            set(names) & set(value['unresolved_pool_ids'])):
        raise TargetValidationError('Local special pool bindings overlap or replace an unresolved inventory')
    scoped=[p for item in value['scoped_bindings']for p in item['pool_ids']]
    if (len(scoped)!=len(set(scoped)) or set(scoped)!=set(value['scoped_pool_ids']) or
            not set(value['partially_scoped_pool_ids'])<=set(scoped) or
            set(scoped)&(set(names)|set(ORDINARY_POOLS)|set(value['unresolved_pool_ids']))):
        raise TargetValidationError('Scoped past views overlap an existing or unresolved pool domain')
    pack = value['pack_binding']
    if (pack['pool_id'] != 'constructed.standard_pack' or
            pack['pool_id'] in set(names) | set(scoped) | set(ORDINARY_POOLS) | set(value['unresolved_pool_ids']) or
            pack['complete_for_declared_inventory'] is not True or pack['formal_pool_complete'] is not False):
        raise TargetValidationError('Local pack inventory overlaps another domain or claims official completeness')
    rajh = value['rajh_binding']
    if (rajh['pool_id'] != 'constructed.assemble.rajh' or
            rajh['pool_id'] in set(names) | set(scoped) | set(ORDINARY_POOLS) | set(value['unresolved_pool_ids']) | {pack['pool_id']} or
            value['partial_inventory_pool_ids'] != [rajh['pool_id']] or
            (rajh['reported_total'], rajh['known_member_count'], rajh['missing_member_count']) != (15, 14, 1) or
            rajh['complete_for_declared_inventory'] is not True or rajh['formal_pool_complete'] is not False):
        raise TargetValidationError('Rajh known inventory lost its separate domain or explicitly missing member')
    zombeast = value['zombeast_binding']
    if (zombeast['pool_ids'] != ['crafted.zombeast.first', 'crafted.zombeast.second'] or
            set(zombeast['pool_ids']) & (set(names) | set(scoped) | set(ORDINARY_POOLS) |
                set(value['unresolved_pool_ids']) | {pack['pool_id'], rajh['pool_id']}) or
            zombeast['member_counts'] != [34, 38] or zombeast['eligible_counts'] != [34, 37] or
            zombeast['complete_for_declared_inventory'] is not True or zombeast['formal_pool_complete'] is not False):
        raise TargetValidationError('Zombeast local roles lost their independent inventories or explicit exclusion')
    previous = value['previous_manifest']
    if previous['path'] != 'data/cards/local-special-pool-bindings-v15.json':
        raise TargetValidationError('Local source host requires its original complete predecessor manifest')
    prior = json.loads((ROOT/previous['path']).read_text(encoding='utf8'))
    if (canonical_digest(prior) != previous['canonical_sha256'] or any(
            value.get(k) != v for k,v in prior.items() if k not in ('policy_id','accepted_on','previous_manifest'))):
        raise TargetValidationError('Local source host changed an existing special-pool declaration')
    cata = value['cata_colossal_binding']
    if (cata['source_document'] != 'data/cards/past-colossal-source-binding-v1.json' or
            cata['pool_id'] != 'constructed.past.cards' or cata['pool_id'] not in value['partially_scoped_pool_ids'] or
            cata['source_card_id'] != 'CATA_EVENT_000' or (cata['member_count'],cata['merged_member_count']) != (13,46) or
            cata['complete_for_declared_source_view'] is not True or cata['formal_pool_complete'] is not False or
            canonical_digest(json.loads((ROOT/cata['source_document']).read_text(encoding='utf8'))) != cata['source_document_canonical_sha256']):
        raise TargetValidationError('CATA host lost its complete declared Colossal source projection')
    mech = value['paladin_mech_binding']
    if (mech['source_document'] != 'data/cards/past-paladin-mech-source-binding-v1.json' or
            mech['pool_id'] != 'constructed.past.cards' or mech['pool_id'] not in value['partially_scoped_pool_ids'] or
            mech['source_card_id'] != 'TIME_016' or
            (mech['member_count'],mech['prior_merged_member_count'],mech['merged_member_count']) != (27,46,72) or
            mech['complete_for_declared_source_view'] is not True or mech['formal_pool_complete'] is not False or
            canonical_digest(json.loads((ROOT/mech['source_document']).read_text(encoding='utf8'))) != mech['source_document_canonical_sha256'] or
            mech['faction_qualification_policy_id'] != 'cn37-local-paladin-past-mechs-full-reference-v1'):
        raise TargetValidationError('Past Mech host lost its complete original source or explicit faction policy')
    from .cards.disco_past_secrets import BATCH_PATH as DISCO_PATH,load_batch as load_disco
    disco=value['disco_secret_binding'];data,_=load_disco()
    if (disco['source_document']!=DISCO_PATH.relative_to(ROOT).as_posix() or
            disco['source_document_canonical_sha256']!=canonical_digest(data) or
            (disco['source_card_id'],disco['pool_id'],disco['member_count'])!=('WON_040',data['pool_id'],72) or
            disco['member_ids']!=data['member_ids'] or disco['complete_for_declared_source_view']is not True or disco['formal_pool_complete']is not False):
        raise TargetValidationError('Disco host lost its complete original source binding')
    from .cards.past_mage_arcane_source_cards import BATCH_PATH as SPELL_PATH,load_batch as load_spell_sources
    spells=load_spell_sources()
    expected=[dict(source_document=SPELL_PATH.relative_to(ROOT).as_posix(),
        source_document_canonical_sha256=canonical_digest(spells),reference_document=d['reference_document'],
        reference_sha256=d['reference_sha256'],source_card_id=d['source_card_id'],pool_id=d['pool_id'],
        original_reference_pool_id=d['original_reference_pool_id'],member_count=len(d['member_ids']),
        member_ids=d['member_ids'],complete_for_declared_source_view=True,formal_pool_complete=False)for d in spells['domains']]
    if value['mage_arcane_spell_bindings']!=expected or set(d['pool_id']for d in expected)&set(names+scoped+[disco['pool_id']]):
        raise TargetValidationError('Past spell host lost a complete original source, class inventory or separate pool role')
    from .cards.past_teacher_mage_source import BATCH_PATH as TEACHER_PATH,load_batch as load_mage_teacher
    teacher=load_mage_teacher()
    if value['teacher_mage_binding']!=dict(source_document=TEACHER_PATH.relative_to(ROOT).as_posix(),
            source_document_canonical_sha256=canonical_digest(teacher),source_card_id='TIME_704',
            pool_id='constructed.past.spells',original_member_count=21,mage_member_count=24,merged_member_count=44,
            complete_for_declared_source_view=True,formal_pool_complete=False):
        raise TargetValidationError('Mage teacher host lost its complete source view or original Druid inventory')
    from .cards.champions_of_azeroth import BATCH_PATH as CHAMPIONS_PATH,load_batch as load_champions
    champions=load_champions()
    champion_binding=dict(source_document=CHAMPIONS_PATH.relative_to(ROOT).as_posix(),
        source_document_canonical_sha256=canonical_digest(champions),source_card_id='WON_113',
        pool_ids=[d['pool_id']for d in champions['domains']],
        choice_card_ids=[d['choice_card_id']for d in champions['domains']],
        member_ids_by_pool=[d['member_ids']for d in champions['domains']],member_count=10,
        complete_for_declared_source_view=True,formal_pool_complete=False)
    reserved=set(names+scoped+list(ORDINARY_POOLS)+value['unresolved_pool_ids']+
        [pack['pool_id'],rajh['pool_id'],disco['pool_id']]+zombeast['pool_ids']+[d['pool_id']for d in expected])
    if value['champions_binding']!=champion_binding or set(champion_binding['pool_ids'])&reserved:
        raise TargetValidationError('Champion host lost a complete faction role or overlaps another source domain')
    from .cards.toki_mage_source import BATCH_PATH as TOKI_PATH,load_batch as load_toki_mage
    toki=load_toki_mage()
    if value['toki_mage_binding']!=dict(source_document=TOKI_PATH.relative_to(ROOT).as_posix(),
            source_document_canonical_sha256=canonical_digest(toki),source_card_id='TIME_861',
            pool_id='constructed.past.spells',current_class='mage',original_mage_reference_count=179,
            mage_neutral_member_count=181,prior_merged_member_count=44,merged_member_count=201,
            actual_eligible_count=178,complete_for_declared_source_view=True,formal_pool_complete=False):
        raise TargetValidationError('Toki host lost its complete Mage/neutral inventory or source scope')
    return value


def _reviewed_sources(registry, manifest):
    result = []
    for item in manifest['bindings']:
        document = (ROOT / item['source_document']).resolve()
        if (not document.is_relative_to(ROOT) or
                hashlib.sha256(document.read_bytes()).hexdigest() != item['source_document_sha256']):
            raise TargetValidationError('Local special pool source document changed')
        source = registry.pool(item['pool_id'],
            GenerationContext(item['source_target_id'], item['source_mode']))
        if (canonical_digest(asdict(source)) != item['source_pool_sha256'] or
                [member.card_id for member in source.members] != item['member_ids'] or
                item['complete_for_declared_inventory'] is not True):
            raise TargetValidationError('Local special pool lost its original full inventory or weights')
        # The manifest never becomes a filter for executable coverage.
        for member in source.members:
            registry.card(member.card_id)
        result.append(replace(source, complete=True))
    return tuple(result)


def build_cn37_local_pool_format():
    """Build the fixed local format without a client, outputs, or network.

    New manifests add independently reviewed inventories through this shared
    binding step. Unresolved pool IDs are deliberately not installed.
    """
    manifest = load_bindings()
    original = build_cn37_launch_candidate_format()
    registry = original.registry
    ordinary = tuple(registry.pool(pool_id, original.context) for pool_id in ORDINARY_POOLS)
    from .cards.past_source_scoped_pools import local_pools,register_scopes,BATCH_PATH
    from .cards.one_cost_past_pool import local_pool,register_scope,BATCH_PATH as ONE_COST_PATH
    from .cards.standard_pack_inventory import local_pool as standard_pack_pool,BATCH_PATH as PACK_PATH
    from .cards.rajh_known_passive_pool import local_pool as rajh_pool,BATCH_PATH as RAJH_PATH
    from .cards.zombeast_reference_pools import local_pools as zombeast_pools,BATCH_PATH as ZOMBEAST_PATH
    from .cards.past_colossal_source_pool import missing_metadata,merge_pools,register_scope as register_colossal_scope
    from .cards.past_paladin_mech_source_pool import (missing_metadata as mech_metadata,
        merge_pools as merge_mech_pools,register_scope as register_mech_scope,load_batch as load_mech_binding)
    paths=(BATCH_PATH,ONE_COST_PATH)
    if len(manifest['scoped_bindings'])!=len(paths):raise TargetValidationError('Scoped past source documents missing or duplicated')
    for item,path in zip(manifest['scoped_bindings'],paths):
        if (item['source_document']!=path.relative_to(ROOT).as_posix() or
                item['source_document_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise TargetValidationError('Scoped past source document changed')
    pack = manifest['pack_binding']
    if (pack['source_document'] != PACK_PATH.relative_to(ROOT).as_posix() or
            pack['source_document_sha256'] != hashlib.sha256(PACK_PATH.read_bytes()).hexdigest()):
        raise TargetValidationError('Local pack source document changed')
    rajh = manifest['rajh_binding']
    if (rajh['source_document'] != RAJH_PATH.relative_to(ROOT).as_posix() or
            rajh['source_document_sha256'] != hashlib.sha256(RAJH_PATH.read_bytes()).hexdigest()):
        raise TargetValidationError('Local Rajh source document changed')
    zombeast = manifest['zombeast_binding']
    if (zombeast['source_document'] != ZOMBEAST_PATH.relative_to(ROOT).as_posix() or
            zombeast['source_document_canonical_sha256'] != canonical_digest(
                json.loads(ZOMBEAST_PATH.read_text(encoding='utf8')))):
        raise TargetValidationError('Local Zombeast source document changed')
    # The existing one-cost inventory installs its reviewed SCV metadata too;
    # build that dependency before validating the new source's complete pins.
    one_cost_pool = local_pool(registry,original.context)
    # Prepare all new-source additions before installing any, including a late
    # failure in this source. Metadata does not extend ordinary deck legality.
    metadata_additions = missing_metadata(registry) + mech_metadata(registry)
    for metadata in metadata_additions: registry.register_pool_card(metadata)
    past_pools = merge_pools(registry,original.context,local_pools(registry,original.context))
    past_pools = merge_mech_pools(registry,original.context,past_pools)
    from .cards.past_teacher_mage_source import merge_pools as merge_mage_teacher,register_scope as register_mage_teacher
    past_pools = merge_mage_teacher(registry,original.context,past_pools)
    from .cards.toki_mage_source import merge_pools as merge_toki_mage,register_scope as register_toki_mage,load_batch as load_toki_mage
    past_pools = merge_toki_mage(registry,original.context,past_pools)
    from .cards.protoss_spell_domain import local_pool as protoss_pool
    from .cards.azerite_hawk_domain import local_pool as hawk_pool
    from .cards.azerite_reward_domains import local_pools as azerite_pools
    from .cards.excavate_local_host import local_pools as excavation_pools, profile as excavation_profile
    from .cards.disco_past_secrets import local_pool as disco_pool,register_scope as register_disco_scope
    from .cards.past_mage_arcane_source_cards import local_pools as past_spell_pools,register_scopes as register_past_spell_scopes
    from .cards.champions_of_azeroth import local_pools as champion_pools,register_scopes as register_champion_scopes
    from .cards.past_mage_effect_consumers import gift_pool
    from .cards.past_druid_nature_source import local_pool as nature_pool,register_scope as register_nature_scope
    pools = ordinary + _reviewed_sources(registry, manifest) + past_pools + (
        one_cost_pool,standard_pack_pool(registry,original.context),rajh_pool(registry,original.context)) + zombeast_pools(registry,original.context) + (protoss_pool(registry,original.context),hawk_pool(registry,original.context),gift_pool(registry,original.context)) + azerite_pools(registry,original.context) + excavation_pools(registry,original.context) + (disco_pool(registry,original.context),) + past_spell_pools(registry,original.context) + champion_pools(registry,original.context)
    pools=pools+(nature_pool(registry,original.context),)
    excavation = excavation_profile(original.context)
    binding = canonical_digest(dict(format=FORMAT_VERSION,
        original_binding=original.binding_digest, manifest=canonical_digest(manifest),
        inventories=[asdict(pool) for pool in pools], excavation_profiles=[asdict(excavation)]))
    target_id = FORMAT_VERSION + '-' + binding[:16]
    context = GenerationContext(target_id, original.context.mode)
    for pool in pools:
        registry.register_pool(replace(pool, target_id=target_id, mode=context.mode,
            version=manifest['policy_id'] + '-' + binding[:16] + ':' + pool.version))
    register_scopes(registry,context)
    register_scope(registry,context)
    register_colossal_scope(registry,context,reviewed_member_ids=tuple(load_mech_binding()['merged_member_ids']))
    register_mech_scope(registry,context)
    register_disco_scope(registry,context)
    register_past_spell_scopes(registry,context)
    register_mage_teacher(registry,context,reviewed_member_ids=tuple(load_toki_mage()['merged_member_ids']))
    register_champion_scopes(registry,context)
    register_toki_mage(registry,context)
    register_nature_scope(registry,context)
    registry.register_excavation_profile(replace(excavation, target_id=target_id, mode=context.mode))
    policy = replace(original.policy, id=target_id + '.deck', target_id=target_id)
    registry.validate()
    return replace(original, target_id=target_id, binding_digest=binding,
        policy=policy, context=context)
