"""Seven whole historical minions and the complete physical Spare Part family."""
import json
from pathlib import Path
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import Buff,Damage,Freeze,GainArmor,GrantKeyword,InvokeBehavior,ReturnToHand,SwapStats
from hs_sim.engine.model import CardDefinition,CardType,DamageKind,Keyword,TargetMode,TargetSpec,TimedKeywordSpec,Zone
from hs_sim.engine.pools import GenerateFromCandidates,PoolCard
from hs_sim.engine.target_predicates import TargetPredicateSpec
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record

GNOME,VETERAN,GUARD,LUMI,FILLET,VENDOR,STAFF=('GVG_082','ICC_092','SW_067','BOT_079','TSC_963','YOP_032','REV_338')
PLATING,REWINDER,HORN,CLOAK,COOLANT,SWITCH,BLADES=tuple('PART_00'+str(i)for i in range(1,8))
ROOTS=(GNOME,VETERAN,GUARD,LUMI,FILLET,VENDOR,STAFF);DEPENDENCIES=SPARES=(PLATING,REWINDER,HORN,CLOAK,COOLANT,SWITCH,BLADES);ALL_IDS=(*ROOTS,*SPARES);COLLECTIBLE_ROOTS=()
PREFIX='cards.simple_followup_p93.';MECH_RULE=TargetPredicateSpec(PREFIX+'mech',current_tribes_any=('mech',))
BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p93-v1.json';BATCH_HASH='45080a6db16b6277dd8c9b9c27966f277741f2e6bac431ddc24ab8357483aee1'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['dependencies'])!=ALL_IDS or len(d['evidence_only'])!=4 or any(d[k]for k in('cards','existing_dependencies','skipped')):raise TargetValidationError('P93 complete assigned family changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies']+d['evidence_only']):raise TargetValidationError('P93 complete original row changed')
 if tuple(d['spare_part_family']['full_source_spare_part_spell_ids'])!=SPARES or canonical_digest(d['spare_part_family'])!=d['spare_part_family_sha256']:raise TargetValidationError('P93 complete original family evidence changed')
 return d

def register_simple_followup_p93_cards(registry):
 def cloak(c):
  clock='controller'if c.state.entities[c.target_id].controller==c.player_id else'opponent'
  return(GrantKeyword(c.target_id,Keyword.STEALTH,c.source_id,duration=TimedKeywordSpec(Keyword.STEALTH,player=clock)),)
 registry.register_behavior(PREFIX+'cloak_now',cloak)
 bodies={GNOME:lambda c:(GenerateFromCandidates(c.player_id,SPARES,c.source_id),),
  VETERAN:lambda c:()if c.target_id is None else(Buff(c.target_id,attack=1,source_id=c.source_id),),
  GUARD:lambda c:()if c.target_id is None else(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),
  LUMI:lambda c:()if c.target_id is None else(Buff(c.target_id,1,1,c.source_id),),
  FILLET:lambda c:()if c.target_id is None else(Damage(c.target_id,1,c.source_id,DamageKind.MINION_ABILITY),),
  VENDOR:lambda c:tuple(GainArmor(p,4)for p in(c.player_id,3-c.player_id)),
  STAFF:lambda c:(BuffMinionsInZones(c.player_id,0,1,MinionScope(zones=(Zone.HAND,)),c.source_id),),
  PLATING:lambda c:(Buff(c.target_id,health=1,source_id=c.source_id),),REWINDER:lambda c:(ReturnToHand(c.target_id),),
  HORN:lambda c:(GrantKeyword(c.target_id,Keyword.TAUNT,c.source_id),),CLOAK:lambda c:(InvokeBehavior(PREFIX+'cloak_now',c.source_id,c.player_id,c.target_id,None if c.play is None else c.play.id),),COOLANT:lambda c:(Freeze(c.target_id,c.source_id),),
  SWITCH:lambda c:(SwapStats(c.target_id,c.source_id),),BLADES:lambda c:(Buff(c.target_id,attack=1,source_id=c.source_id),)}
 for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
 registry.register_target_predicate(MECH_RULE)
 for x in load_batch()['dependencies']:
  raw=x['record'];cid=raw['id'];kind=CardType.MINION if cid in ROOTS else CardType.SPELL;kw={}
  if raw['type']!=kind.value.upper()or raw['cost']!=1 or raw['collectible']!=(cid in ROOTS):raise TargetValidationError('P93 full printed kind/cost changed')
  if cid==GNOME:kw['deathrattle']=PREFIX+cid
  elif kind==CardType.MINION:kw['battlecry']=PREFIX+cid
  else:kw['on_play']=PREFIX+cid
  if cid in(VETERAN,GUARD,LUMI):kw['targeting']=TargetSpec(TargetMode.IF_AVAILABLE,zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly')
  elif cid==FILLET:kw['targeting']=TargetSpec(TargetMode.IF_AVAILABLE)
  elif cid in SPARES:kw['targeting']=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='friendly'if cid in(REWINDER,CLOAK)else'any')
  if cid==LUMI:kw['target_rule']=MECH_RULE.id
  definition=CardDefinition(cid,raw['name'],kind,cost=1,attack=raw['attack']if kind==CardType.MINION else 0,health=raw['health']if kind==CardType.MINION else 0,metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
