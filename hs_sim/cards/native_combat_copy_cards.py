"""Real Saber freezes its original killed minion in the native attack window."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.zones import CopyCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .metadata import metadata_from_record

SABRE='TLC_247';PREFIX='cards.native_combat_copy.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-combat-copy-v1.json'
BATCH_HASH='469d91a14322735d3f10d2f59c7351e7d16ef2d6e3a90bc418561c59a6a6f21a'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Native combat copy lost its complete source pin')
    if tuple(x['record']['id']for x in data['cards'])!=(SABRE,)or data['dependencies']:
        raise TargetValidationError('Unreviewed native combat-copy source')
    for row in data['cards']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Native combat copy lost its complete original row')
    return data


def register_native_combat_copy_cards(registry):
    def sabre(c):
        row=completed_attack(c)
        if (row is None or row.declaration.source_id!=c.source_id or not living_source(c)or
                row.source_kind!=CardType.MINION or
                (c.source.zone_epoch,c.source.entered_order)!=(row.combat.source_zone_epoch,row.combat.source_entered_order)):
            return ()
        target=c.state.entities[row.delivery.target_id];cause=target.death_cause
        if (target.kind!=CardType.MINION or target.zone!=Zone.BOARD or
                target.health>0 and not target.doomed or cause is None or cause.kind not in('damage','poison')):
            return ()
        result=cause.health_result
        if (result is None or result.damage_kind!=DamageKind.COMBAT.value or result.source_id!=c.source_id or
                result.original_target_id!=target.id or
                (cause.target_card_id,cause.target_zone_epoch,cause.target_entered_order)!=(target.card_id,target.zone_epoch,target.entered_order)or
                (result.source_zone_epoch,result.source_entered_order)!=(row.combat.source_zone_epoch,row.combat.source_entered_order)or
                not row.combat.event_cursor<result.batch_id<=row.terminal.event_cursor):
            return ()
        return(CopyCard(CapturedCardCopyMaterial.capture(c.state,target),c.player_id,mode='base',source_id=c.source_id),)
    registry.register_behavior(PREFIX+'sabre',sabre)
    raw=load_batch()['cards'][0]['record']
    if (raw['type'],raw['collectible'],raw['cost'],raw['attack'],raw['health'],raw['tags'].get('STEALTH'))!=('MINION',True,4,5,3,1):
        raise TargetValidationError('Unreviewed native Saber face')
    card=CardDefinition(SABRE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
        keywords=(Keyword.STEALTH,),metadata=replace(metadata_from_record(raw),deck_identity=SABRE),
        triggers=(TriggerSpec('attack_finished',PREFIX+'sabre'),))
    registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
