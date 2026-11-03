"""Independent complete local Amber membership; execution is checked after selection."""
import json
from pathlib import Path

from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import CardType,Keyword
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/amber-past-minions-reference-v1.json'
BATCH_HASH='40835eaa22b935eabfab5797433a8c7345e67e1b71152c2c793c1de6e01d7040'
SOURCE='TIME_052'
POOL='constructed.past.amber_minions'
LEGACY_POOL='constructed.past.cards'
POLICY='cn37-local-amber-full-minion-reference-v1'
QUERY=PoolQuery(kinds=(CardType.MINION,),collectible=True)


def producer_pool(registry):
    # Existing independent experimental fixtures keep their explicit old domain.
    # A bound host installs the separate complete source, never the 72-card union.
    return POOL if any(p.id==POOL for p in registry.pools.values())else LEGACY_POOL


def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['source_card_id']!=SOURCE or
            d['pool_id']!=POOL or d['policy_id']!=POLICY or d['weight']!=1 or
            d['definition_validation']!='selected_summon' or
            any(d[k]for k in ('membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Amber requires its full independent local reference and explicit coverage limits')
    prior=json.loads((ROOT/d['upstream_policy_document']).read_text('utf-8'))
    if (canonical_digest(prior)!=d['upstream_policy_canonical_sha256'] or
            d['past_set_ids']!=prior['candidate_reference']['reference']['set_ids']):
        raise TargetValidationError('Amber changed the fixed original local Past set policy')
    rows=d['records'];ids=[v['record']['id']for v in rows]
    if (len(ids)!=3387 or ids!=sorted(set(ids)) or ids!=d['member_ids'] or
            any(canonical_digest(v['record'])!=v['record_sha256']for v in rows) or
            any(r['record']['type']!='MINION' or r['record']['collectible']is not True or
                r['record']['card_set_id']not in d['past_set_ids']for r in rows)):
        raise TargetValidationError('Amber lost, duplicated or changed an original full candidate record')
    excluded=[v['record']['id']for v in rows if v['record']['tags'].get('COLOSSAL')or
              v['record']['tags'].get('DONT_PICK_FROM_SUBSETS')]
    if excluded!=d['excluded_ids'] or len(excluded)!=29:
        raise TargetValidationError('Amber changed its independent native/Colossal exclusions')
    zeros={v['record']['id']for v in rows if v['record']['cost']is None}
    if zeros!=set(d['zero_cost_evidence']):raise TargetValidationError('Amber lost explicit omitted-cost evidence')
    for cid,entry in d['zero_cost_evidence'].items():
        if entry['cost']!=0 or {f['locale']for f in entry['observations']}!={'zh_CN','en_US'} or any(
                type(f['face'].get('manaCost'))is not int or f['face']['manaCost']!=0
                for f in entry['observations']):
            raise TargetValidationError('Amber omitted cost must retain both complete primary zero observations')
    return d


def local_pool(registry,context):
    d=load_batch();pending=[]
    for item in d['records']:
        raw=item['record'];cid=raw['id'];meta=metadata_from_record(raw)
        cost=raw['cost']if raw['cost']is not None else d['zero_cost_evidence'][cid]['cost']
        if cid in registry.cards:
            printed=PoolCard.from_definition(registry.card(cid))
            if printed.kind!=CardType.MINION or printed.cost!=cost or printed.metadata.collectible is not True or printed.metadata.classes!=meta.classes:
                raise TargetValidationError('Amber native printed facts differ from the fixed record: '+cid)
        else:
            tags=raw['tags']
            printed=PoolCard(cid,CardType.MINION,cost,meta,
                keywords=tuple(k for k in Keyword if tags.get(k.name,0)>0),
                battlecry=bool(tags.get('BATTLECRY')),deathrattle=bool(tags.get('DEATHRATTLE')),
                choose_one=bool(tags.get('CHOOSE_ONE')),attack=raw['attack'])
        if cid not in registry.pool_cards:pending.append(printed)
    for row in pending:registry.register_pool_card(row)
    return PoolDefinition(POOL,POLICY,context.target_id,context.mode,
        tuple(PoolMember(cid)for cid in d['member_ids']),tuple(d['excluded_ids']),complete=True)


def register_scope(registry,context):
    pool=registry.pool(POOL,context);d=load_batch()
    if (tuple(m.card_id for m in pool.members)!=tuple(d['member_ids'])or
            any(m.weight!=1 for m in pool.members)or tuple(d['excluded_ids'])!=pool.excluded_card_ids):
        raise TargetValidationError('Amber source inventory was cropped or reweighted')
    registry.register_generation_scope(GenerationScope(POLICY+':'+context.target_id,
        POOL,context.target_id,context.mode,SOURCE,None,QUERY,pool_digest(pool),
        definition_validation='selected_summon'))
