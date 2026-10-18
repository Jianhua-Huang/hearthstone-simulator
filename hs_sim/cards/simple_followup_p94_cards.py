"""Twelve whole one-cost minions using printed declarations and native effects."""
from dataclasses import asdict
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,InvokeBehavior,Overload
from hs_sim.engine.model import CardDefinition,CardType,Keyword
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.sacrifice import BuffCapturedMinion,MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .attack_followup_cards import living_source
from .metadata import metadata_from_record

RAIDER,FOOTMAN,SHIELD,BOAR,HAWK,CULT,DEVIL,IMP,MISTAKE,CAT,FIRE=('CS2_168','CS1_042','EX1_405','CS2_171','CS2_169','OG_070','EX1_243','BT_258','NX2_050','CFM_315','UNG_809')
TABBY='CFM_315t';FLAME='UNG_809t1'
ROOTS=(RAIDER,FOOTMAN,SHIELD,BOAR,HAWK,CULT,DEVIL,IMP,MISTAKE,CAT,FIRE);DEPENDENCIES=(TABBY,);ALL_IDS=(*ROOTS,*DEPENDENCIES);COLLECTIBLE_ROOTS=()
PREFIX='cards.simple_followup_p94.';BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p94-v1.json';BATCH_HASH='58a21c9a1744442f9b3c36c9421cc671c9bb333fa2142c8a0706e847ea150f56'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['dependencies'])!=ALL_IDS or tuple(x['record']['id']for x in d['existing_dependencies'])!=(FLAME,)or any(d[k]for k in('cards','evidence_only','skipped')):raise TargetValidationError('P94 complete assigned source changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies']+d['existing_dependencies']):raise TargetValidationError('P94 complete original record changed')
 if d['numeric_normalizations']!={SHIELD:{'attack':0}}:raise TargetValidationError('P94 only reviewed missing Attack0 is permitted')
 return d

def register_simple_followup_p94_cards(registry):
 d=load_batch();existing,=d['existing_dependencies']
 if canonical_digest(asdict(registry.card(FLAME)))!=existing['definition_sha256']or canonical_digest(asdict(registry.pool_cards[FLAME]))!=existing['pool_card_sha256']:raise TargetValidationError('P94 requires unchanged complete existing Flame Elemental')
 def cat_now(c):
  board=c.state.players[c.player_id].board;position=board.index(c.source_id)+1 if c.source_id in board else None
  return(SummonByCard(c.player_id,(SummonEntryMaterial(TABBY),),SummonCause.capture(c),position=position),)
 bodies={'cult':lambda c:(BuffCapturedMinion(MinionReference.capture(c.source),1,1,c.source_id),)if living_source(c)else(),
  'devil':lambda c:(Overload(c.player_id,2),),
  'cat':lambda c:(InvokeBehavior(PREFIX+'cat_now',c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),),
  'cat_now':cat_now,'fire':lambda c:(AddToHand(c.player_id,FLAME,c.source_id),)}
 for key,body in bodies.items():registry.register_behavior(PREFIX+key,body)
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];kw={};attack=raw['attack']
  if raw['type']!='MINION'or raw['cost']!=1 or raw['collectible']!=(cid in ROOTS):raise TargetValidationError('P94 full printed kind/cost changed')
  if cid==SHIELD:
   if attack is not None or 'ATK'in raw['tags']:raise TargetValidationError('P94 explicit missing Shieldbearer Attack0 lost its source precondition')
   attack=d['numeric_normalizations'][cid]['attack']
  if cid in(FOOTMAN,SHIELD,IMP):kw['keywords']=(Keyword.TAUNT,)
  if cid==BOAR:kw['keywords']=(Keyword.CHARGE,)
  if cid in(HAWK,DEVIL):kw['keywords']=(Keyword.WINDFURY,)
  if cid==CULT:kw.update(keywords=(Keyword.COMBO,),combo=PREFIX+'cult')
  if cid==DEVIL:kw['on_play']=PREFIX+'devil'
  if cid==IMP:kw['dormant_turns']=2
  if cid in(CAT,FIRE):kw['battlecry']=PREFIX+('cat'if cid==CAT else'fire')
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=attack,health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
