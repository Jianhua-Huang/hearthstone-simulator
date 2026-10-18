"""Native history, hand, split damage and named source consumers."""
import json
from pathlib import Path
from hs_sim.engine.effects import Buff,Damage,DamageBatch,GrantKeyword,GrantSpellDamage,InvokeBehavior,RandomDamage
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import is_honorable_kill
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import CardDefinition,CardType,CostSpec,EndTurnSpec,HandProgressSpec,Keyword,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery,SummonFromPool
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE,RandomSplitDamage
from hs_sim.engine.model import DamageKind
from hs_sim.engine.spell_casts import accepted_cast
from hs_sim.engine.summon_quantities import SummonCause,card_summon
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.engine.zones import CardReference,CopyCard,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,deathrattle_position,minions

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p86-v1.json'
BATCH_HASH='4672bbb354cb73d1814a07facba156ddc32fb92ffa0417dce4902c51597c1056'
SARAAD,KNIGHT,HIPPO,RUMBLER,AZERITE,VILLAIN,BLASTFISHER,MANTLE,PRIESTESS,ANTAEN,SHREDDER,AZALINA=(
 'AT_127','AV_131','AV_215','BT_114','DAL_548','DAL_749','DED_007','DEEP_004','BT_493','BT_934','GVG_096','GIL_198')
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=DEPENDENCIES=ROOTS=(SARAAD,KNIGHT,HIPPO,RUMBLER,AZERITE,VILLAIN,BLASTFISHER,MANTLE,PRIESTESS,ANTAEN,SHREDDER,AZALINA)
DEFERRED=('BT_495',)
POOL_ID='constructed.cards'
PREFIX='cards.simple_followup_p86.'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or tuple(x['record']['id']for x in d['dependencies'])!=ROOTS or tuple(x['card_id']for x in d['skipped'])!=DEFERRED:
  raise TargetValidationError('P86 complete assigned scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P86 complete original row changed')
 return d

def register_simple_followup_p86_cards(registry):
 d=load_batch()
 def saraad(c):return(GenerateFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.SPELL,),collectible=True),source_id=c.source_id),)if is_inspire(c.state,c.event,c.player_id)else()
 def rumbler(c):
  previous=next((x for x in reversed(c.state.owner_turn_history)if x.player_id==c.player_id and x.closed),None)
  qualified=previous is not None and any(x.player_id==c.player_id and x.owner_turn_id==previous.id and x.payload_started and x.failure is None for x in c.state.cast_history)
  return(DamageBatch(tuple(Damage(i,2,c.source_id,DamageKind.MINION_ABILITY)for p in(1,2)for i in minions(c,registry,p)if i!=c.source_id)),)if qualified else()
 def villain(c):
  if c.deathrattle is None:raise ResolutionError('Recurring Villain needs its original Deathrattle acceptance')
  attack=c.death.attack if c.death is not None else c.source.attack
  return(card_summon(c,c.player_id,VILLAIN,deathrattle_position(c)),)if attack>=4 else()
 def blastfisher(c):
  count=1+sum(has_any_tribe(registry,c.state.entities[i],('beast',))for i in minions(c,registry,c.player_id))
  return tuple(InvokeBehavior(PREFIX+'blast_now',c.source_id,c.player_id)for _ in range(count))
 def own_cast(c):
  cast=accepted_cast(c.state,c.event);return cast is not None and cast.player_id==c.player_id
 def discount(c):return(ModifyStoredCost(CardReference.capture(c.source),CostSpec(delta=-1),c.source_id),)
 def azalina(c):
  own=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[c.player_id].hand)
  other=tuple(CardReference.capture(c.state.entities[i])for i in c.state.players[3-c.player_id].hand)
  return(RemoveFromGame(own,c.source_id),*(CopyCard(ref,c.player_id,source_id=c.source_id)for ref in other))
 bodies=dict(saraad=saraad,knight=lambda c:()if c.target_id is None else(Damage(c.target_id,3,c.source_id,DamageKind.MINION_ABILITY),),
  knight_honor=lambda c:(Buff(c.source_id,3,3,c.source_id),)if is_honorable_kill(c.event,c.source_id)else(),hippo=lambda c:(GrantKeyword(c.source_id,Keyword.WINDFURY,c.source_id),)if is_honorable_kill(c.event,c.source_id)else(),
  rumbler=rumbler,azerite=lambda c:(GrantSpellDamage(c.source_id,2,c.source_id),)if c.event.player_id==c.player_id else(),villain=villain,blastfisher=blastfisher,
  blast_now=lambda c:(RandomDamage(characters(c,registry,3-c.player_id),2,c.source_id,DamageKind.MINION_ABILITY),),discount=discount,
  priestess=lambda c:(RandomSplitDamage(c.player_id,None,c.source_id,6,profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY),),
  antaen=lambda c:(RandomSplitDamage(c.player_id,None,c.source_id,10,profile=NON_SPELL_PROFILE,kind=DamageKind.MINION_ABILITY),),
  shredder=lambda c:(SummonFromPool(c.player_id,POOL_ID,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=2,max_cost=2),source_id=c.source_id,cause=SummonCause.capture(c),position=deathrattle_position(c)),),azalina=azalina)
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 registry.register_trigger_condition(PREFIX+'own_cast',own_cast)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={}
  if cid==SARAAD:kw['triggers']=(TriggerSpec('hero_power_used',PREFIX+'saraad'),)
  if cid==KNIGHT:kw.update(battlecry=PREFIX+'knight',targeting=TargetSpec(TargetMode.IF_AVAILABLE),triggers=(TriggerSpec('health_resolved',PREFIX+'knight_honor'),))
  if cid==HIPPO:kw.update(keywords=(Keyword.RUSH,),triggers=(TriggerSpec('health_resolved',PREFIX+'hippo'),))
  if cid in(RUMBLER,BLASTFISHER,AZALINA):kw['battlecry']=PREFIX+{RUMBLER:'rumbler',BLASTFISHER:'blastfisher',AZALINA:'azalina'}[cid]
  if cid in(VILLAIN,SHREDDER):kw['deathrattle']=PREFIX+{VILLAIN:'villain',SHREDDER:'shredder'}[cid]
  if cid==AZERITE:kw['triggers']=(TriggerSpec('turn_started',PREFIX+'azerite'),)
  if cid==MANTLE:kw['hand_progress']=HandProgressSpec('event',1,on_complete=PREFIX+'discount',repeat=True,event='spell_cast_accepted',condition_id=PREFIX+'own_cast')
  if cid==PRIESTESS:kw['triggers']=(TriggerSpec('turn_ended',PREFIX+'priestess',EndTurnSpec()),)
  if cid==ANTAEN:kw.update(dormant_turns=2,on_awaken=PREFIX+'antaen')
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
