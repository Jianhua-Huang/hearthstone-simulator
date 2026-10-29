"""Standard consumers of actual host past pools and native discovery receipts."""
import json
from pathlib import Path
from hs_sim.engine.card_creation import CreatedMinionGrant
from hs_sim.engine.dark_gift_generation import DiscoverDarkGift
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass,CardDefinition,CardType,CostSpec,Keyword,SpellSchool,TriggerSpec,Zone
from hs_sim.engine.nondeath_removal import RemoveFromGame
from hs_sim.engine.spell_casts import cast_record
from hs_sim.engine.pools import DiscoverFromPool,GenerateFromPool,PoolCard,PoolQuery
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference
from hs_sim.targets import TargetValidationError,canonical_digest
from .health_cards import SCHOOLS
from .attack_followup_cards import living_source
from .metadata import metadata_from_record
from .native_followup_cards import deathrattle_position

BATCH_PATH=Path(__file__).resolve().parents[2]/'data/cards/simple-followup-p89-v1.json'
BATCH_HASH='fd2cb4d52c7ccaf49aa29bcffbe04fedb729fa73060a8c3c970babc55c74f584'
WO,NEON,MEMORY,WARDEN,GLAIVE,ALTER,WINGS,LORD,REALITY=('TIME_013','TIME_016','TIME_040','TIME_052','TIME_444','TIME_857','END_027','CATA_EVENT_000','TIME_707')
ROOTS=COLLECTIBLE_ROOTS=(WO,NEON,MEMORY,WARDEN,GLAIVE,ALTER,WINGS,LORD,REALITY)
DEPENDENCIES=()
DEFERRED=('TIME_711','TLC_434','CAP_407','EDR_493')
PAST_POOL='constructed.past.cards'
ARCANE_PAST_POOL='constructed.local-past-arcane.full-reference-v1'
NATURE_PAST_POOL='constructed.local-past-nature.druid-reference-v1'
WARRIOR_NATURE_PAST_POOL='constructed.local-past-nature.warrior-reference-v1'
HUNTER_NATURE_PAST_POOL='constructed.local-past-nature.hunter-reference-v1'
PREFIX='cards.simple_followup_p89.'
QUERIES={WO:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',spell_schools=(SpellSchool.NATURE,)),
 NEON:PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='specified',classes=(CardClass.PALADIN,),include_neutral=False,tribes_any=('mech',)),
 MEMORY:PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=5,max_cost=5),WARDEN:PoolQuery(kinds=(CardType.MINION,),collectible=True),
 GLAIVE:PoolQuery(kinds=(CardType.MINION,),collectible=True,tribes_any=('demon',)),ALTER:PoolQuery(kinds=(CardType.SPELL,),collectible=True,class_mode='current',spell_schools=(SpellSchool.ARCANE,)),
 WINGS:PoolQuery(kinds=(CardType.MINION,),collectible=True,class_mode='current',tribes_any=('dragon',)),LORD:PoolQuery(kinds=(CardType.MINION,),collectible=True,keywords_all=(Keyword.COLOSSAL,)),
 REALITY:PoolQuery(collectible=True,choose_one=True)}

def load_batch():
 d=json.loads(BATCH_PATH.read_text(encoding='utf-8'))
 if canonical_digest(d)!=BATCH_HASH or tuple(x['record']['id']for x in d['cards'])!=ROOTS or tuple(x['card_id']for x in d['skipped'])!=DEFERRED:raise TargetValidationError('P89 complete assigned scope changed')
 if any(canonical_digest(x['record'])!=x['record_sha256']for key in('cards','dependencies','existing_dependencies','evidence_only')for x in d[key]):raise TargetValidationError('P89 complete original row changed')
 return d

