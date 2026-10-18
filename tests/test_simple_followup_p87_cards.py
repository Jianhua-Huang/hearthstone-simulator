"""Complete historical declarations through unchanged native health and utility code."""
from dataclasses import replace
from functools import lru_cache
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p87_cards as cards
from hs_sim.cards.simple_followup_p87_cards import (FIRE,INFERNAL,KINGS,BLADE,ARCHER,DOCTOR,IMP,PROTECTOR,SUNFURY,SEER,COMPANION,TOLVIR,PHOENIX,ROOTS,load_batch,register_simple_followup_p87_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.cards.utility_cards import load_batch as utility_batch,compile_body
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.effects import (ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes

TEST='p87.test.'
HERO,FILLER,MURLOC,ALL,UNKNOWN,DORMANT,LOCATION,PROVIDER=(TEST+i for i in('hero','filler','murloc','all','unknown','dormant','location','provider'))
NOP,HIT,WOUND,KILL,SILENCE,TO_MURLOC=(TEST+i for i in('nop','hit','wound','kill','silence','to-murloc'))
UTILITY=(PROTECTOR,SUNFURY,SEER,COMPANION)
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=tribes)
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p87_cards.register_simple_followup_p87_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(i in r.cards for i in ROOTS)
 if not any(present):register_simple_followup_p87_cards(r)
 elif not all(present):raise AssertionError('Complete P87 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(maxsize=1)
def original_fixture_sources():
 r=baseline_registry();definitions=tuple(r.card('CORE_'+i)for i in ROOTS);keys={r.card('CORE_'+i).battlecry for i in ROOTS if i not in UTILITY}
 assert all(not r.behavior(k).__code__.co_freevars for k in keys)
 return definitions,tuple((k,r.behavior(k))for k in sorted(keys))
def registry(mode):
 r=Registry('p87-small-original-native-callbacks');definitions,bodies=original_fixture_sources()
 for d in definitions:r.register_card(d)
 for key,body in bodies:r.register_behavior(key,body)
 # Original compiler binds unchanged utility stages to this small registry.
 registered=set()
 for row in utility_batch()['cards']:
  cid=row['record']['id']
  if cid not in('CORE_'+i for i in UTILITY):continue
  body=compile_body(r,row['recipe']['bodies']['battlecry'],False,registered);assert body==r.card(cid).battlecry
 register_simple_followup_p87_cards(r)
 for cid,tribes in((FILLER,()),(MURLOC,('murloc',)),(ALL,('all',)),(UNKNOWN,None),(DORMANT,('murloc',))):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=1,health=20,dormant_turns=2 if cid==DORMANT else 0,metadata=meta(tribes)))
 r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=1,durability=3,on_use=NOP,metadata=meta()))
 r.register_card(CardDefinition(PROVIDER,PROVIDER,CardType.MINION,health=8,spell_damage=5,metadata=meta()))
 r.register_behavior(TEST+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P87 deliberate continuation failure')))
 def wait(c):
  change=()
  if mode=='target':change=(Destroy(c.event.target_id,c.source_id),)
  elif mode=='source':change=(Destroy(c.event.target_id,c.source_id),)
  elif mode=='batch':change=(Summon(2,FILLER),)
  elif mode=='seer':
   target=next(c.state.entities[i]for i in c.state.players[1].board if c.state.entities[i].card_id==FILLER);change=(ChangeMinionTribes(MinionReference.capture(target),TribeChangeSpec('set',('murloc',)),c.source_id),)
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change current board',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 scripts={NOP:lambda c:(),HIT:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.EFFECT),),WOUND:lambda c:(Damage(c.state.players[c.player_id].hero_id,8,c.source_id,DamageKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TO_MURLOC:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('murloc',)),c.source_id),)}
 for cid,body in scripts.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec()if cid in(HIT,KILL,SILENCE,TO_MURLOC)else None,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):
   if c.player_id!=1:return False
   eid=c.event.source_id if mode in('target','batch')else c.event.target_id
   return eid is not None and c.state.entities[eid].card_id==(INFERNAL if mode=='batch'else SEER if mode=='seer'else FIRE)
  event='card_committed'if mode=='target'else'health_resolved'if mode=='batch'else'minion_summoned'
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP87Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),mode=None,armor=0):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*8,mana=50,max_mana=50,mana_cap=50,armor=armor),PlayerSetup(HERO,board=enemy,deck=(FILLER,)*8,mana=50,max_mana=50,mana_cap=50)),seed=8787),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,position=None):
  e=self.first(g,cid);g.apply(PlayCard(1,e.id,target_id=target,position=(len(g.state.players[1].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
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
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(g.snapshot(),snap)
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health

 def test_a0_all_thirteen_actual_paid_entries_printed_fields_and_full_native_declarations(self):
  for cid in ROOTS:
   g=self.game((cid,),board=(FILLER,),enemy=(FILLER,));target=self.first(g,FILLER,'board').id if cid in(PROTECTOR,COMPANION)else g.state.players[2].hero_id if cid in(FIRE,ARCHER,DOCTOR,PHOENIX)else None;before=g.state.players[1].mana;eid=self.play(g,cid,target);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid)
   self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(raw['attack'],3 if cid in(BLADE,TOLVIR)else raw['health']));self.assertEqual(before-g.state.players[1].mana,raw['cost']);self.assertEqual(g.state.play_history[-1].card_id,cid)
 def test_b0_fixed_native_damage_uses_real_new_source_and_ignores_spell_bonus(self):
  for cid,amount in((FIRE,4),(ARCHER,1),(PHOENIX,3)):
   g=self.game((cid,),board=(PROVIDER,),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;eid=self.play(g,cid,target);self.assertEqual(g.state.entities[target].damage,amount);row=g.state.damage_history[-1].health_result;self.assertEqual((row.source_id,row.source_card_id,row.damage_kind),(eid,cid,'effect'))
 def test_b1_fixed_target_selection_mandatory_and_rejects_hand_or_own_source(self):
  g=self.game((FIRE,FILLER));source=self.first(g,FIRE);other=self.first(g,FILLER);self.denied(g,PlayCard(1,source.id));self.denied(g,PlayCard(1,source.id,other.id));self.denied(g,PlayCard(1,source.id,source.id));self.play(g,FIRE,g.state.players[1].hero_id);self.assertEqual(self.hp(g),26)
 def test_c0_infernal_one_batch_all_other_characters_excludes_source_dormant_location(self):
  g=self.game((INFERNAL,),board=(FILLER,DORMANT,LOCATION),enemy=(FILLER,));source=self.play(g,INFERNAL);self.assertEqual((self.hp(g),self.hp(g,2)),(29,29));self.assertEqual(g.state.entities[source].damage,0);self.assertEqual(self.first(g,DORMANT,'board').damage,0);self.assertEqual(self.first(g,LOCATION,'board').durability,3);rows=g.state.damage_history;self.assertEqual(len(rows),4);self.assertEqual(len({x.health_result.batch_id for x in rows}),1)
 def test_c1_actual_batch_wait_sees_committed_group_and_no_damage_to_later_new_body(self):
  g=self.game((INFERNAL,),board=(FILLER,),enemy=(FILLER,),mode='batch');self.play(g,INFERNAL);self.fail_wait(g);self.assertEqual((self.hp(g),self.hp(g,2)),(29,29));self.assertTrue(all(g.state.entities[i].damage==1 for pid in(1,2)for i in g.state.players[pid].board if g.state.entities[i].card_id==FILLER));self.choose(g,'change');new=g.state.entities[g.state.players[2].board[-1]];self.assertEqual(new.damage,0);self.portable(g)
 def test_d0_both_self_damage_bodies_hit_actual_new_entity_only(self):
  for cid,damage in((BLADE,4),(TOLVIR,3)):
   g=self.game((cid,),board=(PROVIDER,));eid=self.play(g,cid);self.assertEqual(g.state.entities[eid].damage,damage);self.assertEqual((self.hp(g),self.hp(g,2)),(30,30));self.assertEqual(g.state.damage_history[-1].health_result.source_card_id,cid)
 def test_e0_kings_restores_six_to_own_hero_with_native_cap_and_taunt(self):
  g=self.game((WOUND,KINGS));self.play(g,WOUND);eid=self.play(g,KINGS);self.assertEqual((self.hp(g),self.hp(g,2)),(28,30));self.assertIn(Keyword.TAUNT,g.state.entities[eid].keywords);self.portable(g)
 def test_e1_voodoo_actual_two_health_any_character_and_full_health_no_invention(self):
  g=self.game((HIT,DOCTOR),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.play(g,HIT,target);eid=self.play(g,DOCTOR,target);self.assertEqual(g.state.entities[target].damage,1);self.assertEqual(g.state.healing_history[-1].health_result.source_id,eid)
  g=self.game((DOCTOR,));self.play(g,DOCTOR,g.state.players[1].hero_id);self.assertEqual(self.hp(g),30)
 def test_f0_flame_imp_own_hero_armor_and_damage_source(self):
  g=self.game((IMP,),armor=2);eid=self.play(g,IMP);hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.health,hero.armor),(29,0));self.assertEqual(g.state.entities[eid].health,2);self.assertEqual(g.state.damage_history[-1].health_result.source_id,eid)
 def test_g0_protector_targets_only_other_friendly_minion_and_native_shield_consumption(self):
  g=self.game((PROTECTOR,HIT),board=(FILLER,),enemy=(FILLER,));source=self.first(g,PROTECTOR);target=self.first(g,FILLER,'board').id
  for bad in(g.state.players[1].hero_id,self.first(g,FILLER,'board',2).id,source.id):self.denied(g,PlayCard(1,source.id,bad))
  self.play(g,PROTECTOR,target);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords);self.play(g,HIT,target);self.assertEqual(g.state.entities[target].damage,0);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[target].keywords)
 def test_g1_friendly_grants_allow_no_target_when_no_other_minion_exists(self):
  for cid in(PROTECTOR,COMPANION):
   g=self.game((cid,));eid=self.play(g,cid);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[eid].keywords);self.assertEqual(g.state.entities[eid].max_health,2)
 def test_h0_companion_two_health_buff_keeps_damage_and_excludes_source(self):
  g=self.game((HIT,COMPANION),board=(FILLER,));target=self.first(g,FILLER,'board').id;self.play(g,HIT,target);eid=self.play(g,COMPANION,target);e=g.state.entities[target];self.assertEqual((e.health,e.max_health,e.damage),(19,22,3));self.assertEqual(g.state.entities[eid].max_health,2)
 def test_i0_sunfury_physical_adjacent_recipients_and_permanent_taunt_lifecycle(self):
  g=self.game((SUNFURY,KILL,SILENCE),board=(FILLER,FILLER,FILLER));original=list(g.state.players[1].board);source=self.play(g,SUNFURY,position=1);self.assertEqual([Keyword.TAUNT in g.state.entities[i].keywords for i in original],[True,True,False]);self.play(g,KILL,source);self.assertIn(Keyword.TAUNT,g.state.entities[original[0]].keywords);self.play(g,SILENCE,original[0]);self.assertNotIn(Keyword.TAUNT,g.state.entities[original[0]].keywords);self.portable(g)
 def test_i1_sunfury_dormant_physical_slot_blocks_distant_neighbor(self):
  g=self.game((SUNFURY,),board=(FILLER,DORMANT,FILLER));original=list(g.state.players[1].board);self.play(g,SUNFURY,position=1);self.assertEqual([Keyword.TAUNT in g.state.entities[i].keywords for i in original],[True,False,False])
 def test_j0_seer_other_current_murlocs_all_and_changed_tribes_not_enemy_self_or_dormant(self):
  g=self.game((TO_MURLOC,SEER),board=(FILLER,MURLOC,ALL,DORMANT),enemy=(MURLOC,));target=self.first(g,FILLER,'board').id;self.play(g,TO_MURLOC,target);source=self.play(g,SEER);self.assertEqual([g.state.entities[i].max_health for i in g.state.players[1].board],[22,22,22,20,3]);self.assertEqual(self.first(g,MURLOC,'board',2).max_health,20);self.assertEqual(g.state.entities[source].max_health,3)
 def test_j1_seer_unknown_current_friendly_tribe_rolls_back_original_payment(self):
  g=self.game((SEER,),board=(UNKNOWN,));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,SEER)
  self.assertEqual(g.snapshot(),snap)
 def test_j2_actual_seer_summon_wait_queries_fresh_current_tribe(self):
  g=self.game((SEER,),board=(FILLER,),mode='seer');self.play(g,SEER);self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.first(g,FILLER,'board').max_health,22);self.portable(g)
 def test_k0_actual_target_commit_wait_keeps_original_target_and_payment(self):
  g=self.game((FIRE,),enemy=(FILLER,),mode='target');target=self.first(g,FILLER,'board',2).id;self.play(g,FIRE,target);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,44);self.assertEqual(self.hp(g,2),30);self.portable(g)
 def test_k1_actual_source_summon_wait_does_not_cancel_accepted_fixed_damage(self):
  g=self.game((FIRE,),enemy=(FILLER,),mode='source');target=self.first(g,FILLER,'board',2).id;source=self.play(g,FIRE,target);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[target].damage,4);self.portable(g)
 def test_z0_complete_raw_alias_fields_before_and_after_central_registration(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(13,13,26));self.assertFalse(d['cards']);r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),13)
  for x in d['dependencies']:
   raw=x['record'];source=d['reviewed_declaration_aliases'][raw['id']];self.assertEqual(r1.card(raw['id']),replace(r0.card(source),id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)))
  self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
