"""Native physical draws, original health/Frenzy, spell starts and named deaths."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,ChoiceOption,ForceAttack,GainArmor,InvokeBehavior,RandomDestroy,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,HealthFlow,Keyword,LimitedTriggerSpec,SpellSchool,TriggerSpec
from hs_sim.engine.physical_draw_groups import DrawGroupSlot,DrawPhysicalGroup
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.summon_quantities import card_summon
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions,characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p82-v1.json'
BATCH_HASH='b859223f3505c6496cac375a49e75c33e3babd10a74697ce76f0b706bba32f55'
GUIDE,RAIDER,SMITH,KODO,BULLY,ARMOR,INFIL,WHATLEY,ACOLYTE,INVENTOR=(
 'AV_328','BAR_020','BAR_073','BAR_551','CFM_669','CFM_756','DAL_039','DMF_525','BAR_072','BOT_270')
DEMON,ANNOY,COIN='BAR_072t','BOT_270t','GAME_005'
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=(GUIDE,RAIDER,SMITH,KODO,BULLY,ARMOR,INFIL,WHATLEY,ACOLYTE,INVENTOR)
STATIC_TOKENS=(DEMON,ANNOY)
DEPENDENCIES=ROOTS=COLLECTIBLE_DEPENDENCIES+STATIC_TOKENS
DEFERRED=('DAL_726','DMF_231')
PREFIX='cards.simple_followup_p82.'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if(canonical_digest(d)!=BATCH_HASH or d['cards'] or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES
    or tuple(x['record']['id']for x in d['existing_dependencies'])!=(COIN,)or tuple(x['card_id']for x in d['skipped'])!=DEFERRED):
  raise TargetValidationError('P82 complete reviewed source scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P82 complete original record changed')
 return d

def register_simple_followup_p82_cards(registry):
 d=load_batch()
 if canonical_digest(asdict(registry.card(COIN)))!=d['existing_dependency_definition_pins'][COIN]['sha256']:raise TargetValidationError('P82 requires unchanged existing GAME_005')
 def draw(c,queries):return(DrawPhysicalGroup(c.player_id,c.source_id,tuple(DrawGroupSlot(q)for q in queries)),)
 def raider(c):
  if not living_source(c):return()
  source=BoardPresenceReference.capture(c.state,c.source_id)
  options=tuple(ChoiceOption(json.dumps(dict(attacker=asdict(source),defender=asdict(BoardPresenceReference.capture(c.state,i))if c.state.entities[i].kind==CardType.MINION else i),sort_keys=True),'Original enemy character',entity_id=i)for i in characters(c,registry,3-c.player_id))
  return(RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,sample_size=1,on_select=PREFIX+'raider_selected'),)if options else()
 def raider_selected(c):
  if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:raise ResolutionError('Raider lost original automatic selection')
  row=json.loads(c.choice.choice.options[0].id)
  defender=BoardPresenceReference(**row['defender'])if type(row['defender'])is dict else row['defender']
  return(ForceAttack(BoardPresenceReference(**row['attacker']),defender),)
 def armor(c):
  h=c.health_result
  if h is None:raise ResolutionError('Armorsmith requires original actual health result')
  return(GainArmor(c.player_id,h.damage_dealt),)if h.source_id==c.source_id and h.flow==HealthFlow.DAMAGE.value and h.damage_dealt>0 else()
 def bully(c):
  row=cast_record(c.state,dict(c.event.data)['cast_id'])
  if(row.source_id,row.player_id)!=(c.event.source_id,c.event.player_id)or registry.card(row.card_id).kind!=CardType.SPELL:raise ResolutionError('Bully lost original spell activation')
  return(AddToHand(c.player_id,COIN,c.source_id),)if row.player_id!=c.player_id else()
 bodies=dict(guide=lambda c:draw(c,tuple(PoolQuery(kinds=(CardType.SPELL,),spell_schools=(s,))for s in(SpellSchool.HOLY,SpellSchool.SHADOW))),
  kodo=lambda c:(DrawPhysicalGroup(c.player_id,c.source_id,tuple(DrawGroupSlot(PoolQuery(kinds=(CardType.SPELL,)),current_cost=n)for n in(1,2,3))),),
  whatley=lambda c:draw(c,tuple(PoolQuery(kinds=(CardType.MINION,),tribes_any=(t,))for t in('mech','dragon','pirate'))),
  raider=raider,raider_selected=raider_selected,smith=lambda c:tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),2,2,c.source_id)for i in minions(c,registry,c.player_id)if i!=c.source_id),
  armor=armor,bully=bully,infil=lambda c:(InvokeBehavior(PREFIX+'infil_now',c.source_id,c.player_id),),infil_now=lambda c:(RandomDestroy(minions(c,registry,3-c.player_id),c.source_id),),
  acolyte=lambda c:(card_summon(c,c.player_id,DEMON),),inventor=lambda c:(card_summon(c,c.player_id,ANNOY),card_summon(c,c.player_id,ANNOY)))
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={}
  if cid in(GUIDE,ARMOR,INFIL,DEMON):kw['keywords']=(Keyword.TAUNT,)
  if cid==ANNOY:kw['keywords']=(Keyword.TAUNT,Keyword.DIVINE_SHIELD)
  if cid in(RAIDER,SMITH):kw.update(keywords=(Keyword.FRENZY,),limited_triggers=(LimitedTriggerSpec.frenzy(PREFIX+('raider'if cid==RAIDER else'smith')),))
  if cid in(KODO,WHATLEY,INVENTOR):kw['battlecry']=PREFIX+{KODO:'kodo',WHATLEY:'whatley',INVENTOR:'inventor'}[cid]
  if cid in(GUIDE,INFIL,ACOLYTE):kw['deathrattle']=PREFIX+{GUIDE:'guide',INFIL:'infil',ACOLYTE:'acolyte'}[cid]
  if cid==ARMOR:kw['triggers']=(TriggerSpec('health_resolved',PREFIX+'armor'),)
  if cid==BULLY:kw['triggers']=(TriggerSpec('spell_cast_started',PREFIX+'bully'),)
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
