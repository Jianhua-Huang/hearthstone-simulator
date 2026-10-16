"""Original attacking beneficiaries and the real three-zone growing carrier."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import CardDefinition,CardType,EndTurnSpec,HandProgressSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference,SetCapturedMinionStats
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/stored-growth-native-effects-v1.json'
BATCH_HASH='690f8bd6a5e60f8e536b107e8946355c69e55e99a77f5e1df893cd9b3c96ef45'
PREFIX='cards.stored_growth.'

def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Stored-growth native recipes lost their complete reviewed pin')
    return value

def archaios(c):
    if c.event is None or c.event.kind!='attack_declared':raise ResolutionError('Archaios requires its original attack declaration')
    if c.event.player_id!=c.player_id or c.event.source_id==c.source_id or not living_source(c):return ()
    window_id=dict(c.event.data)['window_id']
    rows=[x for x in c.state.character_attack_history if x.declaration.id==window_id]
    if len(rows)!=1:raise ResolutionError('Archaios lost the original character attack')
    row=rows[0]
    if(row.declaration.source_id,row.declaration.player_id,row.declaration_event_cursor+1)!=(c.event.source_id,c.event.player_id,c.event.sequence):
        raise ResolutionError('Archaios borrowed another attack window')
    if row.source_kind!=CardType.MINION:return ()
    target=c.state.entities[row.declaration.source_id]
    if target.controller!=c.player_id or target.zone!=Zone.BOARD or not target.active or target.health<=0 or target.doomed:return ()
    return(SetCapturedMinionStats(MinionReference.capture(target),health=c.source.health,source_id=c.source_id),)

def register_stored_growth_native_cards(registry):
    data=load_batch();rows={x['record']['id']:x for x in data['cards']}
    if set(rows)!={'TLC_811','TLC_827'}:raise TargetValidationError('Unreviewed stored-growth family')
    registry.register_behavior(PREFIX+'archaios',archaios)
    registry.register_trigger_condition(PREFIX+'own_end',lambda c:c.event is not None and c.event.player_id==c.player_id)
    registry.register_behavior(PREFIX+'board',lambda c:(BuffCapturedMinion(MinionReference.capture(c.source),attack=1,source_id=c.source_id),))
    registry.register_behavior(PREFIX+'stored',lambda c:(BuffStoredCard(CardReference.capture(c.source),attack=1,source_id=c.source_id),))
    for cid,row in rows.items():
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']or recipe['attack']!=(raw['attack']or 0):
            raise TargetValidationError('Unreviewed complete stored-growth native face')
        kwargs={'triggers':(TriggerSpec('attack_declared',PREFIX+'archaios'),)}if cid=='TLC_811'else{
            'triggers':(TriggerSpec('turn_ended',PREFIX+'board',EndTurnSpec()),),
            'hand_progress':HandProgressSpec('event',1,on_complete=PREFIX+'stored',repeat=True,event='turn_ended',
                condition_id=PREFIX+'own_end',zone=(Zone.HAND,Zone.DECK))}
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=recipe['attack'],health=raw['health'],
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
