"""Actual Fabled Talanji/Bwonsamdi bundle and its three nonphysical boon choices."""
import json
from pathlib import Path

from hs_sim.engine.effects import ChoiceOption,Damage,DamageBatch,RequestChoice
from hs_sim.engine.fabled_decks import FabledSpec
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,PlayerEffectSpec
from hs_sim.engine.named_minion_boons import NamedBoon,NamedMinionBoonsProfile,material
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,ResurrectMinion,death_candidates
from hs_sim.engine.zones import DrawMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters

CARD='TIME_619';BWON='TIME_619t';SPELL='TIME_619t2'
BOONS=('TIME_619t3','TIME_619t4','TIME_619t5')
KEYWORDS=(Keyword.TAUNT,Keyword.LIFESTEAL,Keyword.RUSH)
PREFIX='cards.talanji.';POOL_ID='constructed.minions'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/talanji-bwonsamdi-v1.json'
BATCH_HASH='2fb1ffe992bac5283212389d8135e3add9bd6ab59710d610c7e12c1644534dc3'


def load_batch():
    data=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    rows=(*data['cards'],*data['choice_only'],*data['evidence_only'])
    if (canonical_digest(data)!=BATCH_HASH or tuple(x['record']['id']for x in data['cards'])!=(CARD,BWON,SPELL) or
            tuple(x['record']['id']for x in data['choice_only'])!=BOONS or len(data['evidence_only'])!=6 or
            any(data[k]for k in('dependencies','existing_dependencies','skipped')) or
            any(canonical_digest(x['record'])!=x['record_sha256']for x in rows)):
        raise TargetValidationError('Talanji requires its complete Fabled bundle, three actual boons and original enchantments')
    root,bwon,spell=(x['record']for x in data['cards'])
    if ((root['type'],root['cost'],root['attack'],root['health'],root['tags'].get('FABLED'))!=('MINION',4,4,5,1) or
            (bwon['type'],bwon['cost'],bwon['attack'],bwon['health'],bwon['tags'].get('TAG_SCRIPT_DATA_NUM_1'))!=('MINION',6,6,6,4) or
            (spell['type'],spell['cost'])!=('SPELL',3) or
            any(x['tags'].get('IS_FABLED_BUNDLE_CARD')!=1 for x in(bwon,spell))):
        raise TargetValidationError('Talanji original bodies, Fabled companions or initial death tier changed')
    return data


def register_talanji_bwonsamdi_cards(registry):
    data=load_batch();rows={x['record']['id']:x for x in(*data['cards'],*data['choice_only'])}
    def choose(c):
        return(RequestChoice(c.player_id,tuple(ChoiceOption(cid,registry.card(cid).name,
            (AddPlayerEffect(c.player_id,PREFIX+cid,c.source_id),),card_id=cid)for cid in BOONS),
            c.source_id,prompt='选择一项邦桑迪的恩泽'),)
    def talanji(c):
        deaths=death_candidates(c.state,registry,c.player_id,DeathQuery(cards=PoolQuery(card_ids=(BWON,))),c.source_id)
        obtain=ResurrectMinion(c.player_id,deaths[-1].id,source_id=c.source_id,cause=SummonCause.capture(c))if deaths else(
            DrawMatching(c.player_id,PoolQuery(kinds=(CardType.MINION,),card_ids=(BWON,)),'skip',source_id=c.source_id))
        return(obtain,*choose(c))
    def swathe(c):
        hits=tuple(Damage(eid,2,c.source_id,DamageKind.SPELL)for eid in characters(c,registry,3-c.player_id))
        return(DamageBatch(hits),*choose(c))
    def bwonsamdi(c):
        cost,keywords,_=material(c.state,registry,c.player_id,BWON)
        return(SummonFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,
            min_cost=cost,max_cost=cost),source_id=c.source_id,cause=SummonCause.capture(c),entry_keywords=keywords),)
    for name,body in(('root',talanji),('spell',swathe),('death',bwonsamdi)):registry.register_behavior(PREFIX+name,body)
    for cid in(CARD,BWON,SPELL,*BOONS):
        row=rows[cid];raw=row['record'];kind=CardType(raw['type'].lower());option=cid in BOONS
        card=CardDefinition(cid,raw['name'],kind,cost=0 if option else raw['cost'],
            attack=raw['attack']if kind==CardType.MINION else 0,health=raw['health']if kind==CardType.MINION else 0,
            metadata=metadata_from_record(raw),choice_only=option,
            battlecry=PREFIX+'root'if cid==CARD else None,deathrattle=PREFIX+'death'if cid==BWON else None,
            on_play=PREFIX+'spell'if cid==SPELL else None)
        registry.register_card(card)
        if not option and cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
    for cid in BOONS:registry.register_player_effect(PlayerEffectSpec(PREFIX+cid,BWON))
    registry.register_named_minion_boon_profile(NamedMinionBoonsProfile(BWON,CARD,SPELL,
        tuple(NamedBoon(PREFIX+cid,cid,keyword)for cid,keyword in zip(BOONS,KEYWORDS))))
    registry.register_fabled(FabledSpec(CARD,(BWON,SPELL)))
