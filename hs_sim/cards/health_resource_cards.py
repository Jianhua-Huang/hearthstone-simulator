"""Real conditional hand quotes, armor followups and native spell Lifesteal."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import (Damage,DamageBatch,Destroy,GainArmor,InvokeBehavior,
    RandomDamage,RefreshHeroPower)
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.owner_turns import query_for_definition,query_previous_owner_turn
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/conditional-health-resource-v1.json'
BATCH_HASH='29f03baf0a3798a840b8997ba03f73d8c8d91b4e97c31de1c623950afeef02f8'
PREFIX='cards.health_resource.'
SCRIPTS={'FIR_923':'ragnaros_fire','TIME_750':'advance','TLC_620':'fortify',
    'TLC_447':'ablating','JAIL_441':'blood','RLK_024':'death_strike'}


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if canonical_digest(data)!=BATCH_HASH:raise TargetValidationError('Health/resource cards lost their complete reviewed pin')
    return data


def invoke(c,name):
    return InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id)


def held_at_least(c,registry,amount,*,minion_only=False):
    costs=tuple(quote_unselected_cost(c.state,registry,e).amount
        for eid in c.state.players[c.player_id].hand for e in(c.state.entities[eid],)
        if not minion_only or e.kind==CardType.MINION)
    return any(cost>=amount for cost in costs)


def register_health_resource_cards(registry):
    def ragnaros_fire(c):
        amount=8 if held_at_least(c,registry,8)else 4
        ids=minions(c,registry,3-c.player_id)
        return (RandomDamage(ids,amount,c.source_id,DamageKind.SPELL),)if ids else ()
    def advance_draw(c):
        return (DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,)),'skip',source_id=c.source_id),)if held_at_least(c,registry,5,minion_only=True)else ()
    def fortify_hit(c):
        armor=c.state.entities[c.state.players[c.player_id].hero_id].armor
        return (Damage(c.target_id,armor,c.source_id,DamageKind.SPELL),)
    def ablating(c):
        match=query_previous_owner_turn(c.state,c.player_id,query_for_definition(registry.card('TLC_447')))
        return (Destroy(c.target_id,c.source_id),*((invoke(c,'ablating_wave'),)if match.matched else ()))
    def ablating_wave(c):
        return (DamageBatch(tuple(Damage(eid,2,c.source_id,DamageKind.SPELL)
            for player in(1,2)for eid in minions(c,registry,player))),)
    def blood_refresh(c):
        return (RefreshHeroPower(c.player_id),)if c.state.players[c.player_id].hero_power_id is not None else ()
    bodies=dict(ragnaros_fire=ragnaros_fire,
        advance=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),invoke(c,'advance_draw')),
        advance_draw=advance_draw,
        fortify=lambda c:(GainArmor(c.player_id,3),invoke(c,'fortify_hit')),fortify_hit=fortify_hit,
        ablating=ablating,ablating_wave=ablating_wave,
        blood=lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.SPELL),invoke(c,'blood_refresh')),
        blood_refresh=blood_refresh,
        death_strike=lambda c:(Damage(c.target_id,6,c.source_id,DamageKind.SPELL),))
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for row in load_batch()['cards']:
        raw,recipe=row['record'],row['recipe'];kwargs={}
        if canonical_digest(raw)!=row['record_sha256']or raw['type']!='SPELL'or raw['collectible']is not True or SCRIPTS.get(raw['id'])!=recipe['script']:
            raise TargetValidationError('Health/resource recipe lost its complete reviewed spell face')
        target=recipe['target']
        if target in('minion','enemy_minion'):
            kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'if target=='enemy_minion'else'any')
        elif target=='character':
            kwargs['targeting']=TargetSpec(TargetMode.REQUIRED,zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION))
        elif target is not None:raise TargetValidationError('Unknown health/resource target domain')
        school=raw['tags'].get('SPELL_SCHOOL')
        if school is not None and school not in SCHOOLS:raise TargetValidationError('Unknown health/resource spell school')
        card=CardDefinition(raw['id'],raw['name'],CardType.SPELL,cost=raw['cost'],
            keywords=(Keyword.LIFESTEAL,)if raw['tags'].get('LIFESTEAL')==1 else (),
            spell_school=SCHOOLS.get(school),metadata=replace(metadata_from_record(raw),deck_identity=recipe['deck_identity']),
            on_play=PREFIX+recipe['script'],**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
