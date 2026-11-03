"""Five native Rogue spells required by the pinned Mentor source view."""
from dataclasses import asdict, replace
import json
from pathlib import Path

from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import Damage, Draw, InvokeBehavior
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CostSpec, DamageKind,
    PlayerDrawCountCostSpec, PlayerPlayedClassCostSpec, TargetMode, TargetSpec, Zone)
from hs_sim.engine.physical_draw_groups import DrawPhysicalGroup, DrawGroupSlot, DrawGroupReward
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolMember, PoolQuery, resolve_candidates
from hs_sim.engine.generation_scopes import GenerationScope, pool_digest
from hs_sim.engine.student_teaching import QUERY as TEACHER_QUERY
from hs_sim.engine.spell_targets import RandomDestroyEnemySpellGroup
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference, MoveCard, ModifyStoredCost, ShuffleDeck
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

ROOTS=('GDB_467','ONY_031','TOY_519','VAC_700','WW_410')
PREFIX='cards.rogue_teacher.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/rogue-teacher-spells-v1.json'
BATCH_HASH='8dcfd1bd390c258dab4f60675a9e345ed943c414e41dd4d42114394b8f84b035'
FOUR=PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=4,max_cost=4)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(d)!=BATCH_HASH or tuple(d['roots'])!=ROOTS or d['formal_pool_complete']or d['cn_calibrated']:
        raise TargetValidationError('Rogue Mentor spells require the complete pinned five-card batch')
    if any(canonical_digest(row['record'])!=row['record_sha256']for row in d['cards'].values()):
        raise TargetValidationError('Rogue Mentor lost a complete original source row')
    return d


def make_definition(raw):
    cid=raw['id'];fields={}
    if cid not in ROOTS or raw['type']!='SPELL':raise TargetValidationError('Expected an original Rogue spell')
    if cid=='TOY_519':fields['player_draw_count_cost']=PlayerDrawCountCostSpec('cost.player-physical-draw-count-turn-v1')
    if cid=='VAC_700':fields['player_played_class_cost']=PlayerPlayedClassCostSpec(None,'cost.player-played-other-class-v1')
    if cid=='WW_410':fields['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
        metadata=metadata_from_record(raw),spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**fields)


def quasar(c):
    hand=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].hand)
    moves=tuple(MoveCard(card,c.player_id,Zone.DECK,'random',source_id=c.source_id)for card in hand)
    return (*shuffled(c,moves), *((ShuffleDeck(c.player_id),)if moves else()),
        InvokeBehavior(PREFIX+'discount_deck',c.source_id,c.player_id))


def discount_deck(c):
    return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-3),c.source_id)
        for i in c.state.players[c.player_id].deck)


def register_rogue_teacher_spells(registry):
    d=load_batch()
    registry.register_behavior(PREFIX+'discount_deck',discount_deck)
    bodies={
        'GDB_467':quasar,
        'ONY_031':lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*5,
            DrawGroupReward('trigger_drawn_deathrattles')),),
        'TOY_519':lambda c:(GenerateFromPool(c.player_id,'constructed.cards',FOUR,count=2,
            source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),),
        'VAC_700':lambda c:(RandomDestroyEnemySpellGroup(c.player_id,c.cast.id,c.source_id,2),),
        'WW_410':lambda c:(Damage(c.target_id,7,c.source_id,DamageKind.SPELL),Draw(c.player_id,7,c.source_id)),
    }
    for cid,body in bodies.items():
        registry.register_behavior(PREFIX+cid,body)
        card=make_definition(d['cards'][cid]['record'])
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))


def shared_member_ids():
    d=load_batch()
    return tuple(dict.fromkeys((*d['prior_member_ids'],*d['teacher_candidate_ids'])))


def validate_native(registry,d):
    for cid,pin in d['native_pins'].items():
        if (canonical_digest(asdict(registry.card(cid)))!=pin['definition_sha256'] or
                canonical_digest(asdict(registry.pool_card(cid)))!=pin['pool_card_sha256']):
            raise TargetValidationError('Rogue Mentor changed its pinned native material: '+cid)


def merge_past_pools(registry,context,pools):
    d=load_batch();validate_native(registry,d)
    matches=[p for p in pools if p.id=='constructed.past.spells']
    if len(matches)!=1:raise TargetValidationError('Rogue Mentor requires its one complete original shared pool')
    original,=matches
    if (not original.complete or original.excluded_card_ids or
            original.members!=tuple(PoolMember(cid)for cid in d['prior_member_ids'])):
        raise TargetValidationError('Rogue Mentor cannot replace a cropped or reordered original pool')
    merged=replace(original,version=d['policy_id']+':'+BATCH_HASH+':'+original.version,
        members=tuple(PoolMember(cid)for cid in shared_member_ids()))
    return tuple(merged if p is original else p for p in pools)


def register_teacher_scope(registry,context):
    d=load_batch();validate_native(registry,d);pool=registry.pool('constructed.past.spells',context)
    if not pool.complete or pool.excluded_card_ids or pool.members!=tuple(PoolMember(cid)for cid in shared_member_ids()):
        raise TargetValidationError('Rogue Mentor lost its complete independently declared union')
    registry.register_generation_scope(GenerationScope(d['policy_id']+':'+context.target_id,pool.id,
        context.target_id,context.mode,'TIME_704',CardClass.ROGUE,TEACHER_QUERY,pool_digest(pool)))
    actual=resolve_candidates(registry,context,pool.id,TEACHER_QUERY,current_class=CardClass.ROGUE,
        source_card_id='TIME_704',exclude_source_by_rule=True)
    if tuple(row.card_id for row in actual)!=tuple(d['teacher_candidate_ids']) or any(row.weight!=1 for row in actual):
        raise TargetValidationError('Rogue Mentor changed its full original candidates or weights')
