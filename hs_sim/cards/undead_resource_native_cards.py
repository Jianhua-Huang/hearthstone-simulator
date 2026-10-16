"""Real Undead mana, death threshold, physical Kindred tutor and native spell value."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,InvokeBehavior,RefreshMana,SplitDamage
from hs_sim.engine.kindred import request as kindred_request
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,KindredProfile,Keyword,TargetSpec,TriggerSpec
from hs_sim.engine.native_spell_values import CreateDeathrattleSpell,SpellBaseDamageProfile
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.turn_start_draws import TurnDrawSuppressionProfile
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/undead-resource-native-v1.json'
BATCH_HASH='690383373ce3911b0fe3624e66ec654edab7158d7cd563705f8d20bc5eace289'
BROODMOTHER='CATA_469';AESSINA='EDR_430';RAPTOR='TLC_432';EXPERIMENT='CATA_464';CHILLER='TIME_617';BREATH='CATA_464t'
PREFIX='cards.undead_resource_native.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Undead resource native complete source pin changed')
    return data


def register_undead_resource_native_cards(registry):
    def broodmother(c):
        if c.event is None or c.event.kind!='attack_declared'or c.event.source_id!=c.source_id:return()
        return(RefreshMana(c.player_id,max(0,c.source.attack)),)
    def aessina(c):
        count=sum(d.controller==c.player_id and registry.card(d.card_id).kind==CardType.MINION for d in c.state.death_history)
        return(SplitDamage(3-c.player_id,20,c.source_id,kind=DamageKind.MINION_ABILITY),)if count>=20 else()
    def raptor(c):
        reward=DrawGroupReward('set_cost_all',0,c.kindred.repetitions)if c.kindred.condition.matched else DrawGroupReward()
        slot=DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,)),max_current_cost=3,current_deathrattle=True)
        return(DrawPhysicalGroup(c.player_id,c.source_id,(slot,),reward),)
    def experiment(c):
        if c.deathrattle is None:raise UnsupportedDefinitionError('Blackwing Experiment requires its actual accepted Deathrattle')
        return(CreateDeathrattleSpell(c.player_id,BREATH,c.deathrattle.id),)
    def breath(c):
        if c.cast is None or c.cast.native_spell_value is None:raise UnsupportedDefinitionError('Dragon Breath has no actual bound native base damage')
        return(Damage(c.target_id,c.cast.native_spell_value.spell_base_value.amount,c.source_id,DamageKind.SPELL),)
    registry.register_behavior(PREFIX+'broodmother',broodmother)
    registry.register_behavior(PREFIX+'aessina',lambda c:(InvokeBehavior(PREFIX+'aessina_now',c.source_id,c.player_id),))
    registry.register_behavior(PREFIX+'aessina_now',aessina)
    for name,body in(('raptor_prepare',raptor),('experiment',experiment),('breath',breath)):registry.register_behavior(PREFIX+name,body)
    # Registration replaces this wrapper with the shared native Kindred producer.
    registry.register_behavior(PREFIX+'raptor',lambda c:kindred_request(c,RAPTOR))
    data=load_batch()
    if tuple(x['record']['id']for x in data['cards'])!=(BROODMOTHER,AESSINA,RAPTOR,EXPERIMENT,CHILLER)or tuple(x['record']['id']for x in data['dependencies'])!=(BREATH,):
        raise TargetValidationError('Unreviewed Undead resource root/dependency set')
    for row in data['cards']+data['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Incomplete Undead resource native raw face')
        kind=CardType(raw['type'].lower())
        if cid==BROODMOTHER:kwargs.update(keywords=(Keyword.RUSH,),triggers=(TriggerSpec('attack_declared',PREFIX+'broodmother'),))
        elif cid==AESSINA:kwargs['battlecry']=PREFIX+'aessina'
        elif cid==RAPTOR:kwargs['battlecry']=PREFIX+'raptor'
        elif cid==EXPERIMENT:kwargs['deathrattle']=PREFIX+'experiment'
        elif cid==BREATH:kwargs.update(on_play=PREFIX+'breath',targeting=TargetSpec(),spell_school=SCHOOLS[raw['tags']['SPELL_SCHOOL']])
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']or 0,
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_kindred_profile(KindredProfile(RAPTOR,'body',wrapper=PREFIX+'raptor',prepare=PREFIX+'raptor_prepare'))
    registry.register_spell_value_profile(SpellBaseDamageProfile(BREATH,EXPERIMENT))
    registry.register_turn_draw_profile(TurnDrawSuppressionProfile(CHILLER))
