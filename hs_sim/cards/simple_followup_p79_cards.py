"""Finite real stat-buff dependencies over native references and completion facts."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope,RandomBuffStoredMinion
from hs_sim.engine.effects import ChoiceOption,RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.inspire import is_inspire
from hs_sim.engine.model import CardDefinition,CardType,TargetMode,TargetSpec,TriggerSpec,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.engine.tribes import has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import minions,characters

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p79-v1.json'
BATCH_HASH='b2d7b224ce24b2d3c0ba21e59f84efeb2296de64acd52f9ee3b9a375aee5474f'
KNIGHT,REPAIR,FUNGAL,TECH,SPEAKER,HAN,CHAMPION,VALIANT,SENTINEL,CRYO,REVENANT,WYRM=(
 'AT_096','GVG_083','LOOT_167','BOT_910','DAL_147','CFM_685','AT_090','AT_049','LOE_061','CFM_671','ICC_450','CFM_060')
COLLECTIBLE_ROOTS=()
DEPENDENCIES=ROOTS=(KNIGHT,REPAIR,FUNGAL,TECH,SPEAKER,HAN,CHAMPION,VALIANT,SENTINEL,CRYO,REVENANT,WYRM)
PREFIX='cards.simple_followup_p79.'
def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['existing_dependencies']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES:
  raise TargetValidationError('P79 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P79 complete original record changed')
 return d
def register_simple_followup_p79_cards(registry):
 d=load_batch()
 def buff(c,eid,a,h):return BuffCapturedMinion(MinionReference.capture(c.state.entities[eid]),a,h,c.source_id)
 def targeted(c,a,h):return ()if c.target_id is None else(buff(c,c.target_id,a,h),)
 def fungal(c):
  if not living_source(c):return()
  board=c.state.players[c.player_id].board;index=board.index(c.source_id)
  adjacent={board[i]for i in(index-1,index+1)if 0<=i<len(board)}
  return tuple(buff(c,i,2,2)for i in minions(c,registry,c.player_id)if i in adjacent)
 def hand(c,a,h,tribes=()):
  return(BuffMinionsInZones(c.player_id,a,h,MinionScope((Zone.HAND,),PoolQuery(kinds=(CardType.MINION,),tribes_any=tribes),tribe_basis='current'),c.source_id),)
 def champion(c):
  return tuple(buff(c,i,1,1)for i in minions(c,registry,c.player_id)if i!=c.source_id)if is_inspire(c.state,c.event,c.player_id)else()
 def valiant(c):
  return tuple(buff(c,i,2,0)for i in minions(c,registry,c.player_id)if has_any_tribe(registry,c.state.entities[i],('totem',)))
 def sentinel(c):
  refs=tuple(MinionReference.capture(c.state.entities[i])for i in minions(c,registry,c.player_id))
  options=tuple(ChoiceOption(json.dumps(asdict(ref),sort_keys=True),'Original friendly minion',entity_id=ref.entity_id)for ref in refs)
  return(RequestChoice(c.player_id,options,c.source_id,min_count=0,max_count=0,sample_size=1,on_select=PREFIX+'sentinel_selected'),)if options else()
 def sentinel_selected(c):
  if c.choice is None or c.choice.selected_ids or len(c.choice.choice.options)!=1:raise ResolutionError('Sentinel lost its original sampled physical recipient')
  return(BuffCapturedMinion(MinionReference(**json.loads(c.choice.choice.options[0].id)),3,3,c.source_id),)
 def cryo(c):
  return(buff(c,c.source_id,2,2),)if living_source(c)and any(c.state.entities[i].frozen for i in characters(c,registry,3-c.player_id))else()
 def revenant(c):
  count=sum(c.state.entities[i].damage>0 for p in(1,2)for i in minions(c,registry,p))
  return(buff(c,c.source_id,count,count),)if count and living_source(c)else()
 def wyrm(c):
  cast=cast_record(c.state,dict(c.event.data)['cast_id'])
  if(cast.source_id,cast.player_id,cast.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):raise ResolutionError('Red Wyrm lost original cast completion linkage')
  if not cast.completed or not cast.payload_started or cast.failure is not None or cast.interrupted:raise ResolutionError('Red Wyrm requires actual successful cast completion')
  return(buff(c,c.source_id,2,0),)if cast.player_id==c.player_id and living_source(c)else()
 bodies=dict(knight=lambda c:targeted(c,1,1),repair=lambda c:targeted(c,0,4),fungal=fungal,tech=lambda c:hand(c,2,2),speaker=lambda c:hand(c,3,3,('dragon',)),
  han=lambda c:(RandomBuffStoredMinion(c.player_id,5,5,source_id=c.source_id),),champion=champion,valiant=valiant,
  valiant_inspire=lambda c:valiant(c)if is_inspire(c.state,c.event,c.player_id)else(),sentinel=sentinel,sentinel_selected=sentinel_selected,cryo=cryo,revenant=revenant,wyrm=wyrm)
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 registry.register_target_predicate(TargetPredicateSpec(PREFIX+'friendly_mech',current_tribes_any=('mech',)))
 scripts={KNIGHT:'knight',REPAIR:'repair',FUNGAL:'fungal',TECH:'tech',SPEAKER:'speaker',HAN:'han',VALIANT:'valiant',CRYO:'cryo',REVENANT:'revenant'}
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={}
  if cid in scripts:kw['battlecry']=PREFIX+scripts[cid]
  if cid in(KNIGHT,REPAIR):kw.update(targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'),target_rule=PREFIX+'friendly_mech')
  if cid in(CHAMPION,VALIANT,WYRM):kw['triggers']=(TriggerSpec('spell_cast_finished'if cid==WYRM else'hero_power_used',PREFIX+('wyrm'if cid==WYRM else'champion'if cid==CHAMPION else'valiant_inspire')),)
  if cid==SENTINEL:kw['deathrattle']=PREFIX+'sentinel'
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
