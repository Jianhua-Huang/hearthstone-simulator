"""Original health/death/attack consumers and native ordinary five-cost bodies."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.effects import ChoiceOption,Damage,DamageBatch,Heal,InvokeBehavior,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,EndTurnSpec,HealingKind,HealthFlow,Keyword,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,FreezeCapturedMinion,MinionReference,live_minion
from hs_sim.engine.secrets import RemoveSecret
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import completed_attack,living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p80-v1.json'
BATCH_HASH='8a49217c186ebef75a55715f8c6d1444fbdb0e201efe14ac87f1dbd6bf75c2f2'
HEALBOT,APPLEBAUM,LOBBER,SCORCHER,SQUAD,HYDRA,DREADLORD,WATCHER,CRUSHER,GUARD,INSPECTOR,JUNKBOT=(
 'OG_147','GIL_667','GVG_099','TRL_526','CFM_667','UNG_087','ICC_075','GVG_100','UNG_079','AV_129','GIL_648','GVG_106')
COLLECTIBLE_ROOTS=()
DEPENDENCIES=ROOTS=(HEALBOT,APPLEBAUM,LOBBER,SCORCHER,SQUAD,HYDRA,DREADLORD,WATCHER,CRUSHER,GUARD,INSPECTOR,JUNKBOT)
PREFIX='cards.simple_followup_p80.'
def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['existing_dependencies']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES:
  raise TargetValidationError('P80 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P80 complete original record changed')
 return d
def register_simple_followup_p80_cards(registry):
 d=load_batch()
 def hero(c,pid):return c.state.players[pid].hero_id
 def hit(c,target,n):return Damage(target,n,c.source_id,DamageKind.MINION_ABILITY)
 def health(c):
  result=c.health_result
  if result is None:raise ResolutionError('P80 health reaction requires its original result')
  return result
 def own_hit(c):
  result=health(c)
  return result.target_id==c.source_id and result.target_kind==CardType.MINION.value and result.flow==HealthFlow.DAMAGE.value and result.damage_dealt>0
 def lobber(c):
  refs=tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,3-c.player_id))
  options=tuple(ChoiceOption(json.dumps(asdict(ref),sort_keys=True),'Original enemy minion',entity_id=ref.entity_id)for ref in refs)
  return(RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,sample_size=1,on_select=PREFIX+'lobber_selected'),)if options else()
 def lobber_selected(c):
  if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:raise ResolutionError('Lobber lost its original sampled enemy minion')
  ref=MinionReference(**json.loads(c.choice.choice.options[0].id))
  return(hit(c,ref.entity_id,4),)if live_minion(c.state,ref)is not None else()
 def guard(c):
  return tuple(BuffCapturedMinion(MinionReference.capture(c.state.entities[i]),1,0,c.source_id)for i in minions(c,registry,c.player_id))if own_hit(c)else()
 def watcher(c):
  result=health(c)
  if(result.flow!=HealthFlow.DAMAGE.value or result.damage_dealt<=0 or result.target_kind!=CardType.HERO.value
    or result.target_controller!=c.player_id or result.active_player!=c.player_id or not living_source(c)):return()
  return(BuffCapturedMinion(MinionReference.capture(c.source),2,2,c.source_id),)
 def crusher(c):
  row=completed_attack(c)
  if row is None or row.declaration.source_id!=c.source_id or not living_source(c):return()
  if(row.source_card_id,row.source_zone_epoch,row.source_entered_order)!=(c.source.card_id,c.source.zone_epoch,c.source.entered_order):return()
  return(FreezeCapturedMinion(MinionReference.capture(c.source),c.source_id),)
 def junkbot(c):
  ident=dict(c.event.data)['death_id'];row=next((r for r in c.state.death_history if r.id==ident),None)
  if row is None or(row.entity_id,row.controller)!=(c.event.source_id,c.event.player_id):raise ResolutionError('Junkbot lost its original DeathRecord')
  if row.controller!=c.player_id or not living_source(c)or not has_any_tribe(registry,row,('mech',)):return()
  return(BuffCapturedMinion(MinionReference.capture(c.source),2,2,c.source_id),)
 bodies=dict(healbot=lambda c:(Heal(hero(c,3-c.player_id),8,c.source_id,HealingKind.EFFECT),),applebaum=lambda c:(Heal(hero(c,c.player_id),6,c.source_id,HealingKind.EFFECT),),
  lobber=lobber,lobber_selected=lobber_selected,scorcher=lambda c:(DamageBatch(tuple(hit(c,i,1)for p in(1,2)for i in minions(c,registry,p)if i!=c.source_id)),),
  squad=lambda c:()if c.target_id is None else(hit(c,c.target_id,5),),squad_death=lambda c:(hit(c,hero(c,c.player_id),5),),
  hydra=lambda c:(hit(c,hero(c,c.player_id),3),)if own_hit(c)else(),guard=guard,watcher=watcher,crusher=crusher,junkbot=junkbot,
  dreadlord=lambda c:(InvokeBehavior(PREFIX+'dreadlord_now',c.source_id,c.player_id),),dreadlord_now=lambda c:(DamageBatch(tuple(hit(c,i,1)for i in minions(c,registry,3-c.player_id))),),
  inspector=lambda c:tuple(RemoveSecret(i)for i in c.state.players[3-c.player_id].secrets))
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 battlecries={LOBBER:'lobber',SCORCHER:'scorcher',SQUAD:'squad',INSPECTOR:'inspector'}
 deaths={HEALBOT:'healbot',APPLEBAUM:'applebaum',SQUAD:'squad_death'}
 reactions={HYDRA:('health_resolved','hydra'),GUARD:('health_resolved','guard'),WATCHER:('health_resolved','watcher'),CRUSHER:('attack_finished','crusher'),JUNKBOT:('minion_died','junkbot')}
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={}
  if cid in battlecries:kw['battlecry']=PREFIX+battlecries[cid]
  if cid in deaths:kw['deathrattle']=PREFIX+deaths[cid]
  if cid==APPLEBAUM:kw['keywords']=(Keyword.TAUNT,)
  if cid==SQUAD:kw['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy')
  if cid in reactions:kw['triggers']=(TriggerSpec(reactions[cid][0],PREFIX+reactions[cid][1]),)
  if cid==DREADLORD:kw['triggers']=(TriggerSpec('turn_ended',PREFIX+'dreadlord',EndTurnSpec()),)
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
