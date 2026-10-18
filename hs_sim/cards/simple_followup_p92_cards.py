"""Native one-cost Battlecries/Deathrattles and three complete named children."""
import json
from pathlib import Path
from hs_sim.engine.effects import AddToHand,Damage,DamageBatch,Draw,GainArmor,RandomDamage
from hs_sim.engine.model import CardDefinition,CardType,DamageKind
from hs_sim.engine.pools import PoolCard
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.targets import TargetValidationError,canonical_digest
from .metadata import metadata_from_record
from .native_followup_cards import characters,deathrattle_position

KVALDIR,FORAGER,MECHAROO,CRYSTALLIZER,HORROR,LIBRARIAN,BAT,REAVER,LEPER=('AT_105','BAR_751','BOT_445','BOT_447','BT_407','LOOT_014','OG_179','UNG_803','EX1_029')
TINYFIN,JOE,SOUL=('BAR_751t','BOT_445t','BT_407t')
ROOTS=(KVALDIR,FORAGER,MECHAROO,CRYSTALLIZER,HORROR,LIBRARIAN,BAT,REAVER,LEPER)
DEPENDENCIES=(TINYFIN,JOE,SOUL);ALL_IDS=(*ROOTS,*DEPENDENCIES);COLLECTIBLE_ROOTS=()
PREFIX='cards.simple_followup_p92.';BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p92-v1.json'
BATCH_HASH='2bf6be4799c80375fe2a62d716d9a86cfa0ab02a5196f08d56ce0bda145f2917'

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['dependencies'])!=ALL_IDS or any(d[k]for k in('cards','existing_dependencies','evidence_only','skipped')):raise TargetValidationError('P92 complete assigned scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for x in d['dependencies']):raise TargetValidationError('P92 complete original source changed')
 if len(d['exact_parent_child_links'])!=6 or len(d['source_tag_links'])!=3:raise TargetValidationError('P92 complete named-child proof changed')
 return d

def register_simple_followup_p92_cards(registry):
 def hero(c,pid,amount):return Damage(c.state.players[pid].hero_id,amount,c.source_id,DamageKind.MINION_ABILITY)
 def summon(c,cid):return(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c),position=deathrattle_position(c)),)
 bodies={KVALDIR:lambda c:(Damage(c.source_id,3,c.source_id,DamageKind.MINION_ABILITY),),
  FORAGER:lambda c:summon(c,TINYFIN),MECHAROO:lambda c:summon(c,JOE),
  CRYSTALLIZER:lambda c:(hero(c,c.player_id,5),GainArmor(c.player_id,5)),
  HORROR:lambda c:(AddToHand(c.player_id,SOUL,c.source_id),),
  LIBRARIAN:lambda c:(Draw(c.player_id,1,c.source_id),hero(c,c.player_id,2)),
  BAT:lambda c:(RandomDamage(characters(c,registry,3-c.player_id),1,c.source_id,DamageKind.MINION_ABILITY),),
  REAVER:lambda c:(DamageBatch(tuple(hero(c,p,1)for p in(c.player_id,3-c.player_id))),),
  LEPER:lambda c:(hero(c,3-c.player_id,2),)}
 for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
 for x in load_batch()['dependencies']:
  raw=x['record'];cid=raw['id'];kw={}
  if raw['type']!='MINION'or raw['cost']!=1 or raw['collectible']!=(cid in ROOTS):raise TargetValidationError('P92 complete printed minion type/cost changed')
  if cid in(KVALDIR,CRYSTALLIZER,LIBRARIAN,REAVER):kw['battlecry']=PREFIX+cid
  elif cid in ROOTS:kw['deathrattle']=PREFIX+cid
  definition=CardDefinition(cid,raw['name'],CardType.MINION,cost=1,attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
