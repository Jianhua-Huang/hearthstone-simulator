"""Thirteen complete one-cost historical minions, all existing native declarations."""
import json
from pathlib import Path
from hs_sim.engine.effects import Draw
from hs_sim.engine.model import AttackPolicySpec,CardDefinition,CardType,CostAuraSpec,CostSpec,Keyword,StatRelationLayer,StatRelationOperand,StatRelationSpec
from hs_sim.engine.pools import PoolCard
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

BATTLEMAGE,MOLE,FRESHMAN,ATTENDEE,HERMIT,AIR,SNAKE,LAB,QUEEN,WARBOT,EGG,WAX,SKATER=('DRG_239','LOOT_258','SCH_137','AT_097','TSC_065','UNG_019','LOE_010','SCH_310','UNG_085','GVG_051','KAR_029','LOOT_117','BOT_020')
ROOTS=DEPENDENCIES=(BATTLEMAGE,MOLE,FRESHMAN,ATTENDEE,HERMIT,AIR,SNAKE,LAB,QUEEN,WARBOT,EGG,WAX,SKATER)
COLLECTIBLE_ROOTS=();PREFIX='cards.simple_followup_p91.'
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p91-v1.json'
BATCH_HASH='a6a06b0e06806ce8dc682a68428fc6766282560f28b276e7fe78aadbe241c686'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['dependencies'])!=ROOTS or any(d[k]for k in('cards','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P91 complete locked13 definitions changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies']):raise TargetValidationError('P91 complete original source changed')
 if d['numeric_normalizations']!={EGG:{'attack':0},WAX:{'attack':0}}:raise TargetValidationError('P91 individual printed0 evidence changed')
 return d

def register_simple_followup_p91_cards(registry):
 d=load_batch();registry.register_behavior(PREFIX+'egg',lambda c:(Draw(c.player_id,1,c.source_id),))
 keywords={ATTENDEE:(Keyword.TAUNT,),AIR:(Keyword.ELUSIVE,),SNAKE:(Keyword.POISONOUS,),WAX:(Keyword.TAUNT,Keyword.DIVINE_SHIELD),SKATER:(Keyword.MAGNETIC,Keyword.RUSH)}
 for x in d['dependencies']:
  raw=x['record'];cid=raw['id'];kw={}
  if raw['type']!='MINION'or raw['cost']!=1 or raw['collectible']is not True:raise TargetValidationError('P91 requires original one-cost collectible minions')
  attack=raw['attack']
  if cid in(EGG,WAX):
   if attack is not None or'ATK'in raw['tags']:raise TargetValidationError('P91 printed0 may not replace explicit Attack')
   attack=0
  if cid==HERMIT:kw['attack_policies']=(AttackPolicySpec('cannot_attack'),)
  elif cid==LAB:kw['spell_damage']=1
  elif cid==QUEEN:kw['cost_auras']=(CostAuraSpec(CostSpec(delta=2,card_types=(CardType.MINION,))),)
  elif cid==WARBOT:kw['stat_relations']=(StatRelationSpec(operand=StatRelationOperand.SELF_DAMAGED,layer=StatRelationLayer.CONDITIONAL_ATTACK,amount=1),)
  elif cid==EGG:kw['deathrattle']=PREFIX+'egg'
  elif cid==SKATER:kw['magnetic_tribes']=('mech',)
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=attack,health=raw['health'],metadata=metadata_from_record(raw),keywords=keywords.get(cid,()),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
