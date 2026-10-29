"""Original Shaman life, physical hand returns, draw resources and Asteroids."""
from dataclasses import asdict
import hashlib,json
from pathlib import Path

from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.copy_materials import CopyEntryMaterial
from hs_sim.engine.death_hand_returns import ReturnDeadMinion
from hs_sim.engine.effects import AddCostModifier,Damage,DamageBatch,Destroy,Draw,Heal,RandomDamage,ReturnToHand
from hs_sim.engine.model import CardAbilityCondition,CardDefinition,CardType,CastWhenDrawnSpec,CostSpec,DamageKind,HandRepeatSpec,HealingKind,Keyword,PlayedTypeQuery,PlayerEffectSpec,SpellSchool,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.owner_turns import query_previous_owner_turn
from hs_sim.engine.physical_draw_groups import DrawGroupReward,DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.player_effects import AddPlayerEffect,RemovePlayerEffect,spell_effect_values
from hs_sim.engine.pools import PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.sacrifice import GrantCapturedDeathrattle,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause
from hs_sim.engine.summon_sources import ResurrectMinion
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import minions

ROOT=Path(__file__).resolve().parents[2]
BATCH_PATH=ROOT/'data/cards/past-shaman-life-draw-v1.json'
BATCH_HASH='5590e7f4434ce4b80cfdefd98b4a305f73738392282c5b40bf1071be14919552'
ROOTS=('FP1_025','WON_335','BT_101','UNG_956','DAL_432','TOY_506','BOT_093','TTN_830','GDB_445')
DEPENDENCIES=('GDB_430',)
PREFIX='cards.past_shaman_life_draw.'
TARGETED=('FP1_025','WON_335','DAL_432')
NATURE_PRICE=CostSpec(delta=-1,card_types=(CardType.SPELL,),ability=CardAbilityCondition('nature_spell',basis='printed'))
PENDING=PREFIX+'pending_nature'


