"""Real paid entries, printed lifecycles and complete named Battlecry delivery."""
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p94_cards as cards
from hs_sim.cards.simple_followup_p94_cards import RAIDER,FOOTMAN,SHIELD,BOAR,HAWK,CULT,DEVIL,IMP,MISTAKE,CAT,FIRE,TABBY,FLAME,ROOTS,DEPENDENCIES,ALL_IDS,load_batch,register_simple_followup_p94_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonByCard,SummonCause,SummonEntryMaterial
from hs_sim.engine.tribes import ChangeMinionTribes,has_any_subtype,has_any_tribe,tribe_state
from hs_sim.targets import canonical_digest
P='p94.test.'
HERO,FILLER,PRIME,KILL,RETURN,SILENCE,REMOVE=(P+x for x in('hero','filler','prime','kill','return','silence','remove'))
SUMMONED=(CULT,DEVIL,IMP,CAT,FIRE)
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta():return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p94_cards.register_simple_followup_p94_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ALL_IDS)
 if not any(present):register_simple_followup_p94_cards(r)
 elif not all(present):raise AssertionError('Complete P94 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(None)
def preserved_registry(pin):
 if pin!=SOURCE_PIN:raise AssertionError('Source pin required')
 r=baseline_registry();r.freeze();return r
def registry(mode):
 r=Registry('p94-small-native');old=preserved_registry(SOURCE_PIN);r.register_card(old.card(FLAME));r.register_pool_card(old.pool_cards[FLAME]);register_simple_followup_p94_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P94 deliberate native transaction failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 r.register_behavior(P+'fill',lambda c:(AddToHand(1,FILLER,c.source_id),))
 scripts={PRIME:lambda c:(),KILL:lambda c:(Destroy(c.target_id,c.source_id),),RETURN:lambda c:(ReturnToHand(c.target_id),),SILENCE:lambda c:(Silence(c.target_id),),REMOVE:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('remove',('demon',)),c.source_id),)}
 for cid in SUMMONED:scripts[P+'summon.'+cid]=lambda c,cid=cid:(SummonByCard(c.player_id,(SummonEntryMaterial(cid),),SummonCause.capture(c)),)
 for cid,fn in scripts.items():
  r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,RETURN,SILENCE,REMOVE)else None,metadata=meta()))
 r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=1,attack=2,health=8,metadata=meta()))
 extra={}
 if mode:
  event={'entry':'minion_summoned','hand':'card_added_to_hand','reject':'card_added_to_hand','fill':'card_committed','combo':'stats_changed','overload':'overload_added','awaken':'minion_awakened'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='overload':return c.event.player_id==1
   if mode in('entry','awaken'):return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==(TABBY if mode=='entry'else IMP)
   if mode in('hand','reject'):return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==FLAME
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==(FIRE if mode=='fill'else CULT)
  r.register_trigger_condition(P+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,P+('fill'if mode=='fill'else'fail'if mode=='reject'else'wait'),condition_id=P+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=meta(),**extra));r.validate();return r
