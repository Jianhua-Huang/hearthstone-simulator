"""Twilight Egg and Platysaur: complete real bodies using native attached memory."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.deathrattle_memory import GrowDeathrattleSummon,DrawForDeathrattle,DiscardRememberedDraw
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import CardDefinition,CardType,NativeDeathrattleSpec,SummonStats,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-deathrattle-memory-v1.json'
BATCH_HASH='224e227edd6d2271c19284ee24fd0c1373a4259e5e954bddd317e49e589f9a97'
PREFIX='cards.deathrattle_memory.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Native Deathrattle memory lost its complete reviewed source pin')
    return data


def memory(c,kind):
    value=None if c.deathrattle is None else c.deathrattle.ability.deathrattle_memory
    if value is None or value.spec.kind!=kind:
        raise UnsupportedDefinitionError('This Deathrattle source lacks its original typed native memory; unreviewed grants remain unsupported')
    return value


def register_native_deathrattle_memory_cards(registry):
    data=load_batch();rows={x['record']['id']:x for x in data['cards']+data['dependencies']}
    if set(rows)!={'CATA_210','CATA_210t','TLC_603'}:raise TargetValidationError('Unreviewed native Deathrattle source/dependency set')
    egg,token=rows['CATA_210']['record'],rows['CATA_210t']['record']
    if (egg['tags']['TAG_SCRIPT_DATA_NUM_1'],egg['tags']['TAG_SCRIPT_DATA_NUM_2'])!=(token['attack'],token['health']):
        raise TargetValidationError('Egg dynamic initial numbers lost their complete real token')
    def grow(c):
        if c.event.player_id!=c.player_id:return ()
        ref=MinionReference.capture(c.source)
        return tuple(GrowDeathrattleSummon(ref,a.id)for a in active_abilities(c.source,'deathrattle')
            if a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind=='summon_growth')
    def hatch(c):
        value=memory(c,'summon_growth');stats=SummonStats(value.spec.attack+value.growth_steps,value.spec.health+value.growth_steps)
        return(SummonByCard(c.player_id,(SummonEntryMaterial(value.spec.card_id,stats=stats),),SummonCause.capture(c)),)
    def draw(c):
        ids=tuple(a.id for a in active_abilities(c.source,'deathrattle')if a.deathrattle_memory is not None and a.deathrattle_memory.spec.kind=='draw_link')
        return(DrawForDeathrattle(c.player_id,MinionReference.capture(c.source),ids),)
    def discard(c):
        return tuple(DiscardRememberedDraw(c.deathrattle.id,x)for x in memory(c,'draw_link').draws)
    for name,body in dict(grow=grow,hatch=hatch,draw=draw,discard=discard).items():registry.register_behavior(PREFIX+name,body)
    for cid,item in rows.items():
        raw,recipe=item['record'],item['recipe']
        if canonical_digest(raw)!=item['record_sha256']or raw['type']!='MINION':raise TargetValidationError('Unreviewed full native Deathrattle face')
        kwargs={}
        if cid=='CATA_210':
            if recipe['script']!='summon_growth':raise TargetValidationError('Unreviewed Egg recipe')
            kwargs=dict(deathrattle=PREFIX+'hatch',native_deathrattle=NativeDeathrattleSpec('summon_growth',token['id'],token['attack'],token['health']),triggers=(TriggerSpec('turn_started',PREFIX+'grow'),))
        elif cid=='TLC_603':
            if recipe['script']!='draw_link':raise TargetValidationError('Unreviewed Platysaur recipe')
            kwargs=dict(battlecry=PREFIX+'draw',deathrattle=PREFIX+'discard',native_deathrattle=NativeDeathrattleSpec('draw_link'))
        elif recipe['script']!='plain' or raw['text_en']:raise TargetValidationError('Whelp must retain its entire plain face')
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
