"""Original named death rewards, current copies and native awakening consumers."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.cross_zone import MinionScope,minion_references
from hs_sim.engine.deck_shuffles import shuffled
from hs_sim.engine.effects import CopyMinion,InvokeBehavior
from hs_sim.engine.hero_attack_history import hero_attack_count
from hs_sim.engine.model import BoardPresenceReference,CardDefinition,CardType,CostSpec,HeroAttackQuery,Keyword,Zone
from hs_sim.engine.pools import PoolCard,PoolQuery
from hs_sim.engine.sacrifice import GrantCapturedKeyword,MinionReference
from hs_sim.engine.summon_quantities import SummonCause,card_summon
from hs_sim.engine.zones import AddToDeck,ModifyStoredCost
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p84-v1.json'
BATCH_HASH='353fcc72fdd793a20ac9086f80eadbe93edf931262f768af50e6f5db1b95f821'
BELCHER,WHITE,DIREHORN,SORIDORMI,ROC,BLACKWING,OMEGA,ELITE=('FP1_012','CFM_324','UNG_957','WON_146','UNG_801','BRM_034','BOT_536','BAR_846')
SLIME,STORM,MATRIARCH='FP1_012t','CFM_324t','UNG_957t1'
COLLECTIBLE_ROOTS=()
COLLECTIBLE_DEPENDENCIES=(BELCHER,WHITE,DIREHORN,SORIDORMI,ROC,BLACKWING,OMEGA,ELITE)
STATIC_TOKENS=(SLIME,STORM,MATRIARCH)
DEPENDENCIES=ROOTS=COLLECTIBLE_DEPENDENCIES+STATIC_TOKENS
PREFIX='cards.simple_followup_p84.'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES:raise TargetValidationError('P84 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P84 complete original record changed')
 return d

def register_simple_followup_p84_cards(registry):
 d=load_batch()
 if canonical_digest(asdict(registry.card('WON_329')))!=d['existing_dependency_definition_pins']['WON_329']['sha256']:raise TargetValidationError('P84 requires unchanged complete WON_329')
 def copies(c,n):
  if not living_source(c):return()
  original=BoardPresenceReference.capture(c.state,c.source_id);cause=SummonCause.capture(c)
  return tuple(CopyMinion(original,c.player_id,cause=cause)for _ in range(n))
 def awaken_now(c):
  refs=minion_references(c.state,registry,c.player_id,MinionScope((Zone.HAND,),PoolQuery(kinds=(CardType.MINION,),tribes_any=('dragon',)),tribe_basis='current'),c.source_id)
  return tuple(ModifyStoredCost(ref,CostSpec(delta=-4),c.source_id)for ref in refs)
 def roc(c):
  count=sum(i!=c.source_id and c.state.entities[i].kind==CardType.MINION for i in c.state.players[c.player_id].board)
  return(GrantCapturedKeyword(MinionReference.capture(c.source),Keyword.TAUNT,c.source_id),)if count>=2 and living_source(c)else()
 bodies=dict(belcher=lambda c:(card_summon(c,c.player_id,SLIME,deathrattle_position(c)),),white=lambda c:shuffled(c,(AddToDeck(c.player_id,STORM,source_id=c.source_id),)),direhorn=lambda c:shuffled(c,(AddToDeck(c.player_id,MATRIARCH,source_id=c.source_id),)),
  omega=lambda c:copies(c,2)if c.state.players[c.player_id].max_mana>=10 else(),elite=lambda c:copies(c,1)if hero_attack_count(c.state,c.player_id,HeroAttackQuery(window='owner_turn'))>0 else(),
  awaken=lambda c:(InvokeBehavior(PREFIX+'awaken_now',c.source_id,c.player_id),),awaken_now=awaken_now,roc=roc)
 for name,body in bodies.items():registry.register_behavior(PREFIX+name,body)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];meta=metadata_from_record(raw)
  if cid==BLACKWING:definition=replace(registry.card('WON_329'),id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=meta)
  else:
   kw={}
   if cid in(BELCHER,WHITE,DIREHORN,ELITE,*STATIC_TOKENS):kw['keywords']=(Keyword.TAUNT,)
   if cid in(BELCHER,WHITE,DIREHORN):kw['deathrattle']=PREFIX+{BELCHER:'belcher',WHITE:'white',DIREHORN:'direhorn'}[cid]
   if cid in(OMEGA,ELITE,ROC):kw['battlecry']=PREFIX+{OMEGA:'omega',ELITE:'elite',ROC:'roc'}[cid]
   if cid==SORIDORMI:kw.update(dormant_turns=2,on_awaken=PREFIX+'awaken')
   definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=meta,**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
