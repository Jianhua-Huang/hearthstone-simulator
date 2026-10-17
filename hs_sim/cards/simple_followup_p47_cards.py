"""Reviewed native summons, current-deck/history consumers and private deck look."""
import json
from pathlib import Path

from hs_sim.engine.deck_conditions import CheckDeckCondition, DeckCondition
from hs_sim.engine.effects import Damage, Heal, SetStats
from hs_sim.engine.model import (CardClass, CardDefinition, CardType, CastWhenDrawnSpec,
    CostSpec, DamageKind, HandActionSpec, Keyword, RewindSpec, TargetSpec, Zone)
from hs_sim.engine.pools import GenerateFromPool, PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position, minions
from .recruit_cards import shuffle

BATCH_PATH = Path(__file__).resolve().parents[2] / 'data/cards/simple-followup-p47-v1.json'
BATCH_HASH = '50eff4bf2f0e57bfc6c016709d79234f91bc66ac19c5c48cd7965614ad71d392'
SENTRY='JAIL_035'; CHEF='JAIL_507'; SOOTHSAYER='JAIL_912'; TRIPWIRE='JAIL_879'
CLOCK='TIME_038'; BRUISER='JAIL_328'; STARSURGE='EDR_941'; JUDGMENT='JAIL_326'; EYES='TLC_521'
ROOTS=(SENTRY,CHEF,SOOTHSAYER,TRIPWIRE,CLOCK,BRUISER,STARSURGE,JUDGMENT,EYES)
DEPENDENCIES=('JAIL_879t',); SKIPPED=('TIME_019',); POOL_ID='constructed.cards'
PREFIX='cards.simple_followup_p47.'
NO_NEUTRAL=DeckCondition(scope='current',predicate='no_neutral')

def minion_query(cost=None, **kwargs):
    return PoolQuery(kinds=(CardType.MINION,),collectible=True,
        **({} if cost is None else dict(min_cost=cost,max_cost=cost)),**kwargs)

def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=ROOTS
            or tuple(x['record']['id'] for x in data['dependencies'])!=DEPENDENCIES
            or tuple(x['record']['id'] for x in data['skipped'])!=SKIPPED):
        raise TargetValidationError('P47 reviewed complete recipe set changed')
    for row in data['cards']+data['dependencies']+data['skipped']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('P47 complete original source row changed')
    return data

def register_simple_followup_p47_cards(registry):
    def summon(c, query, position=None):
        return SummonFromPool(c.player_id,POOL_ID,query,source_id=c.source_id,
            cause=SummonCause.capture(c),position=position)
    def sentry(c):
        one=SummonByCard(c.player_id,(SummonEntryMaterial(SENTRY),),SummonCause.capture(c))
        return (CheckDeckCondition(c.player_id,NO_NEUTRAL,(one,one)),)
    def chef(c):
        return (summon(c,minion_query(6 if c.state.players[c.player_id].max_mana>=10 else 2,
            keywords_all=(Keyword.TAUNT,))),)
    def soothsayer(c):
        return (Heal(c.state.players[c.player_id].hero_id,6,c.source_id),
            summon(c,minion_query(6),deathrattle_position(c)))
    def tripwire(c):
        return (summon(c,minion_query(5,tribes_any=('beast',))),*shuffle(c,DEPENDENCIES[0],2))
    def token(c):
        return (summon(c,minion_query(5,tribes_any=('beast',))),)
    def clock(c):
        from hs_sim.engine.model import Rarity
        return (GenerateFromPool(c.player_id,POOL_ID,minion_query(rarities=(Rarity.LEGENDARY,)),
            count=2,source_id=c.source_id,destination='board',cause=SummonCause.capture(c)),)
    def bruiser(c):
        get=GenerateFromPool(c.player_id,POOL_ID,PoolQuery(collectible=True,
            class_mode='specified',classes=(CardClass.PALADIN,),include_neutral=False),
            source_id=c.source_id,cost=CostSpec(delta=-2))
        return (CheckDeckCondition(c.player_id,NO_NEUTRAL,(get,)),)
    def starsurge(c):
        deaths=sum(d.controller==c.player_id and registry.card(d.card_id).kind==CardType.MINION
            for d in c.state.death_history)
        return (Damage(c.target_id,1+deaths,c.source_id,DamageKind.SPELL),)
    def judgment(c):
        selected=c.state.entities[c.target_id]
        attack,health=selected.attack,selected.health
        return tuple(SetStats(i,attack,health,c.source_id)
            for p in (1,2) for i in minions(c,registry,p))
    def eyes(c):
        return (ChooseFromZone(c.player_id,3-c.player_id,Zone.DECK,operation='top',
            sample_size=3,distinct='entity',source_id=c.source_id,prompt='选择一张牌置于对手牌库顶'),)
    bodies=dict(zip(ROOTS,(sentry,chef,soothsayer,tripwire,clock,bruiser,starsurge,judgment,eyes)))
    bodies[DEPENDENCIES[0]]=token
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for row in load_batch()['cards']+load_batch()['dependencies']:
        raw=row['record'];cid=raw['id'];kwargs={};kind=CardType(raw['type'].lower())
        if cid in (SOOTHSAYER,BRUISER):kwargs['deathrattle']=PREFIX+cid
        elif kind==CardType.MINION:kwargs['battlecry']=PREFIX+cid
        else:kwargs['on_play']=PREFIX+cid
        if cid in (SENTRY,SOOTHSAYER):kwargs['keywords']=(Keyword.TAUNT,)
        if cid in (SOOTHSAYER,JUDGMENT):kwargs['hand_actions']=(HandActionSpec('prepare','prepare',1),)
        if cid==CLOCK:kwargs.update(keywords=(Keyword.REWIND,),rewind=RewindSpec(retries=3))
        if cid==DEPENDENCIES[0]:kwargs.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        if cid in (STARSURGE,JUDGMENT):kwargs['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),
            relation='friendly' if cid==JUDGMENT else 'any')
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack'] or 0,
            health=raw['health'] or 0,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),
            metadata=metadata_from_record(raw),**kwargs)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
