"""Actual Frontier consumers of original hands, decks, deaths and draw phases."""
import json
from pathlib import Path

from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import Damage, DestroyBatch, InvokeBehavior
from hs_sim.engine.model import (CardDefinition, CardType, CastWhenDrawnSpec,
    DamageKind, EndTurnSpec, Keyword, TriggerSpec, Zone)
from hs_sim.engine.pools import PoolCard, PoolQuery, SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery, Resurrect, SummonFromZone, death_candidates
from hs_sim.engine.zones import AddToDeck, CardReference, DiscardCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .health_cards import SCHOOLS
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOTS=('DAL_553','OG_042','OG_133','NEW1_030','ULD_304','TRL_541')
BLOOD='TRL_541t'
PREFIX='cards.frontier_zone_and_end.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/frontier-zone-and-end-v1.json'
BATCH_HASH='3ad231923d24910b7367f61aee86dc2a379936ed3b0582f24aceba5e06fb3703'


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    rows=value['cards']+value['dependencies']
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or
            tuple(x['record']['id']for x in value['cards'])!=ROOTS or
            tuple(x['record']['id']for x in value['dependencies'])!=(BLOOD,) or
            len(value['official_faces'])!=14 or value['formal_pool_complete']is not False or
            value['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Frontier zone/end consumers lost their complete source scope')
    return value


def register_frontier_zone_and_end(registry):
    value=load_batch();rows={x['record']['id']:x['record']for x in value['cards']+value['dependencies']}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Frontier consumers cannot replace existing native identities')

    def nzoth(c):
        query=DeathQuery(has_deathrattle=True,deathrattle_basis='printed')
        count=len(death_candidates(c.state,registry,c.player_id,query,c.source_id))
        return (Resurrect(c.player_id,count,query,source_id=c.source_id,cause=SummonCause.capture(c)),)

    def discard(c):
        return tuple(DiscardCard(CardReference.capture(c.state.entities[i]),c.source_id)
            for i in c.state.players[c.player_id].hand)

    def deathwing(c):
        targets=tuple(i for pid in (1,2)for i in minions(c,registry,pid)if i!=c.source_id)
        return (DestroyBatch(targets,c.source_id),InvokeBehavior(PREFIX+'discard',c.source_id,c.player_id))

    def phaoris(c):
        prices=tuple(quote_unselected_cost(c.state,registry,c.state.entities[i]).amount
            for i in c.state.players[c.player_id].hand if c.state.entities[i].kind==CardType.SPELL)
        cause=SummonCause.capture(c)
        return tuple(SummonFromPool(c.player_id,'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=cost,max_cost=cost),
            source_id=c.source_id,cause=cause)for cost in prices)

    def blood_after(c):
        row=c.draw
        if (row is None or row.card_id!=BLOOD or row.entity_id!=c.source_id or
                row.player_id!=c.player_id or row.phase!='after_draw' or row.outcome!='cast'):
            raise TargetValidationError('Corrupted Blood copies require their actual after-draw root')
        return tuple(AddToDeck(c.player_id,BLOOD,source_id=c.source_id)for _ in range(2))

    bodies={
        'DAL_553':lambda c:(SummonFromPool(c.player_id,'constructed.minions',
            PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=6,max_cost=6),
            source_id=c.source_id,cause=SummonCause.capture(c)),),
        'OG_042':lambda c:(SummonFromZone(c.player_id,source_id=c.source_id,cause=SummonCause.capture(c)),),
        'OG_133':nzoth,'NEW1_030':deathwing,'discard':discard,'ULD_304':phaoris,
        'TRL_541':lambda c:tuple(AddToDeck(pid,BLOOD,source_id=c.source_id)for pid in (1,2)),
        BLOOD:lambda c:(Damage(c.state.players[c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),),
        'blood_after':blood_after,
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for cid,raw in rows.items():
        kind=CardType(raw['type'].lower());fields={}
        if kind==CardType.MINION:fields.update(attack=raw['attack'],health=raw['health'])
        if cid in ('DAL_553','OG_042'):
            fields['triggers']=(TriggerSpec('turn_ended',PREFIX+cid,EndTurnSpec('controller')),)
        elif cid in ('OG_133','NEW1_030','ULD_304'):fields['battlecry']=PREFIX+cid
        elif cid=='TRL_541':fields['deathrattle']=PREFIX+cid
        else:fields.update(on_play=PREFIX+BLOOD,keywords=(Keyword.CASTS_WHEN_DRAWN,),
            cast_when_drawn=CastWhenDrawnSpec(after_draw=PREFIX+'blood_after'))
        card=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),
            spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')),**fields)
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
