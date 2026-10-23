"""Native original-death operands, physical delivery and genuine event growth."""
from dataclasses import replace
from functools import lru_cache
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p88_cards as cards
from hs_sim.cards.simple_followup_p88_cards import (LIGHTSHOWER,MIXTRESS,VENDOR,PORCUPINE,CRYPT,FORGE,SAPPER,RATTLER,SERVANT,ACOLYTE,DEATH_ACOLYTE,BATTLEFIEND,VAPOR,ROOTS,load_batch,register_simple_followup_p88_cards)
from hs_sim.cards import death_followup_cards as death,reactive_growth_cards as reactive
from hs_sim.cards.utility_cards import load_batch as utility_batch,compile_body
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GrantKeyword,InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference

TEST='p88.test.'
HERO,FILLER,TINY,UNDEAD,ELEMENTAL,UNKNOWN,WEAPON,PROVIDER=(TEST+i for i in('hero','filler','tiny','undead','elemental','unknown','weapon','provider'))
NOP,PING,HIT,LETHAL,ZERO,KILL,BUFF,SILENCE,TAKE,WOUND,SHIELD,SUMMON_ELEMENTAL,TO_UNDEAD,HAND_ELEMENTAL,BARE=(TEST+i for i in('nop','ping','hit','lethal','zero','kill','buff','silence','take','wound','shield','summon-elemental','to-undead','hand-elemental','bare'))
DEATH_SOURCES=(PORCUPINE,RATTLER,SERVANT)
REACTIVE_SOURCES=(DEATH_ACOLYTE,VAPOR)
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=tribes)
def baseline_registry(after_batch=False):
 class OriginalPrefixReady(Exception):
  def __init__(self,registry):self.registry=registry
 def capture(registry):
  if after_batch:register_simple_followup_p88_cards(registry)
  raise OriginalPrefixReady(registry)
 with patch('hs_sim.cards.simple_followup_p88_cards.register_simple_followup_p88_cards',capture):
  try:build_registry()
  except OriginalPrefixReady as found:return found.registry
 raise AssertionError('Original P88 registration boundary was not reached')
def batch_registry():
 r=baseline_registry(after_batch=True)
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(maxsize=1)
def original_fixture_sources():
 r=baseline_registry();ids=tuple('CORE_'+i for i in ROOTS if i not in(*DEATH_SOURCES,*REACTIVE_SOURCES))+('CS2_029',);definitions=tuple(r.card(i)for i in ids);keys=set()
 for d in definitions:
  if d.id=='CORE_'+SAPPER:continue
  keys.update(x for x in(d.on_play,d.battlecry,d.deathrattle)if x);keys.update(x.behavior_id for x in d.triggers)
 for k in keys:
  body=r.behavior(k)
  if body.__code__.co_freevars:
   assert body.__code__.co_freevars==('attack_record',)and not body.__closure__[0].cell_contents.__code__.co_freevars
 return definitions,tuple((k,r.behavior(k))for k in sorted(keys))
