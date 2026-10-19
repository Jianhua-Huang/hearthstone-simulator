"""Lady Azshara's actual Fabled location family and ordinary Choose One bodies."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.card_creation import CardSpellRepeatGrant
from hs_sim.engine.effects import CopyMinion, InvokeBehavior
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.locations import (AdvanceLocationFace, AdvanceStoredLocationFace,
    DestroyCapturedLocation, LocationFaceReference)
from hs_sim.engine.model import (BoardPresenceReference, CardDefinition, CardType,
    ChooseBranch, ChooseOneSpec, SummonStats, TargetSpec, Zone)
from hs_sim.engine.pools import FillHandFromPool, GenerateFromPool, PoolCard, PoolQuery
from hs_sim.engine.zones import CardReference, DestroyStoredCard
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record

ROOT='TIME_211'; ZIN_BRANCH='TIME_211a'; WELL_BRANCH='TIME_211b'
WELL='TIME_211t1'; WELL_UP='TIME_211t1t'; ZIN='TIME_211t2'; ZIN_UP='TIME_211t2t'
DEPENDENCIES=(ZIN_BRANCH,WELL_BRANCH,WELL,WELL_UP,ZIN,ZIN_UP)
PREFIX='cards.azshara_fabled_locations.'
POOL='constructed.cards'; SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/azshara-fabled-locations-v1.json'
BATCH_HASH='c75a447db26162da68d61b2b2c020a3ec9ba8d73893ad63ea743be39dc04846e'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(ROOT,)
            or tuple(x['record']['id']for x in data['dependencies'])!=DEPENDENCIES
            or data['existing_dependencies']
            or tuple(x['record']['id']for x in data['evidence_only'])!=('TIME_211t1te','TIME_211t2te')):
        raise TargetValidationError('Azshara requires her complete original Fabled family')
    for key in ('cards','dependencies','evidence_only'):
        for row in data[key]:
            if canonical_digest(row['record'])!=row['record_sha256']:
                raise TargetValidationError('Azshara original source changed')
    return data


def register_azshara_fabled_location_cards(registry):
    def empower(c, base, upgraded, removed):
        player=c.state.players[c.player_id]
        originals=tuple(c.state.entities[i]for i in (*player.board,*player.hand,*player.deck))
        upgrades=[];destruction=[]
        for e in originals:
            if e.kind!=CardType.LOCATION or e.controller!=c.player_id:
                continue
            if e.card_id==base:
                upgrades.append(AdvanceLocationFace(LocationFaceReference.capture(c.state,e.id),upgraded,c.source_id)
                    if e.zone==Zone.BOARD else AdvanceStoredLocationFace(CardReference.capture(e),upgraded,c.source_id))
            elif e.card_id in removed:
                destruction.append(DestroyCapturedLocation(LocationFaceReference.capture(c.state,e.id),c.source_id)
                    if e.zone==Zone.BOARD else DestroyStoredCard(CardReference.capture(e),c.source_id))
        return (*upgrades,*destruction)
    def zin(c):return empower(c,ZIN,ZIN_UP,(WELL,WELL_UP))
    def well(c):return empower(c,WELL,WELL_UP,(ZIN,ZIN_UP))
    def both(c):
        # Both real printed bodies run. The second sees the first body's new
        # faces, so both locations are destroyed, as the designer confirmed.
        return (*zin(c),InvokeBehavior(PREFIX+'well',c.source_id,c.player_id))
    def fill(c,upgraded):
        return (FillHandFromPool(GenerateFromPool(c.player_id,POOL,SPELLS,source_id=c.source_id,
            temporary_until_turn=c.state.turn,spell_repeat=CardSpellRepeatGrant()if upgraded else None)),)
    def copy(c,upgraded):
        target=c.state.entities.get(c.target_id)
        if target is None:return ()
        stats=SummonStats(target.attack*2,target.health*2)if upgraded else None
        return (CopyMinion(BoardPresenceReference.capture(c.state,target.id),c.player_id,stats=stats),)
    for name,body in (('zin',zin),('well',well),('both',both),
        ('fill',lambda c:fill(c,False)),('fill_twice',lambda c:fill(c,True)),
        ('copy',lambda c:copy(c,False)),('copy_double',lambda c:copy(c,True))):
        registry.register_behavior(PREFIX+name,body)
    data=load_batch();raws={x['record']['id']:x['record']for x in data['cards']+data['dependencies']}
    spec=ChooseOneSpec((ChooseBranch(ZIN_BRANCH,raws[ZIN_BRANCH]['name'],PREFIX+'zin'),
        ChooseBranch(WELL_BRANCH,raws[WELL_BRANCH]['name'],PREFIX+'well')),
        ChooseBranch(ROOT+':combined','兼得',PREFIX+'both'))
    for cid,raw in raws.items():
        choice=cid in (ZIN_BRANCH,WELL_BRANCH)
        kw={};kind=CardType(raw['type'].lower())
        if cid==ROOT:
            if (raw['cost'],raw['attack'],raw['health'])!=(5,5,5):
                raise TargetValidationError('Azshara original face changed')
            kw.update(attack=5,health=5,choose_one=spec)
        elif not choice:
            if kind!=CardType.LOCATION or (raw['cost'],raw['health'])!=(4,3):
                raise TargetValidationError('Azshara original location face changed')
            kw.update(durability=3,on_use=PREFIX+('fill_twice'if cid==WELL_UP else'fill'if cid==WELL else
                'copy_double'if cid==ZIN_UP else'copy'))
            if cid in (ZIN,ZIN_UP):
                kw.update(requires_board_space=True,targeting=TargetSpec(zones=(Zone.BOARD,),
                    kinds=(CardType.MINION,),relation='friendly'))
        card=CardDefinition(cid,raw['name'],kind,cost=0 if choice else raw['cost'],choice_only=choice,
            metadata=replace(metadata_from_record(raw),deck_identity=cid),**kw)
        registry.register_card(card)
        if not choice and cid not in registry.pool_cards:
            registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_fabled(FabledSpec(ROOT,(WELL,ZIN)))
