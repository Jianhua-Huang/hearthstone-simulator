"""Reviewed current-presence prices and existing passive cost consumers."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.model import (CardDefinition,CardType,CostAuraSpec,CostSpec,HandActionSpec,
    IntrinsicCostSpec,Keyword,PaymentType,PlayerPlayedClassCostSpec,PlayerWeaponAttackCostSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/presence-cost-effects-v1.json'
BATCH_HASH='38fa66fd699a520a93634d5ebbefbd4b3b4d7857766b197ce6ff5f5be93d2c23'
PRESENCE={
 'hand_other_dragon':IntrinsicCostSpec(delta=-3,condition='hand_other_dragon',history_profile_id='hand.current-other-dragon-v1'),
 'board_dormant_minion':IntrinsicCostSpec(delta=-4,condition='board_dormant_minion',history_profile_id='board.current-dormant-minion-v1'),
 'turn_holy_and_shadow':IntrinsicCostSpec(set_to=1,condition='turn_holy_and_shadow',history_profile_id='cast.current-turn-holy-shadow-v1'),
}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Presence cost content differs from its reviewed source pin')
    return data


def register_presence_cost_cards(registry):
    for row in load_batch()['cards']:
        raw,spec=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']:raise TargetValidationError('Presence cost record changed')
        if raw['type']!='MINION' or raw['collectible'] is not True or type(raw['cost']) is not int:
            raise TargetValidationError('Presence batch requires explicit complete collectible minions')
        profile=spec['profile'];kwargs={}
        if profile in PRESENCE:kwargs['intrinsic_costs']=(PRESENCE[profile],)
        elif profile=='last_play':kwargs['player_played_class_cost']=PlayerPlayedClassCostSpec(None,'cost.player-last-played-cost-v1')
        elif profile=='weapon_attack':kwargs['player_weapon_attack_cost']=PlayerWeaponAttackCostSpec()
        elif profile=='corpses':kwargs['cost_payment']=PaymentType.CORPSES
        elif profile=='all_minion_aura':
            # This full reviewed row has the Prepare text/DECK_ACTION_COST, but no PREPARE main tag.
            if raw['tags'].get('DECK_ACTION_COST')!=1:raise TargetValidationError('Prepare requires its original action cost')
            kwargs['hand_actions']=(HandActionSpec('prepare','prepare',1),)
            kwargs['cost_auras']=(CostAuraSpec(CostSpec(delta=2,card_types=(CardType.MINION,)),relation='any'),)
        else:raise TargetValidationError('Unreviewed passive cost profile')
        definition=CardDefinition(raw['id'],raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            keywords=tuple(Keyword(k) for k in spec['keywords']),
            metadata=replace(metadata_from_record(raw),deck_identity=spec['deck_identity']),**kwargs)
        registry.register_card(definition);registry.register_pool_card(PoolCard.from_definition(definition))
