"""Finite reviewed spell recipes; execution stays in existing public effects."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,DamageBatch,Draw,RandomDamageBatch
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,TargetMode,TargetSpec,Zone
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import tribe_state
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/health-sequence-spells-v1.json'
BATCH_HASH='2f9a6df7745f6e65958cb73d7929db1cb4955356f4bac83cd81fd0cf91c23cfa'
PREFIX='cards.health_sequence.'
SCRIPTS={'FIR_909':'burst','FIR_954':'scorch','TLC_440':'cryo','TLC_901':'fumes','TIME_216':'electric','EDR_814':'infest'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Health sequence spells differ from their complete reviewed pin')
    return data


def shares_type(left,right):
    if left is None or right is None:raise UnsupportedDefinitionError('Unknown current minion tribe in shared-type damage')
    if not left.members or not right.members:return False
    if left.members==right.members==('all',):return True
    if left.members==('all',):return left.matches_any(right.members)
    if right.members==('all',):return right.matches_any(left.members)
    return bool(set(left.members)&set(right.members))


def register_health_sequence_cards(registry):
    def scorch_result(c):
        result=c.health_result;target=c.state.entities[result.original_target_id]
        return(Draw(target.controller,1,c.source_id),)
    def electric_result(c):
        # RuleContext holds the original post-health-batch/pre-reaction facts.
        # A later return, reborn or trigger cannot turn a failed survival into
        # success, or rewrite an already accepted reward.
        result=c.health_result;target=c.state.entities[result.original_target_id]
        survived=target.kind==CardType.MINION and target.zone==Zone.BOARD and target.active and target.health>0 and not target.doomed
        return(Draw(c.player_id,2,c.source_id),)if survived else()
    def cryo(c):
        match=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card('TLC_440')))
        return(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),Draw(c.player_id,2 if match.matched else 1,c.source_id))
    def fumes(c):
        target=c.state.entities[c.target_id]
        if target.kind!=CardType.MINION or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return ()
        tribe=tribe_state(registry,target)
        if tribe is None:raise UnsupportedDefinitionError('Unknown target tribe in shared-type damage')
        ids=[target.id]
        if tribe.members:
            ids.extend(eid for p in(1,2)for eid in minions(c,registry,p)if eid!=target.id and shares_type(tribe,tribe_state(registry,c.state.entities[eid])))
        return(DamageBatch(tuple(Damage(eid,3,c.source_id,DamageKind.SPELL)for eid in ids)),)
    def infest(c):
        return(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),
            SummonByCard(c.player_id,(SummonEntryMaterial('EDR_810t'),),SummonCause.capture(c)))
    bodies=dict(burst=lambda c:(RandomDamageBatch(characters(c,registry,3-c.player_id),3,2,c.source_id,DamageKind.SPELL),),
        scorch=lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL,PREFIX+'scorch_result'),),scorch_result=scorch_result,
        cryo=cryo,fumes=fumes,electric=lambda c:(Damage(c.target_id,5,c.source_id,DamageKind.SPELL,PREFIX+'electric_result'),),
        electric_result=electric_result,infest=infest)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    for row in data['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Existing Leech lost its reviewed native face')
        registry.card(row['record']['id'])
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];cid=raw['id'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(cid)!=recipe['script']:
            raise TargetValidationError('Health sequence recipe lost its complete reviewed spell face')
        target=recipe['target']
        if target=='minion':kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        elif target=='character':kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
        elif target is not None:raise TargetValidationError('Unknown health sequence target recipe')
        school=raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unknown health sequence spell school')
        card=CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