def registry(mode):
 r=Registry('p88-small-original-native-sources');definitions,bodies=original_fixture_sources()
 for d in definitions:r.register_card(d)
 for k,body in bodies:r.register_behavior(k,body)
 data=death.load_batch();subset=dict(data,cards=[x for x in data['cards']if x['record']['id']in('CORE_'+i for i in DEATH_SOURCES)],existing_dependencies=[],dependency_links=[],gallery_dependency_links=[])
 with patch.object(death,'load_batch',return_value=subset):death.register_death_followup_cards(r)
 data=reactive.load_batch();subset=dict(data,cards=[x for x in data['cards']if x['record']['id']in('CORE_'+i for i in REACTIVE_SOURCES)])
 with patch.object(reactive,'load_batch',return_value=subset):reactive.register_reactive_growth_cards(r)
 row=next(x for x in utility_batch()['cards']if x['record']['id']=='CORE_'+SAPPER);assert compile_body(r,row['recipe']['bodies']['deathrattle'],False,set())==r.card('CORE_'+SAPPER).deathrattle
 register_simple_followup_p88_cards(r)
 for cid,tribes,atk,hp in((FILLER,(),1,20),(TINY,(),1,2),(UNDEAD,('undead',),1,5),(ELEMENTAL,('elemental',),1,8),(UNKNOWN,None,1,5)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp,metadata=meta(tribes)))
 r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=2,durability=10,metadata=meta()))
 r.register_card(CardDefinition(PROVIDER,PROVIDER,CardType.MINION,health=8,spell_damage=5,metadata=meta()))
 r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P88 deliberate pending continuation failure')))
 def wait(c):
  change=()
  if mode in('split','rattler'):change=(Summon(2,TINY),)
  elif mode=='servant':change=(Destroy(c.state.players[1].board[0],c.source_id),)
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change current board',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 scripts={NOP:lambda c:(),PING:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),HIT:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.EFFECT),),LETHAL:lambda c:(Damage(c.target_id,10,c.source_id,DamageKind.EFFECT),),ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),BUFF:lambda c:(Buff(c.target_id,3,2,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),WOUND:lambda c:tuple(Damage(c.state.players[p].hero_id,10,c.source_id,DamageKind.EFFECT)for p in(1,2)),SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),SUMMON_ELEMENTAL:lambda c:(Summon(c.player_id,ELEMENTAL),),TO_UNDEAD:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('undead',)),c.source_id),),HAND_ELEMENTAL:lambda c:(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('elemental',)),c.source_id),),BARE:lambda c:(Damage(c.state.players[2].hero_id,2,c.state.players[1].hero_id,DamageKind.EFFECT),)}
 for cid,body in scripts.items():
  target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid==HAND_ELEMENTAL else TargetSpec()if cid not in(NOP,WOUND,SUMMON_ELEMENTAL,BARE)else None
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):
   if c.player_id!=1 or c.event.source_id is None:return False
   cid=c.state.entities[c.event.source_id].card_id
   return cid in((PORCUPINE,)if mode=='split'else(RATTLER,)if mode=='rattler'else(SERVANT,)if mode=='servant'else(VENDOR,ACOLYTE)if mode=='draw'else(LIGHTSHOWER,))
  event='damage_dealt'if mode=='split'else'card_drawn'if mode=='draw'else'health_resolved'if mode=='heal'else'minion_died'
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP88Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*14,mana=60,max_mana=60,mana_cap=60,weapon_card_id=WEAPON),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*14,mana=60,max_mana=60,mana_cap=60,weapon_card_id=WEAPON)),seed=8888),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','original_entities','source_allocation','behavior_id'):self.assertNotIn('"'+key+'"',public)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),snap)
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor

 def test_a0_all_thirteen_actual_paid_entries_and_printed_native_declarations(self):
  for cid in ROOTS:
   g=self.game((cid,));before=g.state.players[1].mana;eid=self.play(g,cid);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid);e=g.state.entities[eid]
   self.assertEqual((e.attack,e.health),(raw['attack'],raw['health']));self.assertEqual(before-g.state.players[1].mana,raw['cost']);self.assertEqual(g.state.play_history[-1].card_id,cid)
 def test_b0_lightshower_original_death_heals_friendly_group_not_enemy(self):
  g=self.game((WOUND,HIT,KILL),board=(FILLER,LIGHTSHOWER));self.play(g,WOUND);target=self.first(g,FILLER,'board').id;self.play(g,HIT,target);source=self.first(g,LIGHTSHOWER,'board').id;self.play(g,KILL,source);self.assertEqual((self.hp(g),self.hp(g,2),g.state.entities[target].health),(28,20,20));self.assertTrue(all(x.health_result.source_id==source for x in g.state.healing_history));self.portable(g)
 def test_b1_lightshower_actual_heal_batch_wait_is_complete_and_rolls_back(self):
  g=self.game((WOUND,HIT,KILL),board=(FILLER,LIGHTSHOWER),mode='heal');self.play(g,WOUND);target=self.first(g,FILLER,'board').id;self.play(g,HIT,target);self.play(g,KILL,self.first(g,LIGHTSHOWER,'board').id);self.fail_wait(g);self.assertEqual((self.hp(g),g.state.entities[target].health),(28,20));self.choose(g);self.portable(g)
 def test_b2_mixtress_both_heroes_four_and_silenced_death_no_effect(self):
  for silenced in(False,True):
   g=self.game((WOUND,SILENCE,KILL),board=(MIXTRESS,));source=self.first(g,MIXTRESS,'board').id;self.play(g,WOUND)
   if silenced:self.play(g,SILENCE,source)
   self.play(g,KILL,source);self.assertEqual((self.hp(g),self.hp(g,2)),(20,20)if silenced else(24,24))
 def test_c0_vendor_both_real_entries_draw_controller_first_then_other(self):
  g=self.game((VENDOR,KILL));source=self.play(g,VENDOR);self.assertEqual([x.player_id for x in g.state.draw_history],[1,2]);self.play(g,KILL,source);self.assertEqual([x.player_id for x in g.state.draw_history],[1,2,1,2]);self.portable(g)
 def test_c1_vendor_stolen_death_uses_current_controller_order_and_original_source(self):
  g=self.game((TAKE,KILL),board=(VENDOR,));source=self.first(g,VENDOR,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);self.assertEqual([x.player_id for x in g.state.draw_history],[2,1]);self.assertTrue(all(x.source_id==source for x in g.state.draw_history))
 def test_c2_vendor_first_actual_draw_wait_resumes_second_once(self):
  g=self.game((VENDOR,),mode='draw');self.play(g,VENDOR);self.fail_wait(g);self.choose(g);self.assertEqual([x.player_id for x in g.state.draw_history],[1,2]);self.assertEqual(g.state.players[1].mana,58);self.portable(g)
 def test_d0_porcupine_original_buffed_death_attack_not_printed_attack_or_spell_bonus(self):
  g=self.game((BUFF,KILL),board=(PORCUPINE,PROVIDER));source=self.first(g,PORCUPINE,'board').id;self.play(g,BUFF,source);self.play(g,KILL,source);self.assertEqual(self.hp(g,2),25);self.assertEqual(g.state.death_history[-1].attack,5);self.assertEqual(sum(x.health_result.damage_dealt for x in g.state.damage_history),5);self.portable(g)
 def test_d1_porcupine_dead_source_packet_wait_preserves_remaining_native_budget(self):
  g=self.game((BUFF,KILL),board=(PORCUPINE,),mode='split');source=self.first(g,PORCUPINE,'board').id;self.play(g,BUFF,source);self.play(g,KILL,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(sum(x.health_result.damage_dealt for x in g.state.damage_history),5);self.assertTrue(all(x.health_result.source_id==source for x in g.state.damage_history));self.portable(g)
 def test_e0_crypt_and_forge_printed_rush_taunt_and_original_armor_amounts(self):
  for cid,initial,dead,keyword in((CRYPT,6,12,Keyword.RUSH),(FORGE,0,8,Keyword.TAUNT)):
   g=self.game((cid,KILL));source=self.play(g,cid);self.assertEqual(self.armor(g),initial);self.assertIn(keyword,g.state.entities[source].keywords);self.play(g,KILL,source);self.assertEqual(self.armor(g),dead)
 def test_e1_stolen_forge_death_rewards_actual_controller(self):
  g=self.game((TAKE,KILL),board=(FORGE,));source=self.first(g,FORGE,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);self.assertEqual((self.armor(g),self.armor(g,2)),(0,8))
 def test_f0_sapper_returns_one_original_enemy_physical_minion_and_empty_pool_keeps_rng(self):
  g=self.game((KILL,),board=(SAPPER,),enemy=(FILLER,TINY));original=set(g.state.players[2].board);self.play(g,KILL,self.first(g,SAPPER,'board').id);self.assertEqual(len(original&set(g.state.players[2].hand)),1);self.assertEqual(len(g.state.players[2].board),1);self.portable(g)
  g=self.game((KILL,),board=(SAPPER,));rng=g.snapshot()['rng_state'];self.play(g,KILL,self.first(g,SAPPER,'board').id);self.assertEqual(g.snapshot()['rng_state'],rng)
 def test_g0_rattler_death_uses_fresh_enemy_minion_batch_and_excludes_heroes_friends(self):
  g=self.game((KILL,),board=(RATTLER,FILLER),enemy=(FILLER,),mode='rattler');self.play(g,KILL,self.first(g,RATTLER,'board').id);self.fail_wait(g);self.choose(g,'change');self.assertEqual([g.state.entities[i].damage for i in g.state.players[2].board],[1,1]);self.assertEqual(self.first(g,FILLER,'board').damage,0);self.assertEqual((self.hp(g),self.hp(g,2)),(30,30));self.portable(g)
 def test_h0_servant_uses_original_attack_single_and_automatic_multiple_candidates(self):
  for count in(1,2):
   g=self.game((BUFF,KILL),board=(SERVANT,)+(FILLER,)*count);source=self.first(g,SERVANT,'board').id;self.play(g,BUFF,source);self.play(g,KILL,source);self.assertEqual(g.state.death_history[-1].attack,5);self.assertEqual(sorted(g.state.entities[i].attack for i in g.state.players[1].board),[6]if count==1 else[1,6]);self.assertIsNone(g.state.pending_choice);self.portable(g)
 def test_h1_servant_original_dead_source_wait_refreshes_surviving_candidates(self):
  g=self.game((BUFF,KILL),board=(SERVANT,FILLER,FILLER),mode='servant');source=self.first(g,SERVANT,'board').id;self.play(g,BUFF,source);self.play(g,KILL,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(len(g.state.players[1].board),1);self.assertEqual(g.state.entities[g.state.players[1].board[0]].attack,6);self.portable(g)
 def test_i0_acolyte_only_positive_self_damage_draws_including_actual_lethal(self):
  g=self.game((ZERO,PING,PING),board=(ACOLYTE,),enemy=(FILLER,));source=self.first(g,ACOLYTE,'board').id;self.play(g,ZERO,source);self.play(g,PING,self.first(g,FILLER,'board',2).id);self.assertFalse(g.state.draw_history);self.play(g,PING,source);self.assertEqual(len(g.state.draw_history),1)
  g=self.game((LETHAL,),board=(ACOLYTE,));source=self.first(g,ACOLYTE,'board').id;self.play(g,LETHAL,source);self.assertEqual(len(g.state.draw_history),1);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
 def test_i1_acolyte_shield_silence_and_real_damage_draw_wait(self):
  g=self.game((SHIELD,PING,SILENCE,PING),board=(ACOLYTE,));source=self.first(g,ACOLYTE,'board').id;self.play(g,SHIELD,source);self.play(g,PING,source);self.assertFalse(g.state.draw_history);self.play(g,SILENCE,source);self.play(g,PING,source);self.assertFalse(g.state.draw_history)
  g=self.game((PING,),board=(ACOLYTE,),mode='draw');self.play(g,PING,self.first(g,ACOLYTE,'board').id);self.fail_wait(g);self.choose(g);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
 def test_j0_death_acolyte_friendly_recorded_undead_not_enemy_or_nonundead(self):
  g=self.game((KILL,KILL,KILL),board=(DEATH_ACOLYTE,UNDEAD,FILLER),enemy=(UNDEAD,));self.play(g,KILL,self.first(g,UNDEAD,'board',2).id);self.play(g,KILL,self.first(g,FILLER,'board').id);self.assertFalse(g.state.draw_history);self.play(g,KILL,self.first(g,UNDEAD,'board').id);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
 def test_j1_death_acolyte_current_changed_tribes_and_unknown_rolls_back(self):
  g=self.game((TO_UNDEAD,KILL),board=(DEATH_ACOLYTE,FILLER));source=self.first(g,FILLER,'board').id;self.play(g,TO_UNDEAD,source);self.play(g,KILL,source);self.assertEqual(len(g.state.draw_history),1)
  g=self.game((KILL,),board=(DEATH_ACOLYTE,UNKNOWN));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,KILL,self.first(g,UNKNOWN,'board').id)
  self.assertEqual(g.snapshot(),snap)
 def test_k0_battlefiend_genuine_own_hero_attack_not_minion_or_bare_hero_damage(self):
  g=self.game((BARE,),board=(BATTLEFIEND,FILLER),enemy=(FILLER,));source=self.first(g,BATTLEFIEND,'board').id;self.play(g,BARE);g.apply(Attack(1,self.first(g,FILLER,'board').id,self.first(g,FILLER,'board',2).id));self.assertEqual(g.state.entities[source].attack,1);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[source].attack,2);self.portable(g)
 def test_k1_battlefiend_opponent_hero_attack_and_silence_do_not_grow(self):
  g=self.game((SILENCE,),board=(BATTLEFIEND,));source=self.first(g,BATTLEFIEND,'board').id;g.apply(EndTurn(1));g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id));self.assertEqual(g.state.entities[source].attack,1);g.apply(EndTurn(2));self.play(g,SILENCE,source);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(g.state.entities[source].attack,1)
 def test_l0_vapor_only_other_real_own_hand_elemental_play_not_summon_or_spell(self):
  g=self.game((ELEMENTAL,SUMMON_ELEMENTAL,NOP,FILLER),board=(VAPOR,));source=self.first(g,VAPOR,'board').id;self.play(g,SUMMON_ELEMENTAL);self.play(g,NOP);self.play(g,FILLER);self.assertEqual(g.state.entities[source].attack,1);self.play(g,ELEMENTAL);self.assertEqual(g.state.entities[source].attack,2);self.portable(g)
 def test_l1_vapor_submitted_current_hand_tribe_and_opponent_exclusion(self):
  g=self.game((HAND_ELEMENTAL,FILLER),board=(VAPOR,),enemy_hand=(ELEMENTAL,));source=self.first(g,VAPOR,'board').id;self.play(g,HAND_ELEMENTAL,self.first(g,FILLER).id);self.play(g,FILLER);self.assertEqual(g.state.entities[source].attack,2);g.apply(EndTurn(1));self.play(g,ELEMENTAL,pid=2);self.assertEqual(g.state.entities[source].attack,2)
 def test_z0_complete_raw_aliases_callbacks_and_central_assembly_preservation(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(13,13,26));self.assertFalse(d['cards']);r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),13)
  for x in d['dependencies']:
   raw=x['record'];source=d['reviewed_declaration_aliases'][raw['id']];self.assertEqual(r1.card(raw['id']),replace(r0.card(source),id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)))
  self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
