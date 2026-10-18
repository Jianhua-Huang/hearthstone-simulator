"""Complete small minions exercise native payment, combat, death and generation."""
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p91_cards as cards
from hs_sim.cards.simple_followup_p91_cards import BATTLEMAGE,MOLE,FRESHMAN,ATTENDEE,HERMIT,AIR,SNAKE,LAB,QUEEN,WARBOT,EGG,WAX,SKATER,ROOTS,load_batch,register_simple_followup_p91_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p89_cards import PAST_POOL,WARDEN,register_simple_followup_p89_cards
from hs_sim.cards.native_past_entry_grant_cards import FLASHBACK,register_native_past_entry_grant_cards
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import Buff,ChangeControl,ChoiceOption,Damage,Destroy,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes
from hs_sim.engine.pools import GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.targets import canonical_digest
P='p91.test.'
HERO,FILLER,HIT,KILL,HEAL,SILENCE,BUFF,TAKE,RETURN,TRIGGER,SUMMON_SKATER,GENERATE,UNKNOWN=(P+x for x in('hero','filler','hit','kill','heal','silence','buff','take','return','trigger','summon-skater','generate','unknown'))
CONTEXT=GenerationContext('p91-explicit-bounded-past','experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta():return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p91_cards.register_simple_followup_p91_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p91_cards(r)
 elif not all(present):raise AssertionError('Complete P91 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode,members):
 r=Registry('p91-small-native-host');register_simple_followup_p91_cards(r);register_simple_followup_p89_cards(r);register_native_past_entry_grant_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P91 deliberate native waiting failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 scripts={HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),HEAL:lambda c:(Heal(c.target_id,1,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),BUFF:lambda c:(Buff(c.target_id,1,1,c.source_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),RETURN:lambda c:(ReturnToHand(c.target_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),SUMMON_SKATER:lambda c:(Summon(c.player_id,SKATER,0),),GENERATE:lambda c:(GenerateFromPool(c.player_id,PAST_POOL,PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1),destination='board',source_id=c.source_id,cause=SummonCause.capture(c)),)}
 for cid,body in scripts.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid not in(SUMMON_SKATER,GENERATE)else None,metadata=meta()))
 r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=1,attack=1,health=20,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):
   if c.player_id!=1:return False
   if mode in('entry','flashback'):
    if c.event.target_id is None:return False
    e=c.state.entities[c.event.target_id]
    if mode=='flashback'and e.card_id==SKATER and(e.attack,e.health)!=(2,1):raise ResolutionError('Actual Flashback grant missing at first Skaterbot notification')
    return e.card_id in(SKATER,MOLE)
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==EGG
  r.register_trigger_condition(P+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec('minion_summoned'if mode in('entry','flashback')else'card_drawn',P+'wait',condition_id=P+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=meta(),**extra))
 if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,1,CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=()),battlecry=False,deathrattle=False,choose_one=False,attack=1))
 r.register_pool(PoolDefinition(PAST_POOL,'p91-bounded-complete-fixture',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True));r.validate();return r
