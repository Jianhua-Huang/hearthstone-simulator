"""Complete original Warrior Nature source and its two remaining native spells."""
from dataclasses import asdict,replace
import hashlib,json
from pathlib import Path
from hs_sim.engine.effects import CopyMinion,Damage,DamageBatch,InvokeBehavior
from hs_sim.engine.generation_scopes import GenerationScope,pool_digest
from hs_sim.engine.model import (BoardPresenceReference,CardClass,CardDefinition,CardType,
    DamageKind,IntrinsicCostSpec,SpellSchool)
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember,resolve_candidates
from hs_sim.engine.previous_turn_spell_costs import CONDITION,HISTORY
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import TargetValidationError,canonical_digest
from . import past_priest_nature_source as reference
from .metadata import metadata_from_record
from .simple_followup_p89_cards import WO,QUERIES,WARRIOR_NATURE_PAST_POOL

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-warrior-nature-source-v1.json'
BATCH_HASH='3d2806485ac8e7a85c3d8e9843367ae2b9defec5695702cdaa379818abae68ff'
POLICY='cn37-local-warrior-past-nature-v1'
ROOTS=('DEEP_010','UNG_927')
MEMBERS=('DEEP_010','UNG_927','YOP_015')
PREFIX='cards.past_warrior_nature_source.'


def make_definition(raw):
    cid=raw['id']
    if (cid not in ROOTS or raw['type']!='SPELL' or raw['cost']!=4 or raw['collectible']is not True or raw['tags'].get('SPELL_SCHOOL')!=4):
        raise TargetValidationError('Warrior Nature requires the complete fixed original four-cost Nature faces')
    extra={'intrinsic_costs':(IntrinsicCostSpec(delta=-2,condition=CONDITION,history_profile_id=HISTORY),)}if cid=='DEEP_010'else{}
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=4,on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE,metadata=metadata_from_record(raw),**extra)


def load_batch():
    d=json.loads(BATCH_PATH.read_text('utf8'));raw=reference.load_batch()
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or d['policy_id']!=POLICY or
            tuple(v['record']['id']for v in d['cards'])!=ROOTS or d['dependencies']or d['evidence_only']or
            [v['record']['id']for v in d['existing_dependencies']]!=['YOP_015',WO]or
            len(d['official_observations'])!=8 or d['source_card_id']!=WO or d['pool_id']!=WARRIOR_NATURE_PAST_POOL or
            d['member_ids']!=list(MEMBERS)or[v['card_id']for v in d['native_pins']]!=list(MEMBERS)or
            canonical_digest(d['query'])!=canonical_digest(asdict(QUERIES[WO]))or
            any(d[k]for k in ('new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Warrior Nature lost a complete source, native face or separate original role')
    if (d['full_union_source_document']!=reference.BATCH_PATH.relative_to(ROOT).as_posix()or
            hashlib.sha256(reference.BATCH_PATH.read_bytes()).hexdigest()!=d['full_union_source_sha256']):
        raise TargetValidationError('Warrior Nature changed its complete original 174-row reference')
    for key in ('cards','existing_dependencies'):
        for v in d[key]:
            if canonical_digest(v['record'])!=v['record_sha256']:raise TargetValidationError('Warrior Nature lost a complete original row')
    derived=[v['record']['id']for v in raw['full_union_records']if
        CardClass.WARRIOR in metadata_from_record(v['record']).classes or CardClass.NEUTRAL in metadata_from_record(v['record']).classes]
    if derived!=list(MEMBERS):raise TargetValidationError('Warrior Nature differs from its complete original class order')
    return d


def live_minions(c,player):
    return tuple(c.state.entities[eid]for eid in c.state.players[player].board if
        c.state.entities[eid].kind==CardType.MINION and c.state.entities[eid].active and
        not c.state.entities[eid].doomed and c.state.entities[eid].health>0)


def register_past_warrior_nature_cards(registry):
    prepared=[]
    for row in load_batch()['cards']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Warrior Nature cannot replace or lose an original native face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):
            raise TargetValidationError('Warrior Nature changed an existing complete metadata row')
        prepared.append(card)
    def pulse(c):
        return(DamageBatch(tuple(Damage(e.id,1,c.source_id,kind=DamageKind.SPELL)
            for player in (1,2)for e in live_minions(c,player))),)
    def blood_warriors(c):
        group=tuple(BoardPresenceReference.capture(c.state,e.id)for e in live_minions(c,c.player_id)if e.damage>0)
        cause=SummonCause.capture(c)
        return tuple(CopyMinion(ref,c.player_id,cause=cause)for ref in group)
    registry.register_behavior(PREFIX+'pulse',pulse)
    registry.register_behavior(PREFIX+'DEEP_010',lambda c:(InvokeBehavior(PREFIX+'pulse',c.source_id,c.player_id),)*3)
    registry.register_behavior(PREFIX+'UNG_927',blood_warriors)
    for c in prepared:
        registry.register_card(c)
        if c.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(c))


def checked_native(registry,d):
    for v in d['native_pins']:
        cid=v['card_id']
        if (canonical_digest(asdict(registry.card(cid)))!=v['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=v['pool_card_sha256']):
            raise TargetValidationError('Warrior Nature lost complete native member '+cid)
    for v in d['existing_dependencies']:
        if canonical_digest(asdict(registry.card(v['record']['id'])))!=v['definition_sha256']:
            raise TargetValidationError('Warrior Nature changed its existing source/shared effect')


def local_pool(registry,context):
    d=load_batch();checked_native(registry,d)
    return PoolDefinition(WARRIOR_NATURE_PAST_POOL,POLICY,context.target_id,context.mode,
        tuple(PoolMember(cid)for cid in d['member_ids']),complete=True)


def register_scope(registry,context):
    d=load_batch();expected=local_pool(registry,context);pool=registry.pool(WARRIOR_NATURE_PAST_POOL,context)
    if pool!=replace(expected,version=context.target_id+':'+expected.version):
        raise TargetValidationError('Warrior Nature cannot borrow, crop, reorder or reweight a source')
    registry.register_generation_scope(GenerationScope(POLICY+':'+WO+':warrior:'+context.target_id,
        pool.id,context.target_id,context.mode,WO,CardClass.WARRIOR,QUERIES[WO],pool_digest(pool)))
    actual=resolve_candidates(registry,context,pool.id,QUERIES[WO],current_class=CardClass.WARRIOR,source_card_id=WO,exclude_source_by_rule=True)
    if [v.card_id for v in actual]!=d['member_ids']or[v.weight for v in actual]!=[1]*3:
        raise TargetValidationError('Warrior Nature actual candidates changed complete original order or weights')
