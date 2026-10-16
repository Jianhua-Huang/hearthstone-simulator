"""Actual next-Murloc price/reward and next-owner-turn card taxes."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.effects import AddCostModifier, Damage, DamageBatch
from hs_sim.engine.model import (CardDefinition, CardType, CostSpec, DamageKind,
    Keyword, PlayerEffectSpec, TriggerSpec)
from hs_sim.engine.owner_turns import query_for_definition, query_previous_owner_turn
from hs_sim.engine.player_effects import AddPlayerEffect, RemovePlayerEffect
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/next-play-price-effects-v1.json'
BATCH_HASH='1c7b6c40abc752820fe8a8514809eae24f5e40b571c628009a30534d637f297e'
PREFIX='cards.next_play_prices.'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:
        raise TargetValidationError('Next-play prices lost their complete reviewed source pin')
    return data


def register_next_play_price_cards(registry):
    def glider(c):
        matched=query_previous_owner_turn(c.state,c.player_id,
            query_for_definition(registry.card('TLC_428'))).matched
        return(AddCostModifier(c.player_id,CostSpec(delta=-1,card_types=(CardType.MINION,)),
            uses_remaining=1,source_id=c.source_id,tribes_any=('murloc',),
            minion_keyword=Keyword.DIVINE_SHIELD if matched else None),)

    def arm(c,name):
        return AddPlayerEffect(3-c.player_id,PREFIX+'pending_'+name,c.source_id)

    def activate(c,amount,minion_only):
        if c.event.player_id!=c.player_id:
            return()
        spec=CostSpec(delta=amount,card_types=(CardType.MINION,))if minion_only else CostSpec(delta=amount)
        return(RemovePlayerEffect(c.player_id,c.player_effect.id),
            AddCostModifier(c.player_id,spec,source_id=c.source_id,expires_turn=c.state.turn))

    registry.register_behavior(PREFIX+'glider',glider)
    registry.register_behavior(PREFIX+'slow',lambda c:(arm(c,'slow'),))
    registry.register_behavior(PREFIX+'tar',lambda c:(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.SPELL)
        for i in minions(c,registry,3-c.player_id))),arm(c,'tar')))
    registry.register_behavior(PREFIX+'activate_slow',lambda c:activate(c,1,False))
    registry.register_behavior(PREFIX+'activate_tar',lambda c:activate(c,2,True))
    rows=load_batch()['cards']
    if [x['record']['id']for x in rows]!=['TLC_428','TIME_716','TLC_439']:
        raise TargetValidationError('Unreviewed next-play price identities')
    for row in rows:
        raw,recipe=row['record'],row['recipe']
        if canonical_digest(raw)!=row['record_sha256']or not raw['collectible']:
            raise TargetValidationError('Unreviewed next-play price face')
        body={'TLC_428':'glider','TIME_716':'slow','TLC_439':'tar'}[raw['id']]
        kwargs={'battlecry':PREFIX+body}if body=='glider'else{'on_play':PREFIX+body}
        card=CardDefinition(raw['id'],raw['name'],CardType[raw['type']],cost=raw['cost'],
            attack=raw['attack']or 0,health=raw['health']or 0,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    for cid,name in [('TIME_716','slow'),('TLC_439','tar')]:
        registry.register_player_effect(PlayerEffectSpec(PREFIX+'pending_'+name,cid,
            triggers=(TriggerSpec('turn_started',PREFIX+'activate_'+name),)))