def register_simple_followup_p89_cards(registry):
 d=load_batch()
 def wo(c):
  record=cast_record(c.state,dict(c.event.data)['cast_id'])
  if(record.source_id,record.player_id,record.target_id)!=(c.event.source_id,c.event.player_id,c.event.target_id):raise ResolutionError('Wo lost original completed spell linkage')
  if not record.completed or not record.payload_started or record.failure is not None or record.interrupted:raise ResolutionError('Wo requires actual successful spell completion')
  if record.player_id!=c.player_id or not living_source(c):return()
  pool={CardClass.WARRIOR:WARRIOR_NATURE_PAST_POOL,CardClass.HUNTER:HUNTER_NATURE_PAST_POOL}.get(c.state.players[c.player_id].hero_class,NATURE_PAST_POOL)
  return(DiscoverFromPool(c.player_id,pool,QUERIES[WO],source_id=c.source_id),)
 def reality(c):
  p=c.state.players[c.player_id];hand=tuple(CardReference.capture(c.state.entities[i])for i in p.hand);deck=tuple(CardReference.capture(c.state.entities[i])for i in p.deck)
  return(RemoveFromGame((*hand,*deck),c.source_id),)+tuple(GenerateFromPool(c.player_id,PAST_POOL,QUERIES[REALITY],count=count,source_id=c.source_id,destination=destination,position='bottom'if destination=='deck'else'random',cost=CostSpec(delta=-1))for count,destination in((len(hand),'hand'),(len(deck),'deck'))if count)
 bodies={WO:wo,NEON:lambda c:(DiscoverFromPool(c.player_id,PAST_POOL,QUERIES[NEON],source_id=c.source_id,minion_grant=CreatedMinionGrant(5,5)),),
 MEMORY:lambda c:(GenerateFromPool(c.player_id,PAST_POOL,QUERIES[MEMORY],source_id=c.source_id),),
 WARDEN:lambda c:(GenerateFromPool(c.player_id,PAST_POOL,QUERIES[WARDEN],source_id=c.source_id,destination='board',board_position=deathrattle_position(c),cause=SummonCause.capture(c)),),
 GLAIVE:lambda c:(GenerateFromPool(c.player_id,PAST_POOL,QUERIES[GLAIVE],source_id=c.source_id),),
 ALTER:lambda c:(DiscoverFromPool(c.player_id,ARCANE_PAST_POOL,QUERIES[ALTER],source_id=c.source_id,discoveries=2,cost=CostSpec(delta=-2)),),
 WINGS:lambda c:(DiscoverDarkGift(c.player_id,PAST_POOL,QUERIES[WINGS],c.source_id),),
 LORD:lambda c:(GenerateFromPool(c.player_id,PAST_POOL,QUERIES[LORD],source_id=c.source_id),),REALITY:reality}
 for cid,body in bodies.items():registry.register_behavior(PREFIX+cid,body)
 for item in d['cards']:
  raw=item['record'];cid=raw['id'];kind=CardType(raw['type'].lower());kw={}
  if kind==CardType.SPELL:kw.update(on_play=PREFIX+cid,spell_school=SCHOOLS.get(raw['tags'].get('SPELL_SCHOOL')))
  elif cid==WO:kw.update(keywords=(Keyword.ELUSIVE,),triggers=(TriggerSpec('spell_cast_finished',PREFIX+cid),))
  elif cid==LORD:kw['battlecry']=PREFIX+cid
  elif cid in(MEMORY,WARDEN,GLAIVE):kw['deathrattle']=PREFIX+cid
  if cid==WARDEN:kw['keywords']=(Keyword.TAUNT,)
  definition=CardDefinition(cid,raw['name'],kind,cost=raw['cost'],attack=raw['attack']or 0,health=raw['health']if kind==CardType.MINION else 0,durability=raw['health']if kind==CardType.WEAPON else 0,metadata=metadata_from_record(raw),**kw)
  registry.register_card(definition)
  if cid not in registry.pool_cards:registry.register_pool_card(PoolCard.from_definition(definition))
