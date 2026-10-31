"""Actual native stat/health providers and complete ordinary/fixed pool recipes."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.deck_conditions import CheckDeckCondition,DeckCondition
from hs_sim.engine.effects import GrantKeyword,Overload,ReplaceHeroPower
from hs_sim.engine.model import (CardClass,CardDefinition,CardType,CostSpec,HandRepeatSpec,
    HealthFlow,Keyword,Rarity,TriggerSpec,Zone)
from hs_sim.engine.native_stat_gains import NativeStatGainProfile
from hs_sim.engine.pools import GenerateFromCandidates,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.random_secret_generation import SetRandomSecretFromPool
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.summon_sources import DeathQuery,Resurrect,death_candidates
from hs_sim.engine.zones import ChooseFromZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .core_secret_cards import event_play
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-live-provider-pools-v1.json'
BATCH_HASH='6570a25f987604dc4db1c1d81c59758f97be2c9c56497213cf499b2b9d3aee39'
SAIDAN,LUMIA,NAIELLE,NEPTULON,COLLECTOR,QUEEN,PUTRICIDE,ROTFACE,HADRONOX,HELBRIM=ROOTS=(
    'AV_345','GDB_144','GDB_846','GVG_042','GIL_677','DRG_089','ICC_204','ICC_405','ICC_835','BAR_324')
TRACKING,=DEPENDENCIES=('GDB_846hp',)
POISONS=('CS2_074','ICC_221','YOP_015','BAR_321','BAR_318')
EXISTING=(*POISONS,'YOP_015t')
EVIDENCE=('MIS_701','CORE_CS2_074','CORE_ICC_221')
PREFIX='cards.past_live_provider_pools.'
POOL='constructed.cards'
MURLOCS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('murloc',))
LEGENDARIES=PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,))
DRAGONS=PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('dragon',),exclude_source=True)
HUNTER_SECRETS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,keywords_all=(Keyword.SECRET,),
    class_mode='specified',classes=(CardClass.HUNTER,),include_neutral=False)
TAUNT_DEATHS=DeathQuery(cards=PoolQuery(keywords_all=(Keyword.TAUNT,)),keywords_at_death=True)


def make_definition(raw):
    cid=raw['id'];kind=CardType.HERO_POWER if cid==TRACKING else CardType.MINION
    if (cid not in ROOTS+DEPENDENCIES or raw['type']!=kind.name or type(raw['cost'])is not int or
            kind==CardType.MINION and any(type(raw[k])is not int for k in('attack','health'))):
        raise TargetValidationError('Live providers require their complete original physical faces')
    fields={}
    if cid in(NAIELLE,NEPTULON,COLLECTOR,QUEEN,HELBRIM):fields['battlecry']=PREFIX+cid
    if cid in(HADRONOX,HELBRIM):fields['deathrattle']=PREFIX+cid
    if cid==SAIDAN:fields['keywords']=(Keyword.RUSH,)
    if cid==LUMIA:fields.update(keywords=(Keyword.LIFESTEAL,),triggers=(
        TriggerSpec('health_resolved',PREFIX+'immune'),))
    if cid==NEPTULON:fields['on_play']=PREFIX+'overload'
    if cid==COLLECTOR:fields.update(keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec())
    if cid==PUTRICIDE:fields['triggers']=(TriggerSpec('card_played',PREFIX+'secret'),)
    if cid==ROTFACE:fields['triggers']=(TriggerSpec('health_resolved',PREFIX+'legendary'),)
    if cid==TRACKING:fields['on_use']=PREFIX+'tracking'
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],
        attack=raw['attack']if kind==CardType.MINION else 0,health=raw['health']if kind==CardType.MINION else 0,
        metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or
            tuple(d['fixed_poison_candidate_ids'])!=POISONS or len(d['official_observations'])!=36 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage',
                'formal_pool_complete','cn_calibrated','official_poison_pool_verified'))):
        raise TargetValidationError('Live providers lost complete source roles, fixed candidates or open-domain boundaries')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:
            raise TargetValidationError('Changed complete original live-provider source row')
    for key in('full_reference','primary_child_relations','poison_public_reference'):
        item=d[key];path=(ROOT/item['path']).resolve()
        if not path.is_relative_to(ROOT)or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise TargetValidationError('Changed complete retained provider evidence')
    ref=json.loads((ROOT/d['full_reference']['path']).read_text(encoding='utf8'))
    original={x['record']['id']:x['record']for x in ref['candidate_records']}
    if (len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or
            any(x['record']!=original[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Cropped complete original past source')
    return d


def hero_damage(c):
    h=c.health_result
    return (h is not None and h.flow==HealthFlow.DAMAGE.value and h.damage_dealt>0 and
        h.target_kind==CardType.HERO.value and h.target_id==c.state.players[h.target_controller].hero_id)


def survived(c):
    h=c.health_result;e=c.source
    return (h is not None and h.flow==HealthFlow.DAMAGE.value and h.damage_dealt>0 and
        h.target_id==e.id and h.health_after>0 and not h.doomed_after and
        e.zone==Zone.BOARD and e.active and e.health>0 and not e.doomed and
        (h.target_zone_epoch,h.target_entered_order)==(e.zone_epoch,e.entered_order))


def register_past_live_provider_pools(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if (canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Live providers changed a complete existing Poison dependency')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if (card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Live providers cannot replace or alter a complete physical face')
        registry._validate_card(card);prepared.append(card)
    def played_secret(c):
        p=event_play(c)
        return (p is not None and p.player_id==c.player_id and p.kind==CardType.SPELL and
            not p.countered and registry.card(p.card_id).secret is not None)
    def hadronox(c):
        rows=death_candidates(c.state,registry,c.player_id,TAUNT_DEATHS,c.source_id)
        return ()if not rows else(Resurrect(c.player_id,len(rows),TAUNT_DEATHS,source_id=c.source_id,
            cause=SummonCause.capture(c),death_ids=tuple(row.id for row in rows)),)
    bodies={
        NAIELLE:lambda c:(ReplaceHeroPower(c.player_id,TRACKING,source_id=c.source_id),),
        NEPTULON:lambda c:(GenerateFromPool(c.player_id,POOL,MURLOCS,count=4,source_id=c.source_id),),
        COLLECTOR:lambda c:(GenerateFromPool(c.player_id,POOL,LEGENDARIES,source_id=c.source_id),),
        QUEEN:lambda c:(CheckDeckCondition(c.player_id,DeckCondition('current','no_duplicates'),(
            GenerateFromPool(c.player_id,POOL,DRAGONS,count=2,source_id=c.source_id,cost=CostSpec(set_to=0)),)),),
        HADRONOX:hadronox,
        HELBRIM:lambda c:(GenerateFromCandidates(c.player_id,POISONS,c.source_id),),
        'tracking':lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.DECK,operation='take',
            distinct='entity',source_id=c.source_id,discovery=True,prompt='从你的牌库中发现一张牌'),),
        'overload':lambda c:(Overload(c.player_id,3),),
        'immune':lambda c:()if not hero_damage(c)else(
            GrantKeyword(c.health_result.target_id,Keyword.IMMUNE,c.source_id,expires_turn=c.state.turn),),
        'secret':lambda c:()if not played_secret(c)else(
            SetRandomSecretFromPool(c.player_id,POOL,c.source_id,HUNTER_SECRETS),),
        'legendary':lambda c:()if not survived(c)else(
            GenerateFromPool(c.player_id,POOL,LEGENDARIES,source_id=c.source_id,
                destination='board',cause=SummonCause.capture(c)),),
    }
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    for card in prepared:
        registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
    registry.register_native_stat_gain_profile(NativeStatGainProfile(SAIDAN,'double_positive'))
