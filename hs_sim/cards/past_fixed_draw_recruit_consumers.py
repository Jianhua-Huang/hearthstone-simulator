"""Complete named Artifact chains and original physical draw/recruit consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.effects import AddToHand,Buff,ChoiceOption,Draw,RequestChoice
from hs_sim.engine.hand_capacity import SetHandCapacity
from hs_sim.engine.model import CardDefinition,CardType,ChoicePurpose,Keyword,Rarity,SummonStats,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.ordered_group_batches import FillBoardWithCard,SummonOrderedGroup
from hs_sim.engine.ordered_summon_groups import OrderedGroupMember,OrderedSummonGroupSpec
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.random_split_damage import RandomSplitDamage
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.summon_sources import DeathQuery,Resurrect,SummonFromZone
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-fixed-draw-recruit-consumers-v1.json'
BATCH_HASH='92008ab2d70035c134b0b66307d322a3d2638f149c2a2893b9f0fcc49caea5dc'
RAFAAM,SINDRAGOSA,ARALON,ZZERAKU,SUBJECT,GHUUN,WHITEMANE,VASTANN,BARNES,VALDRIS,MAGATHA,HOGGER=ROOTS=(
    'LOE_092','ICC_838','REV_363','DRG_209','BOT_573','DMF_056','EX1_190','WON_345','KAR_114','DRG_208','JAM_036','OG_318')
LANTERN,TIMEPIECE,MIRROR,MUMMY,CHAMPION,DRAKE,GNOLL=DEPENDENCIES=(
    'LOEA16_3','LOEA16_4','LOEA16_5','LOEA16_5t','ICC_838t','DRG_209t','OG_318t')
SEEDS=('REV_360t','REV_360t1','REV_360t2')
EXISTING=(*SEEDS,'REV_360t4')
ARTIFACTS=(LANTERN,MIRROR,TIMEPIECE)
NORMALIZATIONS={CHAMPION:{'attack':0}}
PREFIX='cards.past_fixed_draw_recruit.'
LEGENDARIES=PoolQuery(kinds=(CardType.MINION,),collectible=True,rarities=(Rarity.LEGENDARY,))
SECRETS=PoolQuery(kinds=(CardType.SPELL,),keywords_all=(Keyword.SECRET,))


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower())
    if cid not in(*ROOTS,*DEPENDENCIES)or kind not in(CardType.MINION,CardType.SPELL)or type(raw['cost'])is not int:
        raise TargetValidationError('Fixed draw/recruit consumer lost its complete original face')
    fields={}
    if kind==CardType.MINION:
        attack=0 if cid==CHAMPION and raw['attack']is None else raw['attack']
        if type(attack)is not int or type(raw['health'])is not int:raise TargetValidationError('Unknown original minion base')
        fields.update(attack=attack,health=raw['health'])
        if cid in ROOTS and cid not in(ZZERAKU,VASTANN,HOGGER):fields['battlecry']=PREFIX+cid
        if cid in(VASTANN,CHAMPION):fields['deathrattle']=PREFIX+cid
        if cid in(ZZERAKU,HOGGER):fields['triggers']=(TriggerSpec('damage_dealt',PREFIX+cid),)
        if cid==GNOLL:fields['keywords']=(Keyword.TAUNT,)
    else:
        fields['on_play']=PREFIX+cid
        if cid==LANTERN:fields['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or
            d['artifact_member_ids']!=list(ARTIFACTS)or d['artifact_weights']!=[1,1,1]or
            d['wildseed_member_ids']!=list(SEEDS)or d['numeric_normalizations']!=NORMALIZATIONS or
            len(d['official_observations'])!=40 or d['API_unavailable_artifact_ids']!=list(DEPENDENCIES[:4])or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Fixed consumers lost complete source roles, evidence limits or membership')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[group]):
            raise TargetValidationError('Fixed consumers changed a complete original local record')
    p=ROOT/d['full_reference_document']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Fixed consumers changed their full original past source')
    ref=json.loads(p.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in ref['candidate_records']}
    if(len(ref['candidate_ids'])!=732 or d['original_candidate_ids']!=ref['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Fixed consumers cropped their original full source')
    return d


def register_past_fixed_draw_recruit_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Fixed consumers changed an existing Wildseed or awakening weapon')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Fixed consumers cannot replace or alter an original native face')
        registry._validate_card(card);prepared.append(card)
    def named(c,cid,count=1):
        cause=SummonCause.capture(c)
        return tuple(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),cause)for _ in range(count))
    def artifacts(c):
        options=tuple(ChoiceOption(cid,registry.card(cid).name,(AddToHand(c.player_id,cid,c.source_id),),card_id=cid)for cid in ARTIFACTS)
        return(RequestChoice(c.player_id,options,c.source_id,prompt='发现一张强大的神器牌',
            sample_size=3,purpose=ChoicePurpose.CARD_DISCOVERY),)
    def seeds(c):
        members=tuple(OrderedGroupMember(cid,SummonEntryMaterial(cid))for cid in SEEDS)
        return(SummonOrderedGroup(OrderedSummonGroupSpec(c.player_id,SummonCause.capture(c),members)),)
    def damage(c,cid):
        target=c.state.players[c.player_id].hero_id if cid==ZZERAKU else c.source_id
        return named(c,DRAKE if cid==ZZERAKU else GNOLL)if c.event.target_id==target and (c.event.amount or 0)>0 else()
    def whitemane(c):
        ids=tuple(row.id for row in c.state.death_history if row.controller==c.player_id and row.turn==c.state.turn and
            row.zone==Zone.BOARD and registry.card(row.card_id).kind==CardType.MINION)
        return(Resurrect(c.player_id,len(ids),query=DeathQuery(min_turn=c.state.turn,max_turn=c.state.turn),
            selection='first',source_id=c.source_id,cause=SummonCause.capture(c),death_ids=ids),)
    def barnes(c):
        materials=tuple(CopyEntryMaterial.capture(c.state,e,'stored_copy','current',SummonStats(1,1),
            registry=registry,player_id=c.player_id)for i in c.state.players[c.player_id].deck
            for e in(c.state.entities[i],)if e.kind==CardType.MINION)
        return(SummonByCard(c.player_id,materials,SummonCause.capture(c),selection='random'),)if materials else()
    bodies={RAFAAM:artifacts,SINDRAGOSA:lambda c:named(c,CHAMPION,2),ARALON:seeds,
        ZZERAKU:lambda c:damage(c,ZZERAKU),HOGGER:lambda c:damage(c,HOGGER),
        SUBJECT:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(SECRETS,different_cards=True),)*5),),
        GHUUN:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*2,DrawGroupReward('health_payment_all')),),
        MAGATHA:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),)*5,DrawGroupReward('give_drawn_spells')),),
        WHITEMANE:whitemane,VASTANN:lambda c:(SummonFromZone(c.player_id,query=PoolQuery(kinds=(CardType.MINION,),
            keywords_all=(Keyword.TAUNT,)),source_id=c.source_id,cause=SummonCause.capture(c)),),BARNES:barnes,
        VALDRIS:lambda c:(SetHandCapacity(c.player_id,12,'raise'),Draw(c.player_id,4,c.source_id)),
        CHAMPION:lambda c:(GenerateFromPool(c.player_id,'constructed.cards',LEGENDARIES,source_id=c.source_id),),
        LANTERN:lambda c:(Buff(c.target_id,10,10,c.source_id),),
        TIMEPIECE:lambda c:(RandomSplitDamage(c.player_id,c.cast.id,c.source_id,10),),
        MIRROR:lambda c:(FillBoardWithCard(c.player_id,MUMMY,SummonCause.capture(c)),)}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
