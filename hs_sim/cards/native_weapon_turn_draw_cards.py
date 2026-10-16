"""Native Lifesteal equipment, opponent-turn Attack and highest stored draw."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import (CardDefinition,CardType,Keyword,StatRelationLayer,StatRelationOperand,StatRelationSpec)
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/native-weapon-turn-draw-effects-v1.json'
BATCH_HASH='a4dc829418d65d5eb30773288d8b0ff6971e31f5dea7a114f1ac373eaa7bab05'
PREFIX='cards.native_weapon_turn_draw.'
SCRIPTS={'CORE_BT_921':'lifesteal_weapon','RLK_067':'lifesteal_weapon','CORE_UNG_928':'opponent_turn_attack','CS3_024':'highest_deck_minion'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(value)!=BATCH_HASH:
        raise TargetValidationError('Native weapon/turn/draw differs from its complete source pin')
    return value


def register_native_weapon_turn_draw_cards(registry):
    registry.register_behavior(PREFIX+'highest_deck_minion',lambda c:(DrawMatching(c.player_id,
        PoolQuery(kinds=(CardType.MINION,)),'skip',selection='highest_cost',source_id=c.source_id),))
    batch=load_batch()
    for row in batch['historical_identity_evidence']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Native weapon/turn/draw identity changed')
    for row in batch['cards']:
        raw,recipe=row['record'],row['recipe'];script=recipe['script'];kind=CardType(raw['type'].lower())
        if(canonical_digest(raw)!=row['record_sha256']or SCRIPTS.get(raw['id'])!=script or raw['collectible']is not True):
            raise TargetValidationError('Unreviewed native weapon/turn/draw face')
        kwargs={}
        if script=='lifesteal_weapon':
            if kind!=CardType.WEAPON or raw['tags'].get('LIFESTEAL')!=1:raise TargetValidationError('Native weapon Lifesteal required')
            kwargs['durability']=raw['health']
        elif script=='opponent_turn_attack':
            kwargs['stat_relations']=(StatRelationSpec(operand=StatRelationOperand.CONTROLLER_OPPONENT_TURN,
                layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=2),)
        elif script=='highest_deck_minion':kwargs['deathrattle']=PREFIX+script
        else:raise TargetValidationError('Unknown native weapon/turn/draw script')
        card=CardDefinition(raw['id'],raw['name'],kind,cost=raw['cost'],attack=raw['attack'],
            health=raw['health']if kind==CardType.MINION else 0,keywords=tuple(Keyword(k)for k in recipe['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
