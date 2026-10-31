"""Complete named draw-cast chains and original physical zone consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import MinionScope,minion_references
from hs_sim.engine.deathrattle_hand_deliveries import GiveRememberedHandMinions
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import Damage,DestroyBatch,Draw,ForceAttack,InvokeBehavior
from hs_sim.engine.hand_history import hand_entry
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.model import (BoardPresenceReference,CardDefinition,CardType,CastWhenDrawnSpec,DamageKind,
    HandProgressSpec,Keyword,NativeDeathrattleSpec,TargetMode,TargetSpec,Zone)
from hs_sim.engine.native_copy_consumers import SwapDeathrattleWithHand
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup,SOURCE_SPELL_STATS
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import DestroyCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import SummonFromZone
from hs_sim.engine.zones import AddToDeck,CardReference,DestroyDeckMatching,DestroyStoredCard,DiscardMatching
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_deathrattle_memory_cards import memory

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-zone-token-draw-v1.json'
BATCH_HASH='77cec092dd5c3ce114ac30b92cec188d5fbb730c9bce40eabc3e0e8050b9ba97'
LYNN,FLIK,TICKATUS,KANGOR,POZZIK,WAX,MANKRIK,BOOM,MAXIMA,BALINDA=ROOTS=(
    'ETC_071','DRG_037','DMF_118','ETC_329','ETC_425','DRG_036','BAR_721','DAL_064','DMF_089','AV_284')
CORRUPTED,BOT,CANDLE,WIFE,RAGE,BOMB=DEPENDENCIES=('DMF_118t','ETC_425t','DRG_036t','BAR_721t','BAR_721t2','BOT_511t')
EXISTING=('GVG_110t',)
EVIDENCE=('MIS_701','AV_284e','AV_284e2','AV_284e3')
PREFIX='cards.past_zone_token_draw.'


def make_definition(raw):
    cid=raw['id']
    if(cid not in ROOTS+DEPENDENCIES or raw['type']not in('MINION','SPELL')or type(raw['cost'])is not int or
            raw['type']=='MINION'and any(type(raw[k])is not int for k in('attack','health'))):
        raise TargetValidationError('Zone/token consumers require their complete original minion/spell faces')
    fields={}
    if cid in(LYNN,KANGOR,WAX):fields['deathrattle']=PREFIX+cid
    elif cid in(ROOTS+(CORRUPTED,)):fields['battlecry']=PREFIX+cid
    if cid==POZZIK:fields.update(deathrattle=PREFIX+'bots',native_deathrattle=NativeDeathrattleSpec('hand_selection'))
    if cid==LYNN:fields['keywords']=(Keyword.TAUNT,)
    if cid==KANGOR:fields['keywords']=(Keyword.LIFESTEAL,)
    if cid==FLIK:fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,(Zone.BOARD,),(CardType.MINION,),'any')
    if cid==TICKATUS:fields.update(keywords=(Keyword.CORRUPT,),hand_progress=HandProgressSpec('corrupt',upgrade_card_id=CORRUPTED))
    if cid==CORRUPTED:fields['keywords']=(Keyword.CORRUPTED,)
    if cid in(CANDLE,WIFE,BOMB):fields.update(on_play=PREFIX+cid,keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
    return CardDefinition(cid,raw['name'],CardType(raw['type'].lower()),cost=raw['cost'],attack=raw.get('attack')or 0,
        health=raw.get('health')or 0,metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            tuple(x['record']['id']for x in d['evidence_only'])!=EVIDENCE or len(d['official_observations'])!=36 or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Zone/token source roles or completeness claims changed')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']+d['evidence_only']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Incomplete original zone/token source row')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:raise TargetValidationError('Changed full past reference')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or ref['candidate_ids']!=d['original_candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):raise TargetValidationError('Cropped full original past source')
    names=d['complete_fixed_CN_minion_names']
    if(len(names)!=d['minion_name_identity_count']or canonical_digest(names)!=d['minion_name_index_sha256']or
            any(type(k)is not str or not k or type(v)is not str or not v for k,v in names.items())):
        raise TargetValidationError('Changed complete original current-name predicate source')
    return d


def register_past_zone_token_draw(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Blastmaster changed its exact existing Boom Bot')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Zone/token consumers replaced or changed another original face')
        registry._validate_card(card);prepared.append(card)
    def lynn(c):
        players=(c.player_id,3-c.player_id)
        return(*(Draw(p,2,c.source_id)for p in players),*(DiscardMatching(p,count=2,source_id=c.source_id)for p in players),
            InvokeBehavior(PREFIX+'destroy_top',c.source_id,c.player_id))
    def destroy_top(c):return tuple(DestroyDeckMatching(p,count=2,selection='first',source_id=c.source_id)for p in(c.player_id,3-c.player_id))
    def current_name(e):return e.display_name or d['complete_fixed_CN_minion_names'].get(e.card_id,registry.card(e.card_id).name)
    def flik(c):
        if c.target_id is None:return()
        target=c.state.entities[c.target_id]
        if target.kind!=CardType.MINION or target.zone!=Zone.BOARD or not target.active or target.doomed or target.health<=0:return()
        wanted=current_name(target);stored=[];board=[]
        for pid in(c.player_id,3-c.player_id):
            for ref in minion_references(c.state,registry,pid,MinionScope(),c.source_id):
                if current_name(c.state.entities[ref.entity_id])!=wanted:continue
                if type(ref)is MinionReference:board.append(ref.entity_id)
                else:stored.append(DestroyStoredCard(ref,c.source_id))
        return(*((DestroyBatch(tuple(board),c.source_id),)if board else()),*stored)
    def tickatus(c,opponent=False):
        return(DestroyDeckMatching(3-c.player_id if opponent else c.player_id,count=5,selection='first',source_id=c.source_id),)
    def kangor(c):
        if c.deathrattle is None:raise ValueError('Kangor requires its actual original Deathrattle invocation')
        return(SwapDeathrattleWithHand(c.deathrattle.id,SummonCause.capture(c),PREFIX+'lifesteal'),)
    def pozzik(c):
        ref=MinionReference.capture(c.source)if living_source(c)else None
        abilities=tuple(a.id for a in active_abilities(c.source,'deathrattle')if a.deathrattle_memory is not None and
            a.deathrattle_memory.spec==NativeDeathrattleSpec('hand_selection'))if ref is not None else()
        return(GiveRememberedHandMinions(c.player_id,BOT,c.source_id,ref,abilities),)
    def bots(c):
        cause=SummonCause.capture(c);works=[]
        for identity in memory(c,'hand_selection').hand_entry_ids:
            original=hand_entry(c.state,identity);entity=c.state.entities[original.entity_id]
            if entity.card_id==BOT and entity.kind==CardType.MINION and entity.zone in(Zone.HAND,Zone.DECK):
                works.append(SummonStoredCard(CardReference.capture(entity),c.player_id,cause=cause))
        return tuple(works)
    def shuffle(c,cid):return shuffled(c,(AddToDeck(c.player_id,cid,source_id=c.source_id),))
    def summon(c,cid,attack=False):return(SummonByCard(c.player_id,(SummonEntryMaterial(cid,on_summon=PREFIX+'attack'if attack else None),),SummonCause.capture(c)),)
    def attack(c,kill=False):
        target=c.state.entities[c.target_id]
        if target.kind!=CardType.MINION or target.zone!=Zone.BOARD or not target.active or target.doomed or target.health<=0:return()
        original=BoardPresenceReference.capture(c.state,target.id)
        return(ForceAttack(original,c.state.players[3-c.player_id].hero_id),*((DestroyCapturedMinion(MinionReference.capture(target),c.source_id),)if kill else()))
    def boom(c):
        count=sum(c.state.entities[i].card_id==BOMB for i in c.state.players[3-c.player_id].deck)
        if not count:return()
        request=SummonByCard(c.player_id,(SummonEntryMaterial(EXISTING[0]),),SummonCause.capture(c))
        return(request,)*(2*count)
    def maxima(c):return(SummonFromZone(c.player_id,source_id=c.source_id,cause=SummonCause.capture(c),on_summon=PREFIX+'attack_die'),)
    def balinda(c):
        reward=DrawGroupReward(SOURCE_SPELL_STATS,source=BoardPresenceReference.capture(c.state,c.source_id))if living_source(c)else DrawGroupReward()
        return(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,))),)*2,reward),)
    bodies={LYNN:lynn,'destroy_top':destroy_top,FLIK:flik,TICKATUS:tickatus,CORRUPTED:lambda c:tickatus(c,True),
        KANGOR:kangor,'lifesteal':lambda c:(GrantCapturedKeyword(MinionReference.capture(c.state.entities[c.target_id]),Keyword.LIFESTEAL,c.source_id),),
        POZZIK:pozzik,'bots':bots,WAX:lambda c:shuffle(c,CANDLE),MANKRIK:lambda c:shuffle(c,WIFE),
        CANDLE:lambda c:summon(c,WAX),WIFE:lambda c:summon(c,RAGE,True),BOMB:lambda c:(Damage(c.state.players[c.player_id].hero_id,5,c.source_id,DamageKind.SPELL),),
        'attack':attack,'attack_die':lambda c:attack(c,True),BOOM:boom,MAXIMA:maxima,BALINDA:balinda}
    for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
    for card in prepared:registry.register_card(card);registry.register_pool_card(PoolCard.from_definition(card))
