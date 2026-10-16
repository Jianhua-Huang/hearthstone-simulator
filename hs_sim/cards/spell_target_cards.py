"""Reviewed lowest/primary/other/hand-center target spell recipes."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.effects import Damage,InvokeBehavior,Overload,RandomDamage
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,TargetMode,TargetSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.spell_target_sequences import FreezeRandomEnemyMinions,DamageEnemyAndRandomOthers,RandomMinionDamageDrawDeaths
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/spell-target-sequences-v1.json'
BATCH_HASH='391c7859add3e3625d3ef16798006c5157656f5c7013ac765d0ca345ddec5427'
PREFIX='cards.spell_targets.'
SCRIPTS={'TLC_227':'lava','TIME_611':'stasis','TIME_855':'barrage','TIME_600':'precision','CORE_CATA_007':'consume'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Target spell recipes differ from their complete reviewed pin')
    return data


def cast_args(c):
    if c.cast is None or c.cast.source_id!=c.source_id:raise ValueError('Target sequence requires actual current SPELL cast')
    return(c.player_id,c.cast.id,c.source_id)


def register_spell_target_cards(registry):
    def lava(c):
        return(*tuple(InvokeBehavior(PREFIX+'lava_wave',c.source_id,c.player_id,play_id=None if c.play is None else c.play.id)for _ in range(3)),Overload(c.player_id,1))
    def lava_wave(c):
        ids=characters(c,registry,3-c.player_id)
        if not ids:return ()
        lowest=min(c.state.entities[eid].health for eid in ids)
        return(RandomDamage(tuple(eid for eid in ids if c.state.entities[eid].health==lowest),2,c.source_id,DamageKind.SPELL),)
    def stasis(c):return(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),FreezeRandomEnemyMinions(*cast_args(c),2))
    def barrage(c):
        return(DamageEnemyAndRandomOthers(*cast_args(c),SourceAllocationFact.capture(c.state,c.state.entities[c.target_id]),3,2,2),)
    def precision(c):
        play=c.play
        center=play is not None and play.source_id==c.source_id and play.hand_size%2==1 and play.hand_index==play.hand_size//2
        return(Damage(c.target_id,5 if center else 3,c.source_id,DamageKind.SPELL),)
    bodies=dict(lava=lava,lava_wave=lava_wave,stasis=stasis,barrage=barrage,precision=precision,
        consume=lambda c:(RandomMinionDamageDrawDeaths(*cast_args(c),3,2),))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(raw['id'])!=recipe['script']:
            raise TargetValidationError('Target spell lost its complete reviewed face')
        target=recipe['target']
        if target in('character','enemy'):
            kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION),relation='enemy'if target=='enemy'else'any')
        elif target is not None:raise TargetValidationError('Unreviewed target spell domain')
        school=raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unreviewed target spell school')
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],spell_school=SCHOOLS.get(school),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
