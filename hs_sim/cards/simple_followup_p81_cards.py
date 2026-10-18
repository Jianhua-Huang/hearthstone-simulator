"""Real five-cost native stat, survival, Inspire and cost consumers."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,Buff,CopyMinion,Damage,DamageBatch,DoubleStats,Draw,GrantKeyword,InvokeBehavior
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,CostAuraSpec,CostSpec,DamageKind,EndTurnSpec,HealthFlow,Keyword,LimitedTriggerSpec,TriggerSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonCause,card_summon
from hs_sim.engine.zones import CardReference,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p81-v1.json'
BATCH_HASH='ab8afdd28dc7496eef586c77c9e9127a4353301b697747ec97cbafc881dcb23a'
FIEND,RECRUITER,EMPEROR,WARLORD,VENTURE,SCRAP,HOG,DOPPEL,PATRON,STONEMAUL,FORTUNE,LURKER=(
 'AT_012','AT_113','BRM_028','CS2_226','CS2_227','BT_720','CFM_688','CFM_668','BRM_019','BAR_896','DMF_121','ULD_189')
SQUIRE='CS2_152'
COLLECTIBLE_ROOTS=()
DEPENDENCIES=ROOTS=(FIEND,RECRUITER,EMPEROR,WARLORD,VENTURE,SCRAP,HOG,DOPPEL,PATRON,STONEMAUL,FORTUNE,LURKER)
PREFIX='cards.simple_followup_p81.'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if(canonical_digest(d)!=BATCH_HASH or d['cards'] or d['skipped'] or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES
   or tuple(x['record']['id']for x in d['existing_dependencies'])!=(SQUIRE,)):
  raise TargetValidationError('P81 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):
  raise TargetValidationError('P81 complete original source record changed')
 return d

def register_simple_followup_p81_cards(registry):
 d=load_batch()
 if canonical_digest(asdict(registry.card(SQUIRE)))!=d['existing_dependency_definition_pins'][SQUIRE]['sha256']:
  raise TargetValidationError('P81 requires unchanged original CS2_152 dependency')
 def fiend(c):
  return(DamageBatch(tuple(Damage(c.state.players[p].hero_id,4,c.source_id,DamageKind.MINION_ABILITY)for p in(1,2))),)
 def buff(c,n):
  return(BuffCapturedMinion(MinionReference.capture(c.source),n,n,c.source_id),)if n and living_source(c)else()
 def warlord(c):
  return buff(c,sum(c.state.entities[i].kind==CardType.MINION and i!=c.source_id for i in c.state.players[c.player_id].board))
 def fortune(c):return buff(c,sum(c.state.entities[i].kind==CardType.SPELL for i in c.state.players[c.player_id].hand))
 def hog(c):
  return(GrantKeyword(c.source_id,Keyword.CHARGE,c.source_id),)if living_source(c)and any(Keyword.TAUNT in c.state.entities[i].keywords for i in minions(c,registry,3-c.player_id))else()
 def doppel(c):
  if not living_source(c):return()
  ref=BoardPresenceReference.capture(c.state,c.source_id);cause=SummonCause.capture(c)
  return(CopyMinion(ref,c.player_id,cause=cause),CopyMinion(ref,c.player_id,cause=cause))
 def patron(c):
  result=c.health_result
  if result is None:raise ResolutionError('Patron requires original actual HealthResult')
  if(result.target_id!=c.source_id or result.target_kind!=CardType.MINION.value or result.flow!=HealthFlow.DAMAGE.value
    or result.damage_dealt<=0 or result.health_after<=0 or result.doomed_after or not living_source(c)):
   return()
  if(result.target_card_id,result.target_zone_epoch,result.target_entered_order)!=(c.source.card_id,c.source.zone_epoch,c.source.entered_order):return()
  return(card_summon(c,c.player_id,PATRON),)
 def emperor_now(c):
  return tuple(ModifyStoredCost(CardReference.capture(c.state.entities[i]),CostSpec(delta=-1),c.source_id)for i in c.state.players[c.player_id].hand)
 bodies=dict(fiend=fiend,fiend_inspire=lambda c:fiend(c)if is_inspire(c.state,c.event,c.player_id)else(),
  recruiter=lambda c:(AddToHand(c.player_id,SQUIRE,c.source_id),)if is_inspire(c.state,c.event,c.player_id)else(),
  emperor=lambda c:(InvokeBehavior(PREFIX+'emperor_now',c.source_id,c.player_id),),emperor_now=emperor_now,
  warlord=warlord,fortune=fortune,hog=hog,doppel=doppel,patron=patron,
  scrap=lambda c:(Buff(c.source_id,attack=4,source_id=c.source_id,expires_turn=c.state.turn),)if living_source(c)else(),
  lurker=lambda c:(DoubleStats(c.source_id,health=True,source_id=c.source_id),)if living_source(c)else(),
  stonemaul=lambda c:(Draw(c.player_id,source_id=c.source_id),))
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 battlecries={FIEND:'fiend',WARLORD:'warlord',FORTUNE:'fortune',HOG:'hog',DOPPEL:'doppel',SCRAP:'scrap',LURKER:'lurker'}
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={}
  if cid in battlecries:kw['battlecry']=PREFIX+battlecries[cid]
  if cid in(FIEND,RECRUITER):kw['triggers']=(TriggerSpec('hero_power_used',PREFIX+('fiend_inspire'if cid==FIEND else'recruiter')),)
  if cid==EMPEROR:kw['triggers']=(TriggerSpec('turn_ended',PREFIX+'emperor',EndTurnSpec()),)
  if cid==PATRON:kw['triggers']=(TriggerSpec('health_resolved',PREFIX+'patron'),)
  if cid==STONEMAUL:kw.update(keywords=(Keyword.RUSH,Keyword.FRENZY),limited_triggers=(LimitedTriggerSpec.frenzy(PREFIX+'stonemaul'),))
  if cid==SCRAP:kw['keywords']=(Keyword.TAUNT,Keyword.RUSH)
  if cid in(FORTUNE,LURKER):kw['keywords']=(Keyword.TAUNT,)
  if cid==VENTURE:kw['cost_auras']=(CostAuraSpec(CostSpec(delta=3,card_types=(CardType.MINION,))),)
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
