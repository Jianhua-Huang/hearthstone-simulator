"""Original copy, physical deck choice, temporary price and attack consumers."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.card_conditions import has_battlecry
from hs_sim.engine.copy_materials import CapturedCardCopyMaterial
from hs_sim.engine.effects import AddCostModifier,AddToHand,Damage,DamageBatch,Freeze
from hs_sim.engine.equipment import equipped_weapon
from hs_sim.engine.forced_attack_sequences import AttackAllOtherMinions
from hs_sim.engine.hand_upgrades import BuffStoredCard
from hs_sim.engine.model import (BoardPresenceReference,CardClass,CardDefinition,CardType,CostSpec,DamageKind,
    Keyword,SpellSchool,TargetMode,TargetSpec,TriggerSpec,Zone)
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.return_followups import ReturnCapturedMinion
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.zones import CardReference,ChooseFromZone,CopyCard,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-copy-target-resource-consumers-v1.json'
BATCH_HASH='4ffc1e282b18d1f5dedc50fe09e2e407b62d2ece1f4d1ed59414d991b9b9c4d0'
NEFARIAN,YSIEL,BARISTA,JEPETTO,YREL,KIRI,SHEKZARA,TENWU,DEATHWING,VARDEN,CARIEL,HOBART=ROOTS=(
    'BRM_030','BT_131','DAL_546','DAL_752','DMF_241','DMF_733','DMF_516','DMF_071','DRG_026','BAR_748','BAR_902','CFM_643')
DEPENDENCIES=('BRM_030t',)
TAIL=DEPENDENCIES[0]
LUNAR,SOLAR=EXISTING=('DMF_057','DMF_058')
PREFIX='cards.past_copy_target_resource.'


def make_definition(raw):
    cid=raw['id'];kind=CardType(raw['type'].lower());fields={}
    if cid not in(*ROOTS,*DEPENDENCIES)or type(raw['cost'])is not int:
        raise TargetValidationError('Copy/target/resource consumer lost its complete original face')
    if kind==CardType.MINION:
        if cid not in ROOTS or type(raw['attack'])is not int or type(raw['health'])is not int:
            raise TargetValidationError('Copy/target/resource requires its original complete minion bases')
        fields.update(attack=raw['attack'],health=raw['health'])
        if cid==CARIEL:fields.update(keywords=(Keyword.RUSH,Keyword.DIVINE_SHIELD),triggers=(TriggerSpec('attack_declared',PREFIX+cid),))
        else:fields['battlecry']=PREFIX+cid
        if cid==TENWU:fields['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly',exclude_source=True)
    elif kind==CardType.SPELL and cid==TAIL:
        fields.update(on_play=PREFIX+cid,targeting=TargetSpec(zones=(Zone.HERO,Zone.BOARD),kinds=(CardType.HERO,CardType.MINION)))
    else:raise TargetValidationError('Unexpected original copy/target/resource physical type')
    return CardDefinition(cid,raw['name'],kind,cost=raw['cost'],metadata=metadata_from_record(raw),**fields)


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if(canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or
            tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES or
            tuple(x['record']['id']for x in d['existing_dependencies'])!=EXISTING or
            [x['record']['id']for x in d['evidence_only']]!=['MIS_701']or len(d['official_observations'])!=32 or
            d['neutral_hero_reward_ids']!=[TAIL,TAIL]or d['kiri_reward_ids']!=[SOLAR,LUNAR]or
            any(d[k]for k in('complete_past_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Copy/target/resource lost complete source roles or made a partial completeness claim')
    for group in('cards','dependencies','existing_dependencies','evidence_only'):
        if any(canonical_digest(x['record'])!=x['record_sha256']for x in d[group]):
            raise TargetValidationError('Copy/target/resource changed a complete original raw row')
    path=ROOT/d['full_reference_document']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=d['full_reference_sha256']:
        raise TargetValidationError('Copy/target/resource changed its full original reference')
    reference=json.loads(path.read_text(encoding='utf8'));rows={x['record']['id']:x['record']for x in reference['candidate_records']}
    if(len(reference['candidate_ids'])!=732 or d['original_candidate_ids']!=reference['candidate_ids']or
            any(x['record']!=rows[x['record']['id']]for x in d['cards'])):
        raise TargetValidationError('Copy/target/resource cropped its original complete source')
    return d


def register_past_copy_target_resource_consumers(registry):
    d=load_batch();prepared=[]
    for row in d['existing_dependencies']:
        cid=row['record']['id']
        if(canonical_digest(asdict(registry.card(cid)))!=row['definition_sha256']or
                canonical_digest(asdict(registry.pool_card(cid)))!=row['pool_card_sha256']):
            raise TargetValidationError('Copy/target/resource changed an existing Eclipse')
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if(card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']or
                canonical_digest(asdict(PoolCard.from_definition(card)))!=row['pool_card_sha256']):
            raise TargetValidationError('Copy/target/resource cannot replace or alter an existing original face')
        registry._validate_card(card);prepared.append(card)
    def nefarian(c):
        current=c.state.players[3-c.player_id].hero_class
        if type(current)is not CardClass:raise UnsupportedDefinitionError('Nefarian requires the actual known current opponent hero class')
        if current==CardClass.NEUTRAL:return(AddToHand(c.player_id,TAIL,c.source_id),)*2
        return(GenerateFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.SPELL,),collectible=True,
            class_mode='specified',classes=(current,),include_neutral=False),2,source_id=c.source_id),)
    def barista(c):
        materials=tuple(CapturedCardCopyMaterial.capture(c.state,c.state.entities[i])for i in minions(c,registry,c.player_id)
            if i!=c.source_id and has_battlecry(c.state.entities[i].abilities))
        return tuple(CopyCard(material,c.player_id,Zone.HAND,mode='base',source_id=c.source_id)for material in materials)
    def yrel(c):
        for i in c.state.players[c.player_id].deck:
            metadata=registry.card(c.state.entities[i].card_id).metadata
            if metadata is None or metadata.classes is None:raise UnsupportedDefinitionError('Yrel requires complete current physical deck classes')
            if CardClass.NEUTRAL in metadata.classes:return()
        source=c.source
        if source.zone!=Zone.BOARD or not source.active or source.health<=0 or source.doomed:return()
        ref=MinionReference.capture(source)
        return tuple(GrantCapturedKeyword(ref,key,c.source_id)for key in(Keyword.RUSH,Keyword.LIFESTEAL,Keyword.TAUNT,Keyword.DIVINE_SHIELD))
    def tenwu(c):
        return()if c.target_id is None else(ReturnCapturedMinion(MinionReference.capture(c.state.entities[c.target_id]),
            c.source_id,cost=CostSpec(set_to=1),expires_turn=c.state.turn),)
    def varden(c):
        group=tuple((i,c.state.entities[i].frozen)for i in minions(c,registry,3-c.player_id))
        packets=tuple(Damage(i,4,c.source_id,DamageKind.MINION_ABILITY)for i,frozen in group if frozen)
        return(*(Freeze(i,c.source_id)for i,frozen in group if not frozen),*((DamageBatch(packets),)if packets else()))
    def cariel(c):
        if c.event.source_id!=c.source_id:return()
        return tuple(ModifyStoredCost(CardReference.capture(e),CostSpec(delta=-1),c.source_id)
            for i in tuple(c.state.players[c.player_id].hand)for e in(c.state.entities[i],)
            if e.kind==CardType.SPELL and registry.card(e.card_id).spell_school==SpellSchool.HOLY)
    def hobart(c):
        if equipped_weapon(c.state,c.state.players[c.player_id])is None:return()
        player=c.state.players[c.player_id]
        return tuple(BuffStoredCard(CardReference.capture(e),2,2,c.source_id)
            for i in(*player.hand,*player.deck)for e in(c.state.entities[i],)if e.kind==CardType.MINION)
    bodies={NEFARIAN:nefarian,YSIEL:lambda c:(AddCostModifier(c.player_id,
        CostSpec(set_to=1,card_types=(CardType.SPELL,)),source_id=c.source_id,expires_turn=c.state.turn),),
        BARISTA:barista,JEPETTO:lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,
            (DrawGroupSlot(PoolQuery(kinds=(CardType.MINION,))),)*2,DrawGroupReward('set_stats_cost_all',1)),),
        YREL:yrel,KIRI:lambda c:(AddToHand(c.player_id,SOLAR,c.source_id),AddToHand(c.player_id,LUNAR,c.source_id)),
        SHEKZARA:lambda c:(ChooseFromZone(c.player_id,c.player_id,Zone.DECK,operation='draw',distinct='card',
            discovery=True,source_id=c.source_id,selected_reward='draw_all_copies'),),TENWU:tenwu,
        DEATHWING:lambda c:(AttackAllOtherMinions(BoardPresenceReference.capture(c.state,c.source_id)),),
        VARDEN:varden,CARIEL:cariel,HOBART:hobart,
        TAIL:lambda c:(Damage(c.target_id,4,c.source_id,DamageKind.SPELL),)}
    for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
