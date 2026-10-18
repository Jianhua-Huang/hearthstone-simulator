"""Actual health/owner-turn sources, native random rewards and shared batches."""
import json
from pathlib import Path
from hs_sim.engine.cross_zone import RandomBuffStoredMinion
from hs_sim.engine.effects import Damage,DamageBatch,InvokeBehavior,RandomBuff
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,DamageKind,EndTurnSpec,HealthFlow,Keyword,TriggerSpec
from hs_sim.engine.pools import GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position,minions

BUTTERFLY,DEPTH,WARDEN,PRIESTESS,BALLOON,ZEALOT,BROOM,HATCHLING,BOMBER,VILLAGER,TENTACLE=('DAL_587','DRG_078','EX1_001','EX1_004','DRG_057','OG_158','SCH_311','TRL_505','GVG_009','OG_241','OG_151')
SHADOW='OG_241a';ROOTS=(BUTTERFLY,DEPTH,WARDEN,PRIESTESS,BALLOON,ZEALOT,BROOM,HATCHLING,BOMBER,VILLAGER,TENTACLE);DEPENDENCIES=(SHADOW,);ALL_IDS=(*ROOTS,*DEPENDENCIES);COLLECTIBLE_ROOTS=()
PREFIX='cards.simple_followup_p95.';POOL_ID='constructed.cards';HUNTER_SPELLS=PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='specified',classes=(CardClass.HUNTER,),include_neutral=False)
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p95-v1.json';BATCH_HASH='87ef082ec40f039dd797b8667ceadb698a04fcb498538d614214c5a2cccad3aa'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['dependencies'])!=ALL_IDS or any(d[k]for k in('cards','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P95 complete assigned records changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies'])or d['numeric_normalizations']!={DEPTH:{'attack':0}}:raise TargetValidationError('P95 original source or sole explicit zero normalization changed')
 return d

def register_simple_followup_p95_cards(registry):
 def invoke(c,name):return(InvokeBehavior(PREFIX+name,c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),)
 def group_damage(c,amount):return(DamageBatch(tuple(Damage(i,amount,c.source_id,DamageKind.MINION_ABILITY)for p in(c.player_id,3-c.player_id)for i in minions(c,registry,p))),)
 def self_buff(c,attack=0,health=0):return(BuffCapturedMinion(MinionReference.capture(c.source),attack,health,c.source_id),)if living_source(c)else()
 def owner_start(c,name):return invoke(c,name)if c.event is not None and c.event.kind=='turn_started'and c.event.player_id==c.player_id else()
 def healed(c):
  result=c.health_result
  if result is None:raise ResolutionError('Lightwarden requires its original actual health result')
  return self_buff(c,2)if result.flow==HealthFlow.HEALING.value and result.healed>0 and result.target_kind in(CardType.HERO.value,CardType.MINION.value)else()
 def broom_now(c):return tuple(GrantCapturedKeyword(MinionReference.capture(c.state.entities[i]),Keyword.RUSH,c.source_id)for i in minions(c,registry,c.player_id)if i!=c.source_id)
 bodies={'butterfly':lambda c:(GenerateFromPool(c.player_id,POOL_ID,HUNTER_SPELLS,source_id=c.source_id),),
  'depth':lambda c:owner_start(c,'depth_now'),'depth_now':lambda c:group_damage(c,5),'warden':healed,
  'priestess':lambda c:invoke(c,'priestess_now'),'priestess_now':lambda c:(RandomBuff(tuple(i for i in minions(c,registry,c.player_id)if i!=c.source_id),0,1,c.source_id),),
  'balloon':lambda c:owner_start(c,'balloon_now'),'balloon_now':lambda c:self_buff(c,health=1),
  'zealot':lambda c:invoke(c,'zealot_now'),'zealot_now':lambda c:(RandomBuff(minions(c,registry,c.player_id),1,1,c.source_id),),
  'broom':lambda c:invoke(c,'broom_now'),'broom_now':broom_now,
  'hatchling':lambda c:(RandomBuffStoredMinion(c.player_id,query=PoolQuery(tribes_any=('beast',)),source_id=c.source_id,cost=CostSpec(delta=-1),tribe_basis='current'),),
  'bomber':lambda c:(DamageBatch(tuple(Damage(c.state.players[p].hero_id,3,c.source_id,DamageKind.MINION_ABILITY)for p in(c.player_id,3-c.player_id))),),
  'villager':lambda c:(SummonByCard(c.player_id,(SummonEntryMaterial(SHADOW),),SummonCause.capture(c),position=deathrattle_position(c)),),
  'tentacle':lambda c:invoke(c,'tentacle_now'),'tentacle_now':lambda c:group_damage(c,1)}
 for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
 for item in load_batch()['dependencies']:
  raw=item['record'];cid=raw['id'];kw={};attack=raw['attack']
  if raw['type']!='MINION'or raw['cost']!=1 or raw['collectible']!=(cid in ROOTS):raise TargetValidationError('P95 printed complete kind/cost changed')
  if cid==DEPTH:
   if attack is not None or 'ATK'in raw['tags']:raise TargetValidationError('P95 zero Attack must retain missing original ATK')
   attack=0
  if cid in(BUTTERFLY,ZEALOT,HATCHLING,VILLAGER,TENTACLE):kw['deathrattle']=PREFIX+{BUTTERFLY:'butterfly',ZEALOT:'zealot',HATCHLING:'hatchling',VILLAGER:'villager',TENTACLE:'tentacle'}[cid]
  if cid in(BROOM,BOMBER):kw['battlecry']=PREFIX+('broom'if cid==BROOM else'bomber')
  if cid==BROOM:kw['keywords']=(Keyword.RUSH,)
  if cid in(DEPTH,BALLOON,WARDEN):kw['triggers']=(TriggerSpec('health_resolved'if cid==WARDEN else'turn_started',PREFIX+{DEPTH:'depth',BALLOON:'balloon',WARDEN:'warden'}[cid]),)
  if cid==PRIESTESS:kw['triggers']=(TriggerSpec('turn_ended',PREFIX+'priestess',EndTurnSpec()),)
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=attack,health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
