"""Setesh composes owner history, exact program consumption and real armor loss."""
from dataclasses import asdict
import json
from pathlib import Path

from hs_sim.engine.effects import GainArmor, LoseArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition, CardType, PlayerEffectSpec, SummonStats, TriggerSpec
from hs_sim.engine.owner_turns import current_owner_turn
from hs_sim.engine.player_effects import AddPlayerEffect, ConsumePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

CARD,GOLEM='BE_557','BE_561t'
PROGRAM='cards.setesh.countdown'
BEGIN='cards.setesh.begin'
DEADLINE='cards.setesh.deadline'
CONVERT='cards.setesh.convert'
TURNS=2
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/setesh-v1.json'
BATCH_HASH='de5221b5970c33537a3fe27794d9afc359bd194d7f69742d2b01b6eebbd2ffd3'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=(CARD,) or
            tuple(x['record']['id'] for x in data['existing_dependencies'])!=(GOLEM,) or
            tuple(x['record']['id'] for x in data['evidence_only'])!=('BE_557e2',) or
            data['dependencies'] or data['skipped'] or data['official_faces_verified']!=4):
        raise TargetValidationError('Setesh requires its complete source, existing Golem and original delayed marker')
    for row in (*data['cards'],*data['existing_dependencies'],*data['evidence_only']):
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Setesh complete original source record changed')
    return data


def register_setesh_card(registry):
    data=load_batch();raw=data['cards'][0]['record']
    if canonical_digest(asdict(registry.card(GOLEM)))!=data['existing_definition_sha256'][GOLEM]:
        raise TargetValidationError('Setesh must reuse the complete existing Steel Golem definition')
    if (raw['type'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('BATTLECRY'),
            raw['tags'].get('TAG_SCRIPT_DATA_NUM_1'),raw['tags'].get('QUEST_PROGRESS_TOTAL'))!=('MINION',7,7,7,1,2,2):
        raise TargetValidationError('Setesh lost its actual seven-Mana 7/7 and two-turn source tags')
    def begin(c):
        if c.battlecry is None or c.battlecry.payload.card_id!=CARD:
            raise ResolutionError('Setesh requires its original actual Battlecry')
        return (GainArmor(c.player_id,20),AddPlayerEffect(c.player_id,PROGRAM,c.source_id))
    def deadline(c):
        if c.event is None or c.event.kind!='turn_started' or c.event.player_id!=c.player_id:return ()
        instance=c.player_effect
        if instance is None or instance.spec_id!=PROGRAM or instance.source_id!=c.source_id:
            raise ResolutionError('Setesh lost its original delayed player instance')
        interval=current_owner_turn(c.state)
        if (interval.origin!='actual' or interval.turn!=dict(c.event.data).get('turn') or
                interval.publication_event not in (None,c.event.sequence) or c.event.sequence<=interval.start_event):
            return ()
        original=max((row.owner_index for row in c.state.owner_turn_history
            if row.player_id==c.player_id and row.turn<=instance.created_turn),default=0)
        if interval.owner_index-original<TURNS:return ()
        return (ConsumePlayerEffect(c.player_id,instance,
            (LoseArmor(c.player_id,source_id=instance.source_id,on_result=CONVERT),)),)
    def convert(c):
        result=c.armor_result
        if (result is None or result.requested is not None or c.event.kind!='armor_loss_resolved' or
                (c.event.source_id,result.player_id,result.hero_id)!=(c.source_id,c.player_id,c.target_id)):
            raise ResolutionError('Setesh requires its actual original all-Armor loss result')
        return (SummonByCard(c.player_id,(SummonEntryMaterial(GOLEM,
            stats=SummonStats(result.actual,result.actual)),),SummonCause.capture(c)),)
    for behavior,body in ((BEGIN,begin),(DEADLINE,deadline),(CONVERT,convert)):
        registry.register_behavior(behavior,body)
    registry.register_player_effect(PlayerEffectSpec(PROGRAM,CARD,triggers=(TriggerSpec('turn_started',DEADLINE),)))
    card=CardDefinition(CARD,raw['name'],CardType.MINION,cost=7,attack=7,health=7,
        battlecry=BEGIN,metadata=metadata_from_record(raw))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