@lru_cache(None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Independent immutable registry key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP94Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),mode=None):
  self.mode=mode;return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60),PlayerSetup(HERO,board=enemy,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=9494),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,position=None):
  e=self.first(g,cid);g.apply(PlayCard(1,e.id,target_id=target,position=len(g.state.players[1].board)if position is None and e.kind==CardType.MINION else position));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def portable(self,g):
  r=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
  for pid in(1,2):
   text=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities','dormancy_id','combo_history'):self.assertNotIn('"'+key+'"',text)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);s=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),s)
 def test_a0_all_twelve_paid_entries_keep_full_printed_stats_and_metadata(self):
  d=load_batch()
  for item in d['dependencies']:
   raw=item['record'];cid=raw['id']
   with self.subTest(cid=cid):
    g=self.game((cid,));source=self.play(g,cid);e=g.state.entities[source];attack=0 if cid==SHIELD else raw['attack'];self.assertEqual((e.attack,e.max_health,g.state.players[1].mana),(attack,raw['health'],59));self.assertEqual(g.state.play_history[0].card_id,cid);self.assertEqual(g.registry.card(cid).metadata,cards.metadata_from_record(raw))
  self.assertIsNone(next(x['record']['attack']for x in d['dependencies']if x['record']['id']==SHIELD));self.assertEqual(d['numeric_normalizations'],{SHIELD:{'attack':0}})
 def test_b0_charge_uses_normal_immediate_hero_attack(self):
  g=self.game((BOAR,));source=self.play(g,BOAR);g.apply(Attack(1,source,g.state.players[2].hero_id));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,99);self.portable(g)
 def test_b1_both_printed_taunts_block_hero_attack(self):
  for cid in(FOOTMAN,SHIELD):
   g=self.game(board=(FILLER,),enemy=(cid,));s=g.snapshot()
   with self.assertRaises(IllegalAction):g.apply(Attack(1,self.first(g,FILLER,'board').id,g.state.players[2].hero_id))
   self.assertEqual(g.snapshot(),s);g.apply(Attack(1,self.first(g,FILLER,'board').id,self.first(g,cid,'board',2).id))
 def test_b2_both_printed_windfury_minions_have_exactly_two_normal_attacks(self):
  for cid in(HAWK,DEVIL):
   g=self.game(board=(cid,));source=self.first(g,cid,'board').id;hero=g.state.players[2].hero_id
   for _ in range(2):g.apply(Attack(1,source,hero))
   s=g.snapshot()
   with self.assertRaises(IllegalAction):g.apply(Attack(1,source,hero))
   self.assertEqual(g.snapshot(),s);self.assertEqual(g.state.entities[hero].health,100-2*g.registry.card(cid).attack);self.assertEqual(g.state.players[1].overload_owed,0)
 def test_c0_cult_first_play_disabled_and_real_prior_play_enables_self_combo(self):
  g=self.game((CULT,));source=self.play(g,CULT);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,2));self.assertFalse(g.state.combo_history)
  g=self.game((PRIME,CULT));self.play(g,PRIME);source=self.play(g,CULT);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,3));row,=g.state.combo_history;self.assertEqual((row.source_id,row.player_id,row.card_id,row.play_id),(source,1,CULT,2));self.assertTrue(row.completed);self.assertEqual(g.state.players[1].mana,59);self.assertFalse(g.state.battlecry_history);self.portable(g)
 def test_c1_combo_stats_wait_restores_without_rebuff_or_repayment(self):
  g=self.game((PRIME,CULT),mode='combo');self.play(g,PRIME);source=self.play(g,CULT);self.fail_wait(g);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,3));self.choose(g);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health,g.state.players[1].mana),(2,3,59));self.assertEqual(len(g.state.combo_history),1);self.portable(g)
 def test_d0_devil_pending_overload_locks_only_next_own_turn_then_releases(self):
  g=self.game((DEVIL,));self.play(g,DEVIL);p=g.state.players[1];self.assertEqual((p.mana,p.overload_owed,p.overload_locked),(59,2,0));self.cycle(g);p=g.state.players[1];self.assertEqual((p.mana,p.overload_owed,p.overload_locked),(58,0,2));self.cycle(g);p=g.state.players[1];self.assertEqual((p.mana,p.overload_owed,p.overload_locked),(60,0,0));self.portable(g)
 def test_d1_devil_overload_wait_keeps_one_native_increment(self):
  g=self.game((DEVIL,),mode='overload');self.play(g,DEVIL);self.fail_wait(g);self.assertEqual(g.state.players[1].overload_owed,2);self.choose(g);self.assertEqual(g.state.players[1].overload_owed,2);self.assertEqual(len([e for e in g.events if e.kind=='overload_added']),1);self.portable(g)
 def test_e0_imp_two_controller_starts_keep_identity_then_wake_with_taunt(self):
  g=self.game((IMP,KILL),enemy=(FILLER,));source=self.first(g,IMP).id;self.assertIsNone(g.state.entities[source].dormancy);self.play(g,IMP);self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2);s=g.snapshot()
  with self.assertRaises(IllegalAction):self.play(g,KILL,source)
  self.assertEqual(g.snapshot(),s);g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2);g.apply(EndTurn(2));self.assertEqual(g.state.entities[source].dormancy.remaining_turns,1);self.cycle(g);self.assertIsNone(g.state.entities[source].dormancy);self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.assertEqual(len([e for e in g.events if e.kind=='minion_awakened']),1);self.assertEqual(len(g.state.play_history),1);s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
  self.assertEqual(g.snapshot(),s);g.apply(EndTurn(1));s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(2,self.first(g,FILLER,'board',2).id,g.state.players[1].hero_id))
  self.assertEqual(g.snapshot(),s);self.portable(g)
 def test_e1_dormant_taunt_does_not_protect_hero_and_still_occupies_slot(self):
  g=self.game((IMP,),enemy=(FILLER,));source=self.play(g,IMP);g.apply(EndTurn(1));g.apply(Attack(2,self.first(g,FILLER,'board',2).id,g.state.players[1].hero_id));self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,98);self.assertIn(source,g.state.players[1].board)
  g=self.game((IMP,CAT),board=(FILLER,)*5);self.play(g,IMP);self.play(g,CAT);self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(e.card_id==TABBY for e in g.state.entities.values()))
 def test_e2_actual_awaken_wait_retains_countdown_transition_and_no_new_summon(self):
  g=self.game((IMP,),mode='awaken');source=self.play(g,IMP);self.cycle(g);self.cycle(g);self.fail_wait(g);self.assertIsNone(g.state.entities[source].dormancy);count=len([e for e in g.events if e.kind=='minion_summoned']);self.choose(g);self.assertEqual(len([e for e in g.events if e.kind=='minion_summoned']),count);self.assertEqual(len(g.state.play_history),1);self.portable(g)
 def test_e3_return_awake_imp_restarts_native_dormancy_on_actual_replay(self):
  g=self.game((IMP,RETURN));source=self.play(g,IMP);self.cycle(g);self.cycle(g);self.play(g,RETURN,source);self.assertIsNone(g.state.entities[source].dormancy);self.play(g,IMP);self.assertEqual(g.state.entities[source].dormancy.remaining_turns,2);self.assertEqual(g.state.entities[source].id,source);self.portable(g)
 def test_f0_all_types_remains_wildcard_with_shared_current_and_printed_queries(self):
  g=self.game((REMOVE,SILENCE),board=(MISTAKE,IMP));e=self.first(g,MISTAKE,'board');self.assertEqual(g.registry.card(MISTAKE).metadata.tribes,('all',))
  for tribe in('mech','murloc','draenei','future_constructed_type'):self.assertTrue(has_any_tribe(g.registry,e,(tribe,)))
  self.assertFalse(has_any_subtype(g.registry,e,('imp',)));self.assertTrue(has_any_subtype(g.registry,self.first(g,IMP,'board'),('imp',)));self.play(g,REMOVE,e.id);e=g.state.entities[e.id];self.assertEqual(tribe_state(g.registry,e).excluded,('demon',));self.assertFalse(has_any_tribe(g.registry,e,('demon',)));self.assertTrue(has_any_tribe(g.registry,e,('demon',),basis='printed'));self.play(g,SILENCE,e.id);e=g.state.entities[e.id];self.assertTrue(has_any_tribe(g.registry,e,('demon',)));self.portable(g)
 def test_g0_cat_battlecry_summons_fresh_exact_child_to_actual_middle_right(self):
  g=self.game((CAT,),board=(FILLER,FILLER));source=self.play(g,CAT,position=1);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[FILLER,CAT,TABBY,FILLER]);child=self.first(g,TABBY,'board');self.assertEqual((child.attack,child.health),(1,1));self.assertNotEqual(source,child.id);cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.source.entity_id,cause.source.card_id,cause.player_id),(source,CAT,1));self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
 def test_g1_cat_ordinary_capacity_keeps_parent_and_never_overfills(self):
  for existing,children in((5,1),(6,0)):
   g=self.game((CAT,),board=(FILLER,)*existing);self.play(g,CAT,position=0);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(len([e for e in g.state.entities.values()if e.card_id==TABBY]),children);self.assertEqual(g.state.players[1].mana,59)
 def test_g2_cat_original_child_entry_wait_restores_without_duplicate_summon(self):
  g=self.game((CAT,),board=(FILLER,FILLER),mode='entry');self.play(g,CAT,position=1);self.fail_wait(g);child=self.first(g,TABBY,'board').id;self.choose(g);self.assertEqual([e.id for e in g.state.entities.values()if e.card_id==TABBY],[child]);self.assertEqual(len(g.state.card_summon_history),1);self.portable(g)
 def test_g3_ordinary_summon_never_runs_battlecry_combo_or_overload(self):
  for cid in SUMMONED:
   g=self.game((P+'summon.'+cid,));self.play(g,P+'summon.'+cid);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[cid]);self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.combo_history);self.assertEqual(g.state.players[1].overload_owed,0)
   if cid==IMP:self.assertEqual(self.first(g,IMP,'board').dormancy.remaining_turns,2)
 def test_h0_fire_exact_existing_flame_elemental_is_added_and_actually_playable(self):
  g=self.game((FIRE,));source=self.play(g,FIRE);child=self.first(g,FLAME);self.assertEqual((child.attack,child.health,g.registry.card(FLAME).cost),(1,2,1));self.assertTrue(any(e.kind=='card_added_to_hand'and e.source_id==source and e.target_id==child.id for e in g.events));self.play(g,FLAME);self.assertEqual(g.state.players[1].mana,58);self.assertEqual(len(g.state.battlecry_history),1);self.portable(g)
 def test_h1_fire_actual_hand_wait_restores_without_second_delivery(self):
  g=self.game((FIRE,),mode='hand');self.play(g,FIRE);self.fail_wait(g);child=self.first(g,FLAME).id;self.choose(g);self.assertEqual(g.state.players[1].hand,[child]);self.assertEqual(g.state.players[1].mana,59);self.portable(g)
 def test_h2_fire_observer_failure_rolls_back_whole_original_paid_action(self):
  g=self.game((FIRE,),mode='reject');s=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,FIRE)
  self.assertEqual(g.snapshot(),s)
 def test_h3_fire_full_hand_burns_complete_existing_child_normally(self):
  g=self.game((FIRE,)+(FILLER,)*9,mode='fill');self.play(g,FIRE);children=[e for e in g.state.entities.values()if e.card_id==FLAME];self.assertEqual(len(children),1);self.assertEqual((children[0].zone,children[0].attack,children[0].health),(Zone.GRAVEYARD,1,2));self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)
 def test_z0_thirteen_complete_rows_and_existing_assembly_are_preserved(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations']),len(d['exact_parent_child_links']),len(d['source_tag_links'])),(12,1,26,4,2));self.assertFalse(d['new_standard_collectible_roots']);r0,r1=baseline_registry(),batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),12);self.assertEqual({cid:r1.card(cid)for cid in r0.cards},r0.cards);self.assertEqual({cid:r1.pool_cards[cid]for cid in r0.pool_cards},r0.pool_cards);existing,=d['existing_dependencies'];self.assertEqual(canonical_digest(asdict(r1.card(FLAME))),existing['definition_sha256']);self.assertEqual(canonical_digest(asdict(r1.pool_cards[FLAME])),existing['pool_card_sha256'])
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