@lru_cache(None)
def fixture_registry(mode,members,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable independent fixture key required')
 r=registry(mode,members);r.freeze();return r

class SimpleFollowupP91Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,members=ROOTS,deck=(FILLER,)*8):
  self.config=(mode,members);return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=9191,generation_context=CONTEXT),fixture_registry(*self.config,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1,position=None):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=(len(g.state.players[pid].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def portable(self,g):
  r=fixture_registry(*self.config,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
  for pid in(1,2):
   text=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',text)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);s=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),s)
 def price(self,g,cid):return g.quote_cost(self.first(g,cid).id).amount

 def test_a0_all_thirteen_native_paid_entries_and_full_printed_metadata(self):
  for cid in ROOTS:
   with self.subTest(cid=cid):
    g=self.game((cid,));source=self.play(g,cid);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid);e=g.state.entities[source];self.assertEqual((e.attack,e.health,g.state.players[1].mana),(0 if cid in(EGG,WAX)else raw['attack'],raw['health'],59));self.assertEqual(g.state.play_history[0].card_id,cid);self.assertEqual(g.registry.card(cid).metadata,cards.metadata_from_record(raw))
 def test_a1_plain_minions_have_no_added_effect_and_exact_tribes(self):
  g=self.game((BATTLEMAGE,MOLE,FRESHMAN));self.play(g,BATTLEMAGE);self.play(g,MOLE);self.play(g,FRESHMAN);self.assertFalse(g.state.draw_history)
  for cid in(BATTLEMAGE,MOLE,FRESHMAN):
   d=g.registry.card(cid);self.assertFalse(d.keywords);self.assertIsNone(d.battlecry);self.assertIsNone(d.deathrattle)
  self.assertEqual(g.registry.card(MOLE).metadata.tribes,('beast',));self.portable(g)
 def test_b0_taunt_and_shield_block_hero_attack_and_absorb_one_packet(self):
  g=self.game(board=(FILLER,),enemy=(WAX,));wax=self.first(g,WAX,'board',2);s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,self.first(g,FILLER,'board').id,g.state.players[2].hero_id))
  self.assertEqual(g.snapshot(),s);g.apply(Attack(1,self.first(g,FILLER,'board').id,wax.id));self.assertEqual(g.state.entities[wax.id].health,2);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[wax.id].keywords);g.apply(EndTurn(1));s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(2,wax.id,g.state.players[1].hero_id))
  self.assertEqual(g.snapshot(),s);self.portable(g)
 def test_b1_hermit_cannot_attack_until_native_silence(self):
  g=self.game((SILENCE,),board=(HERMIT,),enemy=(FILLER,));e=self.first(g,HERMIT,'board');s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,e.id,self.first(g,FILLER,'board',2).id))
  self.assertEqual(g.snapshot(),s);self.play(g,SILENCE,e.id);g.apply(Attack(1,e.id,self.first(g,FILLER,'board',2).id));self.assertEqual(self.first(g,FILLER,'board',2).health,16);self.portable(g)
 def test_b2_air_elusive_rejects_friendly_and_enemy_manual_spells(self):
  g=self.game((BUFF,),board=(AIR,),enemy_hand=(KILL,));source=self.first(g,AIR,'board').id;s=g.snapshot()
  with self.assertRaises(IllegalAction):self.play(g,BUFF,source)
  self.assertEqual(g.snapshot(),s);g.apply(EndTurn(1));s=g.snapshot()
  with self.assertRaises(IllegalAction):self.play(g,KILL,source,pid=2)
  self.assertEqual(g.snapshot(),s);self.portable(g)
 def test_b3_pit_snake_actual_combat_poison_kills_large_survivor(self):
  g=self.game(board=(SNAKE,),enemy=(FILLER,));victim=self.first(g,FILLER,'board',2).id;g.apply(Attack(1,self.first(g,SNAKE,'board').id,victim));self.assertEqual(g.state.entities[victim].zone,Zone.GRAVEYARD);self.portable(g)
 def test_c0_lab_spell_damage_only_current_friendly_unsilenced_provider(self):
  g=self.game((HIT,SILENCE,HIT),board=(LAB,),enemy=(FILLER,LAB));victim=self.first(g,FILLER,'board',2).id;self.play(g,HIT,victim);self.assertEqual(g.state.entities[victim].damage,2);self.play(g,SILENCE,self.first(g,LAB,'board').id);self.play(g,HIT,victim);self.assertEqual(g.state.entities[victim].damage,3);self.portable(g)
 def test_c1_queen_admission_and_stack_then_silence_reprice_current_hand(self):
  g=self.game((QUEEN,QUEEN,MOLE,HIT,SILENCE,SILENCE));self.assertEqual(self.price(g,QUEEN),1);self.play(g,QUEEN);self.assertEqual((self.price(g,MOLE),self.price(g,HIT)),(3,0));self.play(g,QUEEN);self.assertEqual((self.price(g,MOLE),g.state.players[1].mana),(5,56))
  queens=tuple(g.state.players[1].board)
  for expected,eid in zip((3,1),queens):self.play(g,SILENCE,eid);self.assertEqual(self.price(g,MOLE),expected)
  self.play(g,MOLE);self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)
 def test_c2_queen_current_controller_and_return_lifetime(self):
  g=self.game((TAKE,RETURN,MOLE),board=(QUEEN,),enemy_hand=(MOLE,));source=self.first(g,QUEEN,'board').id;self.assertEqual(self.price(g,MOLE),3);self.play(g,TAKE,source);self.assertEqual(self.price(g,MOLE),1);g.apply(EndTurn(1));self.assertEqual(g.quote_cost(self.first(g,MOLE,pid=2).id).amount,3);g.apply(EndTurn(2));self.play(g,RETURN,source);self.assertEqual(g.state.entities[source].zone,Zone.HAND);self.assertEqual(self.price(g,MOLE),1);self.portable(g)
 def test_d0_warbot_current_damage_relation_never_stacks_and_full_heal_removes(self):
  g=self.game((HIT,HIT,HEAL,HEAL),board=(WARBOT,));source=self.first(g,WARBOT,'board').id
  for cid,attack in((HIT,2),(HIT,2),(HEAL,2),(HEAL,1)):self.play(g,cid,source);self.assertEqual(g.state.entities[source].attack,attack)
  self.assertEqual(g.state.entities[source].damage,0);self.portable(g)
 def test_d1_warbot_silence_removes_conditional_attack_without_healing(self):
  g=self.game((HIT,SILENCE),board=(WARBOT,));source=self.first(g,WARBOT,'board').id;self.play(g,HIT,source);self.play(g,SILENCE,source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].damage),(1,1));self.portable(g)
 def test_e0_egg_actual_death_draw_source_live_trigger_and_silence(self):
  g=self.game((TRIGGER,KILL),board=(EGG,));source=self.first(g,EGG,'board').id;self.play(g,TRIGGER,source);self.play(g,KILL,source);self.assertEqual(len(g.state.draw_history),2);self.assertTrue(all(d.source_id==source for d in g.state.draw_history));self.portable(g)
  g=self.game((SILENCE,KILL),board=(EGG,));source=self.first(g,EGG,'board').id;self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertFalse(g.state.draw_history)
 def test_e1_egg_dead_source_draw_wait_recovers_once_and_failed_resume_rolls_back(self):
  g=self.game((KILL,),board=(EGG,),mode='draw');self.play(g,KILL,self.first(g,EGG,'board').id);self.fail_wait(g);self.choose(g);self.assertEqual(len(g.state.draw_history),1);self.portable(g)
 def test_f0_skater_paid_magnetic_merges_with_real_warbot_and_grants_rush(self):
  g=self.game((WARBOT,SKATER),enemy=(FILLER,));host=self.play(g,WARBOT);source=self.play(g,SKATER,position=0);self.assertEqual(g.state.players[1].board,[host]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual((g.state.entities[host].attack,g.state.entities[host].health),(2,4));self.assertIn(Keyword.RUSH,g.state.entities[host].keywords);self.assertEqual(len(g.state.magnetic_history),1);s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,host,g.state.players[2].hero_id))
  self.assertEqual(g.snapshot(),s);g.apply(Attack(1,host,self.first(g,FILLER,'board',2).id));self.assertEqual(g.state.entities[host].attack,3);self.portable(g)
 def test_f1_skater_normal_paid_right_entry_and_ordinary_summon_never_merge(self):
  for cid in(SKATER,SUMMON_SKATER):
   g=self.game((cid,),board=(WARBOT,));self.play(g,cid);self.assertEqual(len(g.state.players[1].board),2);self.assertFalse(g.state.magnetic_history);self.assertEqual((self.first(g,SKATER,'board').attack,self.first(g,SKATER,'board').health),(1,1));self.portable(g)
 def test_f2_actual_amber_death_pool_skater_enters_left_of_mech_without_magnetic(self):
  g=self.game((KILL,),board=(WARDEN,WARBOT),members=(SKATER,),mode='entry');source=self.first(g,WARDEN,'board').id;self.play(g,KILL,source);self.fail_wait(g);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[SKATER,WARBOT]);self.assertFalse(g.state.magnetic_history);self.assertEqual(g.state.card_summon_history[-1].request.cause.source.card_id,WARDEN);self.choose(g);self.portable(g)
 def test_f3_native_one_cost_random_pool_summon_and_unknown_candidate_atomic_failure(self):
  g=self.game((GENERATE,),members=(SKATER,));self.play(g,GENERATE);self.assertEqual(self.first(g,SKATER,'board').health,1);self.assertFalse(g.state.magnetic_history);self.portable(g)
  g=self.game((GENERATE,),members=(SKATER,UNKNOWN));s=g.snapshot()
  with self.assertRaises((ResolutionError,ValueError)):self.play(g,GENERATE)
  self.assertEqual(g.snapshot(),s)
 def test_f4_actual_amber_mole_entry_wait_restores_original_death_cause(self):
  g=self.game((KILL,),board=(WARDEN,WARBOT),members=(MOLE,),mode='entry');self.play(g,KILL,self.first(g,WARDEN,'board').id);self.fail_wait(g);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[MOLE,WARBOT]);self.assertEqual(g.state.card_summon_history[-1].request.cause.source.card_id,WARDEN);self.choose(g);self.portable(g)
 def test_f5_actual_flashback_original_combo_grant_before_first_skater_notification(self):
  g=self.game((HIT,FLASHBACK),board=(WARBOT,),members=(SKATER,),mode='flashback');self.play(g,HIT,self.first(g,WARBOT,'board').id);source=self.play(g,FLASHBACK);self.fail_wait(g);self.assertEqual((self.first(g,SKATER,'board').attack,self.first(g,SKATER,'board').health),(2,1));self.assertFalse(g.state.magnetic_history);self.choose(g)
  bodies=[g.state.entities[i]for i in g.state.players[1].board if g.state.entities[i].card_id==SKATER];self.assertEqual([(e.attack,e.health)for e in bodies],[(2,1),(2,1)]);self.assertTrue(all(any(a.source_id==source and a.attack==1 for a in e.enchantments)for e in bodies));self.assertEqual(g.state.players[1].mana,58);self.assertFalse(g.state.magnetic_history);self.portable(g)
 def test_z0_full13_original_rows26_primary_faces_zero_evidence_and_assembly_preservation(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['official_observations'])),(13,26));self.assertFalse(d['cards']);self.assertFalse(d['new_standard_collectible_roots']);self.assertEqual(d['numeric_normalizations'],{EGG:{'attack':0},WAX:{'attack':0}});r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),13);self.assertTrue(all('CORE_'+cid not in r0.cards for cid in ROOTS));self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
