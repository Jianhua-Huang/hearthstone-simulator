"""Native sequential missiles and single random minion ability hits."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import InvokeBehavior,RandomDamage,SplitDamage
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,EndTurnSpec,Keyword,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-random-damage-effects-v1.json'
BATCH_HASH='9441d3ea091d4e64686a03661517942fdfe414f5c354e180a1e53098a372d57c'
PREFIX='cards.native_random_damage.'
SCRIPTS={'CORE_EX1_082':'bomber','CORE_BT_493':'priestess','CORE_YOP_034':'blackwing','RLK_223':'thassarian'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:
        raise TargetValidationError('Native random damage differs from its complete reviewed pin')
    return value


def register_native_random_damage_cards(registry):
    def invoke(c,name):return InvokeBehavior(PREFIX+name,c.source_id,c.player_id)
    bodies=dict(
        bomber=lambda c:tuple(invoke(c,'bomber_current')for _ in range(3)),
        bomber_current=lambda c:(RandomDamage(tuple(i for p in(1,2)for i in characters(c,registry,p)
            if i!=c.source_id),1,c.source_id,DamageKind.MINION_ABILITY),),
        priestess=lambda c:(invoke(c,'priestess_current'),),
        priestess_current=lambda c:(SplitDamage(3-c.player_id,6,c.source_id,kind=DamageKind.MINION_ABILITY),),
        blackwing=lambda c:(invoke(c,'blackwing_current'),),
        blackwing_current=lambda c:(RandomDamage(minions(c,registry,3-c.player_id),10,c.source_id,DamageKind.MINION_ABILITY),),
        thassarian=lambda c:(invoke(c,'thassarian_current'),),
        thassarian_current=lambda c:(RandomDamage(characters(c,registry,3-c.player_id),2,c.source_id,DamageKind.MINION_ABILITY),))
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    batch=load_batch()
    for row in batch['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Native random identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe']
        if(canonical_digest(raw)!=row['record_sha256']or raw['type']!='MINION'or raw['collectible']is not True
                or SCRIPTS.get(raw['id'])!=recipe['script']):
            raise TargetValidationError('Unreviewed native random damage card')
        kwargs={};body=PREFIX+recipe['script']
        for entry in recipe['entries']:
            if entry in('battlecry','deathrattle'):kwargs[entry]=body
            elif entry=='controller_end':kwargs['triggers']=(TriggerSpec('turn_ended',body,EndTurnSpec()),)
            else:raise TargetValidationError('Unreviewed native random damage entry')
        card=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
