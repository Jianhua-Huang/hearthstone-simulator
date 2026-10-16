"""Native real trigger cards over frozen play/cast/health/death/power facts."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.dormancy import AwakenCapturedMinion
from hs_sim.engine.effects import AddToHand,Damage,DamageBatch,Draw,GainArmor,InvokeBehavior,RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,HealthFlow,Keyword,TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.tribes import apply_change,has_any_tribe,normalized
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/reactive-growth-effects-v1.json'
BATCH_HASH='dd86a326c34e2e918c8d817ebd2c53531428420f468b42e87f50dc61a000afeb'
PREFIX='cards.reactive_growth.'
EVENTS=dict(tidecaller='minion_summoned',antonidas='spell_cast_started',frothing='health_resolved',micro='turn_started',
    pyromancer='card_played',acolyte='minion_died',vapor='card_played',barkshield='hero_power_used',
    tortolla='health_resolved',carnivorous='minion_died',dragonbane='hero_power_used',dryad='hero_power_used')


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Reactive-growth reviewed source pin changed')
    return value


def buff_source(c,attack=0,health=0):
    return BuffCapturedMinion(MinionReference.capture(c.source),attack,health,c.source_id)


def register_reactive_growth_cards(registry):
    batch=load_batch();dependency=batch['reused_dependencies'][0];fire=dependency['record']
    if (canonical_digest(fire)!=dependency['record_sha256']or fire['dbf_id']!=315 or fire['id']!='CS2_029' or
            registry.card(fire['id']).kind!=CardType.SPELL or registry.card(fire['id']).cost!=fire['cost']):
        raise TargetValidationError('Antonidas lost its named complete Fireball315 dependency')
    def tidecaller(c):
        if c.event.player_id!=c.player_id or c.event.target_id==c.source_id:return ()
        target=c.state.entities[c.event.target_id]
        return (buff_source(c,1),)if target.kind==CardType.MINION and has_any_tribe(registry,target,('murloc',))else()
    def antonidas(c):
        record=cast_record(c.state,dict(c.event.data)['cast_id'])
        if (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Antonidas lost its original actual cast start')
        return (AddToHand(c.player_id,fire['id'],c.source_id),)if record.player_id==c.player_id and record.origin=='hand' else()
    def completed_spell(c):
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if (not record.completed or
                (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id)):
            raise ResolutionError('Reactive spell trigger lost its original completed paid play')
        return record.player_id==c.player_id and record.kind==CardType.SPELL and not record.countered
    def pyromancer(c):
        return (InvokeBehavior(PREFIX+'pyromancer_current',c.source_id,c.player_id),)if completed_spell(c)else()
    def pyromancer_current(c):
        return (DamageBatch(tuple(Damage(eid,1,c.source_id,DamageKind.MINION_ABILITY)
            for pid in (1,2)for eid in minions(c,registry,pid))),)
    def health(c):
        result=c.health_result
        if result is None:raise ResolutionError('Reactive damage trigger requires its original health result')
        return result
    def frothing(c):
        result=health(c)
        return (buff_source(c,1),)if result.flow==HealthFlow.DAMAGE.value and result.damage_dealt>0 and result.target_kind==CardType.MINION.value else()
    def tortolla(c):
        result=health(c)
        if result.target_id!=c.source_id or result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0:return ()
        return (GainArmor(c.player_id,1),buff_source(c,1))
    def death(c):
        death_id=dict(c.event.data)['death_id']
        record=next((r for r in c.state.death_history if r.id==death_id),None)
        if record is None or (record.entity_id,record.controller)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Reactive death trigger lost its original DeathRecord')
        return record
    def acolyte(c):
        record=death(c)
        return (Draw(c.player_id,source_id=c.source_id),)if record.controller==c.player_id and has_any_tribe(registry,record,('undead',))else()
    def carnivorous(c):
        record=death(c)
        return (buff_source(c,record.attack),)if record.attack>0 else()
    def vapor(c):
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if not record.completed or (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Vapor lost its original completed paid hand play')
        if record.player_id!=c.player_id or record.source_id==c.source_id or record.kind!=CardType.MINION:return ()
        if record.played_face is None or record.submitted_cost is None:raise ResolutionError('Vapor lost original submitted face/tribe operands')
        meta=record.played_face.metadata;tribes=None if meta is None or meta.tribes is None else normalized(meta.tribes)
        for enchantment in record.submitted_cost.quote.quote_input.enchantments:
            if enchantment.tribe_change is not None:tribes=apply_change(tribes,enchantment.tribe_change)
        if tribes is None:raise UnsupportedDefinitionError('Unknown submitted Elemental tribe identity')
        return (buff_source(c,1),)if tribes.matches_any(('elemental',))else()
    def dragonbane(c):
        return (InvokeBehavior(PREFIX+'dragonbane_current',c.source_id,c.player_id),)if is_inspire(c.state,c.event,c.player_id)else()
    def dryad(c):
        if not is_inspire(c.state,c.event,c.player_id)or c.source.dormancy is None:return ()
        return (AwakenCapturedMinion(MinionReference.capture(c.source),c.source.dormancy.id,c.source_id),)
    bodies=dict(tidecaller=tidecaller,antonidas=antonidas,frothing=frothing,micro=lambda c:(buff_source(c,1),),
        pyromancer=pyromancer,pyromancer_current=pyromancer_current,acolyte=acolyte,vapor=vapor,
        barkshield=lambda c:(buff_source(c,health=2),)if is_inspire(c.state,c.event,c.player_id)else(),tortolla=tortolla,
        carnivorous=carnivorous,dragonbane=dragonbane,dragonbane_current=lambda c:(RandomDamage(characters(c,registry,3-c.player_id),5,c.source_id,DamageKind.MINION_ABILITY),),dryad=dryad)
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if (canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']is not True or
                script not in EVENTS or any(raw[k]!=recipe[k]for k in ('cost','attack','health'))):
            raise TargetValidationError('Unreviewed native reactive card recipe')
        extra=dict(dormant_turns=None,dormant_triggers=(TriggerSpec(EVENTS[script],PREFIX+script),))if script=='dryad'else dict(triggers=(TriggerSpec(EVENTS[script],PREFIX+script),))
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],health=recipe['health'],
            keywords=tuple(Keyword(k)for k in recipe['keywords']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**extra)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
