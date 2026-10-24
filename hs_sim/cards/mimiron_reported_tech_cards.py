"""Reported tech faces; this module does not invent Mimiron's producer pool."""
import json
from pathlib import Path

from hs_sim.engine.effects import ChangeControl,Destroy,DestroyBatch,SilenceBatch
from hs_sim.engine.locations import DestroyLocation
from hs_sim.engine.model import (CardDefinition,CardType,HandActionSpec,Keyword,KeywordAuraSpec,
    Rarity,TargetMode,TargetSpec,Zone)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import DestroyForBuff,MinionReference
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BOUNTY,GLUTTON,RENOVATOR,STARFISH,TECH,HORROR,DRAGON=(
    'AV_138','DED_523','REV_023','TSC_926','EX1_085','GIL_124','DRG_068')
CARDS=(BOUNTY,GLUTTON,RENOVATOR,STARFISH,TECH,HORROR,DRAGON)
COLLECTIBLE_ROOTS=()
PREFIX='cards.mimiron_reported_tech.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/mimiron-reported-tech-v1.json'
BATCH_HASH='732491ee3b94835d91374495b912d72d0166329e2f63cec6b1f22a6c21c9e0f3'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id'] for x in data['cards'])!=CARDS or
            tuple(x['record']['id'] for x in data['evidence_only'])!=('BE_588','REV_378','AV_135') or
            data['mimiron_root_implemented'] is not False or len(data['official_observations'])!=20 or
            any(canonical_digest(x['record'])!=x['record_sha256'] for section in
                ('cards','existing_dependencies','evidence_only') for x in data[section])):
        raise TargetValidationError('Reported tech faces require their complete original rows and pending producer')
    return data


def other_living_minions(c):
    return tuple(i for p in c.state.players.values() for i in p.board if i!=c.source_id and
        c.state.entities[i].kind==CardType.MINION and c.state.entities[i].active and
        c.state.entities[i].health>0 and not c.state.entities[i].doomed)


def four_enemy_minions(c):
    """The manual and automatic target path both provide this detached DTO."""
    opponent=next(p for p in c.observation['players'] if p['id']==3-c.player_id)
    return sum(e.get('kind')==CardType.MINION.value for e in opponent['board'])>=4


def register_mimiron_reported_tech_cards(registry):
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'legendary',printed_rarities=(Rarity.LEGENDARY,)))
    registry.register_target_predicate(TargetPredicateSpec(PREFIX+'beast',current_tribes_any=('beast',)))
    registry.register_target_rule(PREFIX+'four_enemy',four_enemy_minions,visibility='player')

    def destroy_target(c):return () if c.target_id is None else (Destroy(c.target_id,c.source_id),)

    def glutton(c):
        if c.target_id is None:return ()
        target=c.state.entities[c.target_id];source=c.state.entities[c.source_id]
        if (source.zone!=Zone.BOARD or not source.active or source.health<=0 or source.doomed):
            # Destruction still happens if the original beneficiary has left.
            return (Destroy(target.id,c.source_id),)
        return (DestroyForBuff(MinionReference.capture(target),MinionReference.capture(source),1,1,c.source_id,
            require_live_beneficiary=False),)

    def starfish(c):return (SilenceBatch(other_living_minions(c)),)

    def horror(c):
        return (DestroyBatch(tuple(i for i in other_living_minions(c) if c.state.entities[i].attack<=2),c.source_id),)

    def tech(c):
        count=sum(c.state.entities[i].kind==CardType.MINION for i in c.state.players[3-c.player_id].board)
        return () if c.target_id is None or count<4 else (ChangeControl(c.target_id,c.player_id),)

    def renovate(c):return () if c.target_id is None else (DestroyLocation(c.target_id,c.source_id),)

    bodies={BOUNTY:destroy_target,GLUTTON:glutton,RENOVATOR:renovate,STARFISH:starfish,TECH:tech,HORROR:horror}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    targets={
        BOUNTY:dict(target_rule=PREFIX+'legendary',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='enemy',exclude_source=True)),
        GLUTTON:dict(target_rule=PREFIX+'beast',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='any',exclude_source=True)),
        RENOVATOR:dict(targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.LOCATION,),relation='enemy',exclude_source=True)),
        TECH:dict(target_rule=PREFIX+'four_enemy',targeting=TargetSpec(TargetMode.IF_AVAILABLE,kinds=(CardType.MINION,),relation='enemy',exclude_source=True))}
    for row in load_batch()['cards']:
        raw=row['record'];cid=raw['id'];kw=dict(targets.get(cid,{}))
        if cid in bodies:kw['battlecry']=PREFIX+cid
        if cid==RENOVATOR:kw['hand_actions']=(HandActionSpec('trade','trade',cost=1),)
        if cid==DRAGON:kw['keyword_auras']=(KeywordAuraSpec(Keyword.CANT_BE_FROZEN,'friendly_minions',include_self=True),)
        card=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],
            metadata=metadata_from_record(raw),**kw)
        registry.register_card(card)
        if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
