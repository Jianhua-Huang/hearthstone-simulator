"""Actual Armor/spell/attack notifications and a native three-start sleeper."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.forced_attack_sequences import AttackRandomEnemyMinion
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,DamageKind,Keyword,TriggerSpec
from hs_sim.engine.play_history import play_record
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/beast-trigger-native-effects-v1.json'
BATCH_HASH='11eb67cae5ed947541a2b92453b71b444bdbae48965de971df3c55a4d4e95c75'
PREFIX='cards.beast_trigger.'

def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:raise TargetValidationError('Real Beast trigger recipes lost their complete reviewed source pin')
    return value

def basher(c):
    event=c.event
    if event is None or event.kind!='armor_gained':raise ResolutionError('Basher requires its original armor notification')
    if event.player_id!=c.player_id or event.target_id!=c.state.players[c.player_id].hero_id or event.amount<=0 or not living_source(c):return ()
    return(BuffCapturedMinion(MinionReference.capture(c.source),2,2,c.source_id),
        AttackRandomEnemyMinion(BoardPresenceReference.capture(c.state,c.source_id),c.player_id,c.source_id))

def thresher(c):
    if c.event is None or c.event.kind!='card_played':raise ResolutionError('Thresher requires its original completed physical play')
    row=play_record(c.state,dict(c.event.data)['play_id'])
    if not row.completed or(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id):
        raise ResolutionError('Thresher lost its original completed hand play')
    if row.player_id!=c.player_id or row.kind!=CardType.SPELL or row.countered or not living_source(c):return ()
    return(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.DIVINE_SHIELD,c.source_id),)

def tunneler(c):
    row=completed_attack(c)
    if row is None or row.declaration.source_id!=c.source_id or not living_source(c):return ()
    return(Damage(c.state.players[3-c.player_id].hero_id,2,c.source_id,DamageKind.MINION_ABILITY),)

def register_beast_trigger_native_cards(registry):
    data=load_batch();events={'basher':'armor_gained','thresher':'card_played','tunneler':'attack_finished'}
    for name,body in[('basher',basher),('thresher',thresher),('tunneler',tunneler)]:registry.register_behavior(PREFIX+name,body)
    for row in data['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script']
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or not raw['collectible']or script not in(*events,'patriarch'):
            raise TargetValidationError('Unreviewed complete Beast trigger face')
        kwargs={'dormant_turns':3}if script=='patriarch'else{'triggers':(TriggerSpec(events[script],PREFIX+script),)}
        if script=='patriarch'and recipe['dormant_turns']!=3:raise TargetValidationError('Patriarch lost its reviewed three-start sleep')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=tuple(Keyword(k)for k in recipe['keywords']),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
