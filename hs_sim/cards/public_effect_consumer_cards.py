"""Nine actual roots expressed by existing public effects and native entries."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.bonus_effects import GrantRandomBonusEffects
from hs_sim.engine.effects import CopyMinion,DestroyBatch,Draw,InvokeBehavior,SetStats
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,HandActionSpec,Keyword,
    KeywordAuraSpec,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import ReorderZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/public-effect-consumers-v1.json'
BATCH_HASH='5fcefe0bbf38cb4c704c9cd686ea378271b0889391f62eb96ca42260ba2fe302'
GEOMANCER='CATA_EVENT_401';LANCER='CATA_898';AMARA='TLC_835';STAFF='TLC_EVENT_402';DOUBLE='TIME_710'
ARACHNATHID='JAIL_459';SUPPLIER='CAP_003';GALVADON='TLC_444';CAUSALITY='TIME_061'
ROOTS=(GEOMANCER,LANCER,AMARA,STAFF,DOUBLE,ARACHNATHID,SUPPLIER,GALVADON,CAUSALITY)
PREFIX='cards.public_consumers.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Public effect consumers lost their complete source pin')
    return data


def register_public_effect_consumer_cards(registry):
    def destroy_all(c):
        targets=tuple(i for player in c.state.players.values()for i in player.board
            if c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active
            and c.state.entities[i].health>0 and not c.state.entities[i].doomed)
        return (DestroyBatch(targets,c.source_id),)
    def double(c):
        if c.source.kind!=CardType.MINION or c.source.zone!=Zone.BOARD:return ()
        return (CopyMinion(BoardPresenceReference.capture(c.state,c.source_id),c.player_id,cause=SummonCause.capture(c)),)
    def supplier(c):
        if c.event is None or c.event.kind!='attack_finished' or c.event.source_id!=c.source_id or not living_source(c):return ()
        row=completed_attack(c)
        if row is None or row.combat.player_id!=c.player_id:return ()
        return (Draw(c.player_id,source_id=c.source_id),)
    bodies={
        'amara':lambda c:(SetStats(c.state.players[c.player_id].hero_id,health=40,source_id=c.source_id),),
        'staff':destroy_all,'double':double,'supplier':supplier,
        'galvadon':lambda c:(GrantRandomBonusEffects(c.target_id,3,c.source_id),),
        'reverse':lambda c:(InvokeBehavior(PREFIX+'reverse_now',c.source_id,c.player_id),),
        'reverse_now':lambda c:(ReorderZone(c.player_id,Zone.DECK,tuple(reversed(c.state.players[c.player_id].deck))),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    data=load_batch()
    if tuple(row['record']['id']for row in data['cards'])!=ROOTS or data['dependencies']:
        raise TargetValidationError('Unreviewed public-effect consumer root/dependency set')
    for row in data['cards']:
        raw=row['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or not raw['collectible']:raise TargetValidationError('Incomplete public-effect consumer face')
        if cid==GEOMANCER:
            if raw['tags'].get('SPELLPOWER')!=1 or raw['tags'].get('DECK_ACTION_COST')!=1:raise TargetValidationError('Geomancer lost its actual spell bonus or Prepare action cost')
            kwargs.update(spell_damage=1,hand_actions=(HandActionSpec('prepare','prepare',1),))
        elif cid==LANCER:kwargs['keyword_auras']=(KeywordAuraSpec(Keyword.TAUNT,'enemy_minions'),)
        elif cid==AMARA:kwargs['on_play']=PREFIX+'amara'
        elif cid==STAFF:kwargs.update(deathrattle=PREFIX+'staff',durability=raw['health'])
        elif cid==DOUBLE:kwargs.update(keywords=(Keyword.STEALTH,Keyword.COMBO),combo=PREFIX+'double')
        elif cid==ARACHNATHID:kwargs.update(keywords=(Keyword.RUSH,),keyword_auras=(KeywordAuraSpec(Keyword.POISONOUS,'friendly_minions',include_self=True),))
        elif cid==SUPPLIER:kwargs.update(keywords=(Keyword.STEALTH,),triggers=(TriggerSpec('attack_finished',PREFIX+'supplier'),))
        elif cid==GALVADON:kwargs.update(on_play=PREFIX+'galvadon',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)))
        elif cid==CAUSALITY:kwargs['battlecry']=PREFIX+'reverse'
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,
            health=raw['health']if kind==CardType.MINION else 0,metadata=replace(metadata_from_record(raw),deck_identity=cid),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
