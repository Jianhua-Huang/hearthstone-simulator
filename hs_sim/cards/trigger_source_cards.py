"""Real spell/draw/shield sources composed over original facts and public effects."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.draw_casts import draw_record
from hs_sim.engine.effects import InvokeBehavior,RandomDamageBatch
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,DamageKind,Keyword,TriggerSpec,Zone
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/trigger-source-effects-v1.json'
BATCH_HASH='3a42c233311f596cf78a2f6168c0511ad718eff8fa9670764105fc8bd4c4f60c'
PREFIX='cards.trigger_source.'
EVENTS=dict(cho='spell_cast_started',cold='card_played',alabaster='card_drawn',bolvar='shield_lost',
    eredar='card_drawn',moonwell='card_played')


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Real trigger-source pin changed')
    return value


def register_trigger_source_cards(registry):
    def cho(c):
        record=cast_record(c.state,dict(c.event.data)['cast_id'])
        if(record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Cho lost the original spell start')
        if record.origin!='hand':return ()
        source=c.state.entities[record.source_id]
        if source.card_id!=record.card_id or source.kind!=CardType.SPELL:raise ResolutionError('Cho lost the original spell face')
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,source),3-record.player_id,mode='base',source_id=c.source_id),)
    def personal(c):
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if not record.completed or(record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id):
            raise ResolutionError('Trigger source lost its original completed play')
        return record if record.player_id==c.player_id and record.kind==CardType.SPELL and not record.countered else None
    def physical_draw(c):
        record=draw_record(c.state,dict(c.event.data)['draw_id'])
        if(record.entity_id,record.player_id)!=(c.event.target_id,c.event.player_id)or record.outcome not in('hand','cast'):
            raise ResolutionError('Trigger source lost its original physical draw')
        source=c.state.entities[record.entity_id]
        return record,source
    def alabaster(c):
        record,source=physical_draw(c)
        if record.player_id==c.player_id:return ()
        if source.card_id!=record.card_id or source.controller!=record.player_id:
            raise ResolutionError('Original drawn face changed without a supported copy policy')
        material=CapturedCardCopyMaterial.capture(c.state,source)
        return(CopyCard(material,c.player_id,mode='current'if record.outcome=='hand'else'base',
            source_id=c.source_id,cost=CostSpec(set_to=1)),)
    def eredar(c):
        record,_=physical_draw(c)
        return(SummonByCard(c.player_id,(SummonEntryMaterial('TTN_843t1'),),SummonCause.capture(c)),)if record.player_id==c.player_id else()
    def bolvar(c):
        target=c.state.entities[c.event.target_id]
        return(RandomBuffStoredMinion(c.player_id,5,5,source_id=c.source_id),)if target.kind==CardType.MINION and target.controller==c.player_id else()
    def moonwell(c):
        record=personal(c)
        return(BuffCapturedMinion(MinionReference.capture(c.source),record.cost,0,c.source_id),)if record and record.cost else()
    bodies=dict(cho=cho,cold=lambda c:(InvokeBehavior(PREFIX+'cold_current',c.source_id,c.player_id),)if personal(c)else(),
        cold_current=lambda c:(RandomDamageBatch(characters(c,registry,3-c.player_id),2,1,c.source_id,DamageKind.MINION_ABILITY),),
        alabaster=alabaster,bolvar=bolvar,eredar=eredar,moonwell=moonwell)
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if(canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']!=recipe['root']or
                (raw['cost'],raw['attack']or 0,raw['health'])!=(recipe['cost'],recipe['attack'],recipe['health'])):
            raise TargetValidationError('Unreviewed real trigger source face')
        if script not in EVENTS and script!='felbat':raise TargetValidationError('Unknown trigger-source body')
        triggers=()if script=='felbat'else(TriggerSpec(EVENTS[script],PREFIX+script),)
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],health=recipe['health'],
            keywords=tuple(Keyword(k)for k in recipe['keywords']),triggers=triggers,
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']))
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