def make_definition(raw):
    cid=raw['id'];fields={}
    if (cid not in ROOTS+DEPENDENCIES or raw['type']!='SPELL' or raw['collectible']is not(cid in ROOTS)or
            raw['tags'].get('SPELL_SCHOOL')!=(4 if cid in ROOTS else None)or type(raw['cost'])is not int):
        raise TargetValidationError('Shaman life/draw requires complete original spell roles and schools')
    if cid in TARGETED:fields['targeting']=TargetSpec()if cid=='DAL_432'else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))
    if cid=='DAL_432':fields['hand_repeat']=HandRepeatSpec(echo=False)
    if cid=='GDB_430':
        if raw['tags'].get('CASTS_WHEN_DRAWN')!=1 or raw['tags'].get('TAG_SCRIPT_DATA_NUM_1')!=2:
            raise TargetValidationError('Asteroid lost its original automatic draw or base two damage')
        fields.update(keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
    return CardDefinition(cid,raw['name'],CardType.SPELL,cost=raw['cost'],on_play=PREFIX+cid,
        spell_school=SpellSchool.NATURE if cid in ROOTS else None,metadata=metadata_from_record(raw),**fields)


def pending_spec():return PlayerEffectSpec(PENDING,'TTN_830',triggers=(TriggerSpec('turn_started',PREFIX+'activate_nature'),))


def load_batch():
    d=json.loads(BATCH_PATH.read_text(encoding='utf8'))
    if (canonical_digest(d)!=BATCH_HASH or d['schema']!=1 or tuple(v['record']['id']for v in d['cards'])!=ROOTS or
            tuple(v['record']['id']for v in d['dependencies'])!=DEPENDENCIES or d['evidence_only']or
            [v['record']['id']for v in d['existing_dependencies']]!=['TIME_013']or
            len(d['official_observations'])!=22 or d['numeric_normalizations']or
            len(d['original_shaman_member_ids'])!=71 or any(cid not in d['original_shaman_member_ids']for cid in ROOTS)or
            d['pending_profile_sha256']!=canonical_digest(asdict(pending_spec()))or
            any(d[k]for k in('complete_shaman_source_bound','new_standard_roots','membership_uses_executable_coverage','formal_pool_complete','cn_calibrated'))):
        raise TargetValidationError('Shaman life/draw changed complete source roles or claimed partial support complete')
    for row in d['cards']+d['dependencies']+d['existing_dependencies']:
        if canonical_digest(row['record'])!=row['record_sha256']:raise TargetValidationError('Shaman life/draw lost a complete original row')
    p=(ROOT/d['full_union_source_document']).resolve()
    if not p.is_relative_to(ROOT)or hashlib.sha256(p.read_bytes()).hexdigest()!=d['full_union_source_sha256']:
        raise TargetValidationError('Shaman life/draw changed the original full source reference')
    return d


def register_past_shaman_life_draw(registry):
    d=load_batch();prepared=[]
    for row in d['cards']+d['dependencies']:
        card=make_definition(row['record'])
        if card.id in registry.cards or canonical_digest(asdict(card))!=row['definition_sha256']:
            raise TargetValidationError('Shaman life/draw cannot replace or alter a complete native face')
        registry._validate_card(card)
        if card.id in registry.pool_cards and registry.pool_card(card.id)!=PoolCard.from_definition(card):raise TargetValidationError('Shaman life/draw changed complete existing metadata')
        prepared.append(card)
    def base_material(c,entity):return CopyEntryMaterial.capture(c.state,entity,'base_resummon','base',registry=registry,player_id=entity.controller)
    def reincarnate(c):
        target=c.state.entities[c.target_id];material=base_material(c,target)
        return(Destroy(target.id,c.source_id),SummonByCard(target.controller,(material,),SummonCause.capture(c)))
    def grant(c,body):return tuple(GrantCapturedDeathrattle(MinionReference.capture(c.state.entities[eid]),PREFIX+body,c.source_id)for eid in minions(c,registry,c.player_id))
    def spores(c):
        if c.deathrattle is None:raise TargetValidationError('Living Spores requires its original actual Deathrattle invocation')
        cause=SummonCause.capture(c)
        if c.death is not None:return(ResurrectMinion(c.player_id,c.death.id,position=c.death.position,source_id=c.source_id,cause=cause),)
        if c.source.zone not in(Zone.BOARD,Zone.HAND,Zone.DECK):raise TargetValidationError('Living Spores has no actual natural death or current minion')
        return(SummonByCard(c.player_id,(base_material(c,c.source),),cause),)
    def echo(c):
        if c.deathrattle is None:raise TargetValidationError('Spirit Echo requires its original actual Deathrattle invocation')
        if c.death is not None:
            source=c.source;origin=c.death.copy_source.origin
            if (source.zone,source.card_id,source.zone_epoch,source.entered_order)!=(Zone.GRAVEYARD,origin.card_id,origin.zone_epoch+1,origin.entered_order):return()
            fact=SourceAllocationFact.capture(c.state,source)
            return(ReturnDeadMinion(c.death.id,fact,fact),)
        if c.source.zone==Zone.BOARD:return(ReturnToHand(c.source_id),)
        if c.source.zone==Zone.DECK:return(MoveCard(CardReference.capture(c.source),c.player_id,Zone.HAND,reset=True,source_id=c.source_id),)
        return()
    def once(c):return tuple(SummonFromPool(c.player_id,'constructed.cards',PoolQuery(kinds=(CardType.MINION,),min_cost=3,max_cost=3,tribes_any=(tribe,),collectible=True),source_id=c.source_id,cause=SummonCause.capture(c))for tribe in('beast','dragon','elemental','murloc'))
    def reaction(c):
        enabled=query_previous_owner_turn(c.state,c.player_id,PlayedTypeQuery(CardType.MINION,('elemental',))).matched
        return(DrawPhysicalGroup(c.player_id,c.source_id,(DrawGroupSlot(),),DrawGroupReward('copy_self')if enabled else DrawGroupReward()),)
    def activate(c):
        if c.event.player_id!=c.player_id:return()
        return(RemovePlayerEffect(c.player_id,c.player_effect.id),AddCostModifier(c.player_id,NATURE_PRICE,source_id=c.source_id,expires_turn=c.state.turn))
    def meteor(c):
        damage=DamageBatch(tuple(Damage(eid,5,c.source_id,DamageKind.SPELL)for p in(1,2)for eid in minions(c,registry,p)))
        return(damage,)+(AddToDeck(c.player_id,'GDB_430',source_id=c.source_id),)*5
    def asteroid(c):
        value,count=spell_effect_values(c.state,registry,c.cast,2)
        candidates=(c.state.players[3-c.player_id].hero_id,*minions(c,registry,3-c.player_id))
        return(RandomDamage(candidates,value,c.source_id,DamageKind.SPELL),)*count
    bodies={'FP1_025':reincarnate,'WON_335':reincarnate,'BT_101':lambda c:grant(c,'spores'),'UNG_956':lambda c:grant(c,'echo'),
        'spores':spores,'echo':echo,'DAL_432':lambda c:(Heal(c.target_id,4,c.source_id,HealingKind.SPELL),),
        'TOY_506':once,'BOT_093':reaction,'TTN_830':lambda c:(Draw(c.player_id,1,c.source_id),AddPlayerEffect(c.player_id,PENDING,c.source_id)),
        'activate_nature':activate,'GDB_445':meteor,'GDB_430':asteroid}
    for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
    registry.register_player_effect(pending_spec())
    for card in prepared:
        registry.register_card(card)
        if card.id not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(card))
