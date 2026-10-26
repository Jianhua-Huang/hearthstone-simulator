"""Reviewed Final Frontier dependencies composed from existing public effects."""
from dataclasses import replace
import json
from pathlib import Path

from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import Damage, DamageBatch, GainArmor, RefreshMana
from hs_sim.engine.model import (BoardMinionCostSpec, CardDefinition, CardType,
    ChooseBranch, ChooseOneSpec, HandCountCostSpec, Keyword, PlayerHeroPowerCountCostSpec)
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import GrantCapturedKeyword, MinionReference
from hs_sim.engine.summon_quantities import SummonByCard, SummonCause, SummonEntryMaterial
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference, DestroyDeckBatch
from hs_sim.targets import TargetValidationError, canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

ROOTS = ('ULD_193','ULD_721','UNG_806','UNG_852','AT_120','CORE_EX1_586','SW_062',
    'BT_155','CORE_REV_375','ETC_086','CFM_308','CORE_MAW_034','OG_317')
TOKENS = ('BT_155t','REV_375t')
CHOICES = ('CFM_308a','CFM_308b')
KUN_BOTH = 'CFM_308:combined'
PREFIX = 'cards.frontier_common_natives.'
BATCH_PATH = Path(__file__).resolve().parents[2]/'data/cards/frontier-common-natives-v1.json'
BATCH_HASH = '626eb3d4eb342f83a0493de90235323fbbeec5c5f62e771b3683ecb0db1d5d42'
ALIASES = {'CORE_EX1_586':'EX1_586','CORE_REV_375':'REV_375','CORE_MAW_034':'MAW_034'}


def load_batch():
    value=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
    all_rows=value['cards']+value['dependencies']+value['choices']+value['evidence_only']
    if (canonical_digest(value)!=BATCH_HASH or value['schema']!=1 or
            tuple(x['record']['id']for x in value['cards'])!=ROOTS or
            tuple(x['record']['id']for x in value['dependencies'])!=TOKENS or
            tuple(x['record']['id']for x in value['choices'])!=CHOICES or
            len(value['official_faces'])!=30 or value['formal_pool_complete']is not False or
            value['cn_calibrated']is not False or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in all_rows)):
        raise TargetValidationError('Frontier dependencies lost their complete original source inventory')
    raw={x['record']['id']:x['record']for x in all_rows}
    for core,original in ALIASES.items():
        faces=[f for f in value['official_faces']if f['card_id']==original]
        if (len(faces)!=2 or any(raw[core]['dbf_id']not in f['face'].get('copyOfCardId',())for f in faces) or
                any(raw[core][k]!=raw[original][k]for k in ('type','cost','text_en'))):
            raise TargetValidationError('Frontier Core dependency lost its original copy association')
    return value


def register_frontier_common_natives(registry):
    value=load_batch();rows={x['record']['id']:x['record']for key in ('cards','dependencies','choices')for x in value[key]}
    if any(cid in registry.cards for cid in rows):
        raise TargetValidationError('Frontier dependencies cannot replace existing native identities')

    def summon(c,card_id):
        return (SummonByCard(c.player_id,(SummonEntryMaterial(card_id),),SummonCause.capture(c),
            position=deathrattle_position(c)),)

    def refresh(c):return RefreshMana(c.player_id,c.state.players[c.player_id].max_mana)

    def jailer(c):
        cards=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].deck)
        return (DestroyDeckBatch(cards,c.source_id,reveal=False),
            GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.IMMUNE,c.source_id))

    def dragonlord(c):
        cause=SummonCause.capture(c)
        cards=tuple(CardReference.capture(c.state.entities[i])
            for i in c.state.players[c.player_id].hand
            if has_any_tribe(registry,c.state.entities[i],('dragon',)))
        position=deathrattle_position(c)
        return tuple(SummonStoredCard(card,c.player_id,
            position=None if position is None else position+index,cause=cause)
            for index,card in enumerate(cards))

    bodies={
        'BT_155':lambda c:summon(c,'BT_155t'),
        'CORE_REV_375':lambda c:summon(c,'REV_375t'),
        'ETC_086':lambda c:(DamageBatch(tuple(Damage(i,3,c.source_id)
            for i in c.state.players[3-c.player_id].board
            if c.state.entities[i].kind==CardType.MINION)),),
        'CFM_308a':lambda c:(GainArmor(c.player_id,10),),
        'CFM_308b':lambda c:(refresh(c),),
        KUN_BOTH:lambda c:(GainArmor(c.player_id,10),refresh(c)),
        'CORE_MAW_034':jailer,
        'OG_317':dragonlord,
    }
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    declarations={
        'ULD_193':dict(keywords=(Keyword.TAUNT,)),
        'ULD_721':dict(keywords=(Keyword.DIVINE_SHIELD,Keyword.REBORN)),
        'UNG_806':{},
        'UNG_852':dict(keywords=(Keyword.TAUNT,Keyword.ELUSIVE)),
        'AT_120':dict(player_hero_power_count_cost=PlayerHeroPowerCountCostSpec()),
        'CORE_EX1_586':dict(board_minion_cost=BoardMinionCostSpec('all')),
        'SW_062':dict(keywords=(Keyword.RUSH,),hand_count_cost=HandCountCostSpec()),
        'BT_155':dict(keywords=(Keyword.TAUNT,),deathrattle=PREFIX+'BT_155'),
        'CORE_REV_375':dict(keywords=(Keyword.RUSH,),deathrattle=PREFIX+'CORE_REV_375'),
        'ETC_086':dict(keywords=(Keyword.TAUNT,),deathrattle=PREFIX+'ETC_086'),
        'CFM_308':dict(choose_one=ChooseOneSpec(tuple(ChooseBranch(cid,rows[cid]['name'],PREFIX+cid)for cid in CHOICES),
            ChooseBranch(KUN_BOTH,'兼得',PREFIX+KUN_BOTH))),
        'CORE_MAW_034':dict(battlecry=PREFIX+'CORE_MAW_034'),
        'OG_317':dict(deathrattle=PREFIX+'OG_317'),
        'BT_155t':dict(keywords=(Keyword.TAUNT,)),
        'REV_375t':dict(keywords=(Keyword.RUSH,)),
    }
    for cid,raw in rows.items():
        internal=cid in CHOICES;kind=CardType(raw['type'].lower());meta=metadata_from_record(raw)
        if cid in ALIASES:meta=replace(meta,deck_identity=ALIASES[cid])
        fields={}if internal else dict(declarations[cid],attack=raw['attack'],health=raw['health'])
        card=CardDefinition(cid,raw['name'],kind,cost=0 if internal else raw['cost'],
            metadata=meta,choice_only=internal,**fields)
        registry.register_card(card)
        if not internal:registry.register_pool_card(PoolCard.from_definition(card))
