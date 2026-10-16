"""Current Core independent play, cast, attack, recruit and adjacency bodies."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Damage,DamageBatch,Draw,Overload
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.healing_history import restored_health
from hs_sim.engine.model import (AuraSpec,CardDefinition,CardType,DamageKind,Keyword,SpellSchool,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.play_history import play_record
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/basic-trigger-effects-v1.json'
BATCH_HASH='80dd4a26bf926dc11f17af11af0096cb3225b341616e31160734e5865a19164d'
PREFIX='cards.basic_trigger.'
SCRIPTS={'CORE_AT_052':'totem','CORE_BAR_313':'anshe','CORE_BAR_878':'veteran',
         'CORE_BT_351':'battlefiend','CORE_BT_510':'wrathspike','CORE_CFM_790':'rat',
         'CORE_DMF_067':'vendor','CORE_EX1_162':'wolf'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Basic trigger cards differ from their complete reviewed source pin')
    return data


def register_basic_trigger_cards(registry):
    def veteran(c):
        record=play_record(c.state,dict(c.event.data)['play_id'])
        if (record.source_id,record.player_id)!=(c.event.source_id,c.event.player_id) or not record.completed:
            raise ResolutionError('Holy trigger lost its original completed paid play')
        if (record.player_id!=c.player_id or record.kind!=CardType.SPELL or record.countered or
                registry.card(record.card_id).spell_school!=SpellSchool.HOLY):
            return ()
        return (SummonByCard(c.player_id,(SummonEntryMaterial('BAR_878t'),),SummonCause.capture(c)),)

    def attack_record(c):
        row=next((row for row in c.state.character_attack_history if row.terminal is not None
            and row.terminal.status=='completed' and row.terminal.event_cursor+1==c.event.sequence),None)
        if row is None or row.declaration.source_id!=c.event.source_id or row.delivery.target_id!=c.event.target_id:
            raise ResolutionError('Native attack trigger lost its original completed attack')
        return row

    def battlefiend(c):
        row=attack_record(c)
        return (Buff(c.source_id,attack=1,source_id=c.source_id),) if (
            row.source_kind==CardType.HERO and row.declaration.player_id==c.player_id) else ()

    def wrathspike(c):
        attack_record(c)
        if c.event.target_id!=c.source_id:return ()
        return (DamageBatch(tuple(Damage(eid,1,c.source_id,DamageKind.MINION_ABILITY)
            for eid in characters(c,registry,3-c.player_id))),)

    bodies={
        'totem':lambda c:(Overload(c.player_id,1),),
        'anshe':lambda c:(Buff(c.source_id,3,3,c.source_id),)
            if restored_health(c.state,c.player_id,turn=c.state.turn)>0 else (),
        'veteran':veteran,'battlefiend':battlefiend,'wrathspike':wrathspike,
        'rat':lambda c:(SummonFromZone(3-c.player_id,zone=Zone.HAND,selection='random',
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'vendor':lambda c:tuple(Draw(pid,source_id=c.source_id) for pid in (c.player_id,3-c.player_id)),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe']
        if (canonical_digest(raw)!=row['record_sha256'] or raw['type']!='MINION'
                or (raw['cost'],raw['attack'],raw['health'],raw['collectible'])!=
                   (recipe['cost'],recipe['attack'],recipe['health'],recipe['root'])):
            raise TargetValidationError('Basic trigger card lost its reviewed complete face')
        kwargs={};script=recipe['script'];cid=raw['id']
        if script is not None and SCRIPTS.get(cid)!=script:
            raise TargetValidationError('Unreviewed basic native body')
        if cid=='CORE_AT_052':kwargs['on_play']=PREFIX+script
        elif cid in ('CORE_BAR_313','CORE_CFM_790','CORE_DMF_067'):
            kwargs['battlecry']=PREFIX+script
            if cid=='CORE_DMF_067':kwargs['deathrattle']=PREFIX+script
        elif cid in ('CORE_BAR_878','CORE_BT_351','CORE_BT_510'):
            kwargs['triggers']=(TriggerSpec('card_played' if cid=='CORE_BAR_878' else 'attack_finished',PREFIX+script),)
        elif cid=='CORE_EX1_162':kwargs['auras']=(AuraSpec(attack=1,adjacent_only=True),)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=recipe['cost'],attack=recipe['attack'],
            health=recipe['health'],keywords=tuple(Keyword(value) for value in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
