"""Independent reviewed declarations and native Dragon, Deathrattle and Combo bodies."""
from dataclasses import asdict,replace
import json
from pathlib import Path
from hs_sim.engine.effects import Damage,Destroy,GainArmor
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetMode,TargetSpec,Zone
from hs_sim.engine.player_target_inputs import PlayerTargetRuleSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.tribes import TribeState,has_any_tribe
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p83-v1.json'
BATCH_HASH='1ef4c7d99c1887bef95ca4e1ba28c5b320b1f1bbadf6e08cf71907860c0e085a'
FIEND,VALIANT,EMPEROR,HAN,ALCHEMIST,RIDER,CHAMPION,ARMOR,BLACKWING,SCRAP,VILE,CHEMIST=(
 'WON_058','WON_085','WON_133','WON_137','WON_315','WON_316','WON_328','WON_339','WON_329','BT_249','UNG_064','BOT_576')
COLLECTIBLE_ROOTS=()
DEPENDENCIES=ROOTS=(FIEND,VALIANT,EMPEROR,HAN,ALCHEMIST,RIDER,CHAMPION,ARMOR,BLACKWING,SCRAP,VILE,CHEMIST)
PREFIX='cards.simple_followup_p83.'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or d['cards']or d['skipped']or tuple(x['record']['id']for x in d['dependencies'])!=DEPENDENCIES:
  raise TargetValidationError('P83 complete reviewed scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P83 complete original record changed')
 return d

def register_simple_followup_p83_cards(registry):
 d=load_batch()
 for cid,pin in d['existing_dependency_definition_pins'].items():
  if canonical_digest(asdict(registry.card(cid)))!=pin['sha256']:raise TargetValidationError('P83 lost complete original declaration '+cid)
 def held_dragon(c):
  return any(c.state.entities[i].kind==CardType.MINION and has_any_tribe(registry,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand if i!=c.source_id)
 def dragon_target(c):
  own=next(p for p in c.observation['players']if p['id']==c.player_id);matches=[]
  for row in own['hand']:
   if row.get('kind')!=CardType.MINION.value or row.get('ref')==c.source.get('ref'):continue
   if row.get('tribes')is None:raise ResolutionError('Blackwing target requires known own current hand tribes')
   matches.append(TribeState(tuple(sorted(row['tribes'])),tuple(sorted(row.get('tribes_excluded',())))).matches_any(('dragon',)))
  return any(matches)
 registry.register_player_target_rule(PlayerTargetRuleSpec(PREFIX+'held_dragon','p83-current-own-hand-v1'),dragon_target)
 def blackwing(c):return(Damage(c.target_id,5,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None and held_dragon(c)else()
 def scrap(c):
  if c.deathrattle is None:raise ResolutionError('Scrap Golem requires its original Deathrattle acceptance')
  return(GainArmor(c.player_id,max(0,c.death.attack if c.death is not None else c.source.attack)),)
 registry.register_behavior(PREFIX+'blackwing',blackwing);registry.register_behavior(PREFIX+'scrap',scrap)
 registry.register_behavior(PREFIX+'vile',lambda c:()if c.target_id is None else(Destroy(c.target_id,c.source_id),))
 reuse={**d['reviewed_declaration_aliases'],**d['additional_reused_combo_source']}
 for item in d['dependencies']:
  raw=item['record'];cid=raw['id'];metadata=metadata_from_record(raw)
  if cid in reuse:
   definition=replace(registry.card(reuse[cid]),id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata)
  else:
   kw={}
   if cid==BLACKWING:kw.update(battlecry=PREFIX+'blackwing',targeting=TargetSpec(TargetMode.IF_AVAILABLE),target_rule=PREFIX+'held_dragon')
   if cid==SCRAP:kw.update(keywords=(Keyword.TAUNT,),deathrattle=PREFIX+'scrap')
   if cid==VILE:kw.update(keywords=(Keyword.COMBO,),combo=PREFIX+'vile',targeting=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,)),target_condition='combo')
   definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata,**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
