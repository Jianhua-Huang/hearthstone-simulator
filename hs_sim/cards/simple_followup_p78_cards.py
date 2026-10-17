"""Actual owner-end healing debt and ordinary older five-cost dependency bodies."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.adapt import adapt,SPORES_BEHAVIOR,_plants
from hs_sim.engine.effects import Destroy,Draw,Heal,LoseArmor,Silence
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import (CardDefinition,CardType,EndTurnSpec,HealingKind,Keyword,PlayerEffectSpec,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.player_effects import AddPlayerEffect,PlayerEffectDamage
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p78-v1.json'
BATCH_HASH='654c74f1aea02a142737aa03ed88db2bbc1b4aa8c9feb341ff60ab3f5a09a49e'
APPLE='EDR_482'
WHELP,RIDER,SONG,SLUDGE,WATCHER,ALCHEMIST,EMP,HEMET,LONGNECK,RAIDER,BREAKER=(
    'DRG_054','AT_028','CFM_657','LOOT_122','DRG_226','OG_234','BOT_540','GVG_120','UNG_100','AT_119','DRG_069')
COLLECTIBLE_ROOTS=(APPLE,)
DEPENDENCIES=(WHELP,RIDER,SONG,SLUDGE,WATCHER,ALCHEMIST,EMP,HEMET,LONGNECK,RAIDER,BREAKER)
ROOTS=COLLECTIBLE_ROOTS+DEPENDENCIES
PREFIX='cards.simple_followup_p78.'
PROGRAM=PREFIX+'apple'

def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=COLLECTIBLE_ROOTS
            or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or d['skipped']):
        raise TargetValidationError('P78 complete reviewed scope changed')
    if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]):
        raise TargetValidationError('P78 complete original row changed')
    return d

def register_simple_followup_p78_cards(registry):
    d=load_batch()
    for cid,pin in d['existing_dependency_definition_pins'].items():
        if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']:
            raise TargetValidationError('P78 lost complete existing Adapt dependency: '+cid)
    registry.register_behavior(SPORES_BEHAVIOR,_plants)
    def apple(c):
        return (Heal(c.state.players[c.player_id].hero_id,12,c.source_id,HealingKind.SPELL),
            AddPlayerEffect(c.player_id,PROGRAM,c.source_id,capture_health_source=True))
    def debt(c):
        if c.player_effect is None or c.player_effect.spec_id!=PROGRAM:
            raise ValueError('Rotten Apple requires its original captured player instance')
        return (PlayerEffectDamage(c.player_id,c.player_effect,c.state.players[c.player_id].hero_id,3),)
    def self_buff(c,attack,health):
        return (BuffCapturedMinion(MinionReference.capture(c.source),attack,health,c.source_id),)if living_source(c)else()
    def weapon(c):
        identity=c.state.players[3-c.player_id].weapon_id
        return ()if identity is None else(Destroy(identity,c.source_id),)
    bodies=dict(apple=apple,debt=debt,whelp=lambda c:(Draw(c.player_id,source_id=c.source_id),),
        rider=lambda c:self_buff(c,4,0),song=lambda c:()if c.target_id is None else(Silence(c.target_id),),sludge=weapon,
        watcher=lambda c:()if c.target_id is None else(Heal(c.target_id,8,c.source_id,HealingKind.EFFECT),),
        alchemist=lambda c:()if c.target_id is None else(Heal(c.target_id,5,c.source_id,HealingKind.EFFECT),),
        destroy=lambda c:()if c.target_id is None else(Destroy(c.target_id,c.source_id),),
        longneck=lambda c:adapt(c,(c.source_id,),registry),
        raider=lambda c:self_buff(c,2,2)if is_inspire(c.state,c.event,c.player_id)else(),
        breaker=lambda c:(LoseArmor(3-c.player_id,source_id=c.source_id),))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,APPLE,kind='objective',duration=2,tick_event='turn_ended',
        triggers=(TriggerSpec('turn_ended',PREFIX+'debt',EndTurnSpec()),)))
    for tribe in('mech','beast'):registry.register_target_predicate(TargetPredicateSpec(PREFIX+tribe,current_tribes_any=(tribe,)))
    scripts={WHELP:'whelp',SONG:'song',SLUDGE:'sludge',WATCHER:'watcher',ALCHEMIST:'alchemist',EMP:'destroy',HEMET:'destroy',LONGNECK:'longneck',BREAKER:'breaker'}
    for item in d['cards']+d['dependencies']:
        raw=item['record'];cid=raw['id'];kw={}
        if cid in scripts:kw['battlecry']=PREFIX+scripts[cid]
        if cid==APPLE:kw['on_play']=PREFIX+'apple'
        if cid==RIDER:kw.update(keywords=(Keyword.COMBO,),combo=PREFIX+'rider')
        if cid==RAIDER:kw['triggers']=(TriggerSpec('hero_power_used',PREFIX+'raider'),)
        if cid in(SONG,EMP,HEMET):kw['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,))
        if cid in(WATCHER,ALCHEMIST):kw['targeting']=TargetSpec(TargetMode.IF_AVAILABLE)
        if cid in(EMP,HEMET):kw['target_rule']=PREFIX+('mech'if cid==EMP else'beast')
        definition=CardDefinition(cid,raw['name'],CardType.SPELL if cid==APPLE else CardType.MINION,cost=raw['cost'],
            attack=0 if cid==APPLE else raw['attack'],health=0 if cid==APPLE else raw['health'],metadata=metadata_from_record(raw),**kw)
        registry.register_card(definition)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
