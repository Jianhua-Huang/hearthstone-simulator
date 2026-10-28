"""Three original Mage spells over immutable physical draw-group roots."""
from dataclasses import replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.costs import local_cost
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup,SPELL_COST_FOLLOWUP
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.spell_casts import active_cast
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-mage-draw-followups-v1.json'
BATCH_HASH='35da1c747e0e0fbaf0703c7b91ab17d4262aae0c6831d10d7c46c6eae11dced3'
POLICY='cn37-local-past-mage-draw-followups-v1'
LEAVES=DEPENDENCIES=('BAR_542','GIL_548','VAC_431')
COLLECTIBLE_ROOTS=()
PREFIX='cards.past_mage_draw_followups.'
POOL='constructed.cards'


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(d['collectible_leaf_ids'])!=LEAVES or
            tuple(row['record']['id']for row in d['dependencies'])!=DEPENDENCIES or
            len(d['official_observations'])!=6 or any(d[k]for k in ('cards','existing_dependencies',
                'new_standard_roots','source_scope_bound','formal_pool_complete','cn_calibrated')) or
            any(canonical_digest(row['record'])!=row['record_sha256']for row in d['dependencies'])):
        raise TargetValidationError('Past Mage draw followups require their three full original records')
    path=ROOT/d['reference_document']
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=d['reference_sha256'] or
            not set(LEAVES)<=set(json.loads(path.read_text(encoding='utf8'))['candidate_ids'])):
        raise TargetValidationError('Past Mage draw followups lost the full original reference scope')
    return d


def register_past_mage_draw_followups(registry):
    prepared=[]
    for row in load_batch()['dependencies']:
        raw=row['record'];cid=raw['id']
        if raw['type']!='SPELL' or cid in registry.cards or cid in registry.pool_cards:
            raise TargetValidationError('Past Mage draw followups require original new spell faces')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),metadata=metadata_from_record(raw))
        registry._validate_card(card);prepared.append(card)
    def undersea(c):
        row=next(a for a in c.draw_group.arrivals if a.draw_id==c.draw.id)
        cost=max(0,local_cost(row.copy.entity())[0])
        cast=active_cast(c.state,c.source_id,c.player_id)
        if cast is None:raise ResolutionError('Under the Sea lost its original active spell CAST')
        return (SummonFromPool(c.player_id,POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=cost,max_cost=cost),source_id=c.source_id,cause=SummonCause.capture(replace(c,cast=cast))),)
    registry.register_behavior(PREFIX+'undersea',undersea)
    bodies={
        'BAR_542':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*2,
            DrawGroupReward('refresh_drawn_spells',2)),),
        'GIL_548':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*3,
            DrawGroupReward('discard_drawn_spells')),),
        'VAC_431':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,),exclude_source=True)),),
            DrawGroupReward(SPELL_COST_FOLLOWUP,behavior_id=PREFIX+'undersea')),),
    }
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
