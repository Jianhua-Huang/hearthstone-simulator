"""Actual paid bodies, original deaths and complete named delivery receipts."""
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from tools.card_batch import registration_prefix
from hs_sim.cards import simple_followup_p92_cards as cards
from hs_sim.cards.simple_followup_p92_cards import KVALDIR,FORAGER,MECHAROO,CRYSTALLIZER,HORROR,LIBRARIAN,BAT,REAVER,LEPER,TINYFIN,JOE,SOUL,ROOTS,DEPENDENCIES,ALL_IDS,load_batch,register_simple_followup_p92_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,Game,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes
from hs_sim.engine.pools import GenerateFromPool,GenerationContext,PoolCard,PoolDefinition,PoolMember,PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
P='p92.test.'
HERO,LOW,ONE,FILLER,KILL,HIT,BUFF,SILENCE,TAKE,RETURN,TRIGGER,POWER,GENERATE,UNKNOWN=(P+x for x in('hero','low','one','filler','kill','hit','buff','silence','take','return','trigger','power','generate','unknown'))
CONTEXT=GenerationContext('p92-bounded-complete-host','experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta():return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=())
def baseline_registry():
 return registration_prefix(build_registry,'hs_sim.cards.simple_followup_p92_cards.register_simple_followup_p92_cards',register_simple_followup_p92_cards)
def batch_registry():
 r=registration_prefix(build_registry,'hs_sim.cards.simple_followup_p92_cards.register_simple_followup_p92_cards',register_simple_followup_p92_cards,after=True)
 r.validate();return r
def registry(mode,members):
 r=Registry('p92-small-native');register_simple_followup_p92_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P92 deliberate native transaction failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 r.register_behavior(P+'fill',lambda c:(AddToHand(1,FILLER,c.source_id),))
 scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),BUFF:lambda c:(Buff(c.target_id,4,4,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),RETURN:lambda c:(ReturnToHand(c.target_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),GENERATE:lambda c:(GenerateFromPool(c.player_id,'p92.past',PoolQuery(kinds=(CardType.MINION,),collectible=True,min_cost=1,max_cost=1),destination='board',source_id=c.source_id,cause=SummonCause.capture(c)),)}
 for cid,fn in scripts.items():
  r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid!=GENERATE else None,metadata=meta()))
 r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=1,attack=1,health=20,metadata=meta()))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,cost=1,health=20,spell_damage=5,metadata=meta()))
 extra={}
 if mode:
  event={'entry':'minion_summoned','hand':'card_added_to_hand','draw':'card_drawn','health':'health_resolved','reject':'health_resolved','fill':'card_committed'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='entry':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id in(TINYFIN,JOE)
   if mode=='hand':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==SOUL
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in((KILL,)if mode=='fill'else(LIBRARIAN,)if mode=='draw'else(CRYSTALLIZER,REAVER))
  r.register_trigger_condition(P+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,P+'fill'if mode=='fill'else P+'fail'if mode=='reject'else P+'wait',condition_id=P+'eligible'),)
 for cid,hp in((HERO,100),(LOW,5),(ONE,1)):r.register_card(CardDefinition(cid,cid,CardType.HERO,health=hp,metadata=meta(),**extra))
 if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,1,CardMetadata(True,(CardClass.NEUTRAL,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=()),battlecry=False,deathrattle=False,choose_one=False,attack=1))
 r.register_pool(PoolDefinition('p92.past','p92-bounded-complete',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(cid)for cid in members),complete=True));r.validate();return r
@lru_cache(None)
def fixture_registry(mode,members,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable independent registry key required')
 r=registry(mode,members);r.freeze();return r

class SimpleFollowupP92Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),mode=None,members=ROOTS,deck=(FILLER,)*8,hero=HERO,enemy_hero=HERO,armor=0):
  self.config=(mode,members);return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,armor=armor),PlayerSetup(enemy_hero,board=enemy,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=9292,generation_context=CONTEXT),fixture_registry(*self.config,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
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

 def test_a0_all_twelve_actual_paid_entries_complete_scalars_and_metadata(self):
  for cid in ALL_IDS:
   with self.subTest(cid=cid):
    g=self.game((cid,));source=self.play(g,cid);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid);e=g.state.entities[source];self.assertEqual((e.attack,e.max_health,g.state.players[1].mana),(raw['attack'],raw['health'],59));self.assertEqual(g.registry.card(cid).metadata,cards.metadata_from_record(raw));self.assertEqual(g.state.play_history[0].card_id,cid)
 def test_b0_kvaldir_actual_self_damage_and_normal_pool_summon_no_battlecry(self):
  g=self.game((KVALDIR,),board=(POWER,));source=self.play(g,KVALDIR);self.assertEqual((g.state.entities[source].health,g.state.entities[source].damage),(1,3));r,=g.state.damage_history;self.assertEqual((r.health_result.source_id,r.health_result.base_amount,r.health_result.spell_bonus),(source,3,0));self.portable(g)
  g=self.game((GENERATE,),members=(KVALDIR,));self.play(g,GENERATE);self.assertEqual(self.first(g,KVALDIR,'board').health,4);self.assertFalse(g.state.damage_history);self.assertFalse(g.state.battlecry_history);self.portable(g)
 def test_b1_crystallizer_damage_then_fixed_armor_with_existing_armor(self):
  for armor,hp in((0,95),(7,100)):
   g=self.game((CRYSTALLIZER,),board=(POWER,),armor=armor);self.play(g,CRYSTALLIZER);self.assertEqual((self.hp(g),self.armor(g)),(hp,5 if armor==0 else 7));self.portable(g)
 def test_b2_crystallizer_health_wait_precedes_armor_and_resumes_once(self):
  g=self.game((CRYSTALLIZER,),mode='health');self.play(g,CRYSTALLIZER);self.fail_wait(g);self.assertEqual((self.hp(g),self.armor(g)),(95,0));self.choose(g);self.assertEqual((self.hp(g),self.armor(g)),(95,5));self.portable(g)
 def test_b3_crystallizer_actual_lethal_damage_cannot_be_saved_by_later_armor(self):
  g=self.game((CRYSTALLIZER,),hero=LOW);self.play(g,CRYSTALLIZER);self.assertEqual((g.state.status,g.state.winner,self.hp(g)),('finished',2,0));self.assertEqual(self.armor(g),0);self.portable(g)
 def test_c0_librarian_original_draw_precedes_hero_damage_and_fatigue_is_separate(self):
  g=self.game((LIBRARIAN,));source=self.play(g,LIBRARIAN);self.assertEqual((self.hp(g),len(g.state.draw_history)),(98,1));self.assertEqual(g.state.draw_history[0].source_id,source);self.portable(g)
  g=self.game((LIBRARIAN,),deck=());self.play(g,LIBRARIAN);self.assertEqual(self.hp(g),97);self.assertEqual(g.state.draw_history[0].outcome,'fatigue');self.portable(g)
 def test_c1_librarian_real_draw_wait_keeps_original_damage_tail(self):
  g=self.game((LIBRARIAN,),mode='draw');self.play(g,LIBRARIAN);self.fail_wait(g);self.assertEqual(self.hp(g),100);self.choose(g);self.assertEqual((self.hp(g),len(g.state.draw_history)),(98,1));self.portable(g)
 def test_d0_reaver_one_simultaneous_hero_batch_and_settled_wait(self):
  g=self.game((REAVER,),board=(POWER,),mode='health');self.play(g,REAVER);self.fail_wait(g);self.assertEqual((self.hp(g),self.hp(g,2)),(99,99));rows=g.state.damage_history;self.assertEqual(len(rows),2);self.assertEqual(len({r.health_result.batch_id for r in rows}),1);self.assertTrue(all(r.health_result.spell_bonus==0 for r in rows));self.choose(g);self.portable(g)
 def test_d1_reaver_simultaneous_lethal_heroes_draw_instead_of_first_winner(self):
  g=self.game((REAVER,),hero=ONE,enemy_hero=ONE);self.play(g,REAVER);self.assertEqual((self.hp(g),self.hp(g,2),g.state.status,g.state.winner),(0,0,'draw',None));self.portable(g)
 def test_d2_reaver_callback_failure_rolls_back_both_heroes_card_and_payment(self):
  g=self.game((REAVER,),mode='reject');s=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,REAVER)
  self.assertEqual(g.snapshot(),s)
 def test_e0_two_exact_named_death_summons_original_slot_source_and_fresh_stats(self):
  for parent,child in((FORAGER,TINYFIN),(MECHAROO,JOE)):
   g=self.game((BUFF,KILL),board=(FILLER,parent,FILLER));source=self.first(g,parent,'board').id;self.play(g,BUFF,source);self.play(g,KILL,source);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[FILLER,child,FILLER]);e=self.first(g,child,'board');self.assertEqual((e.attack,e.health),(1,1));self.assertNotEqual(e.id,source);cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.source.entity_id,cause.source.card_id,cause.player_id),(source,parent,1));self.portable(g)
 def test_e1_named_live_trigger_uses_right_side_and_full_board_respects_capacity(self):
  g=self.game((TRIGGER,),board=(FILLER,MECHAROO,FILLER));self.play(g,TRIGGER,self.first(g,MECHAROO,'board').id);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[FILLER,MECHAROO,JOE,FILLER]);self.assertFalse(g.state.death_history);self.portable(g)
  g=self.game((TRIGGER,),board=(MECHAROO,)+(FILLER,)*6);self.play(g,TRIGGER,self.first(g,MECHAROO,'board').id);self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(g.state.entities[i].card_id==JOE for i in g.state.players[1].board));self.portable(g)
 def test_e2_named_entry_wait_retains_retired_parent_and_failed_resume(self):
  g=self.game((KILL,),board=(FORAGER,),mode='entry');source=self.first(g,FORAGER,'board').id;self.play(g,KILL,source);self.fail_wait(g);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.choose(g);self.assertEqual(len(g.state.players[1].board),1);self.portable(g)
 def test_f0_horror_named_hand_child_actual_complete_playable_card(self):
  g=self.game((KILL,),board=(HORROR,));source=self.first(g,HORROR,'board').id;self.play(g,KILL,source);e=self.first(g,SOUL);self.assertEqual((e.attack,e.health),(2,1));self.assertFalse(g.state.draw_history);self.assertTrue(any(x.kind=='card_added_to_hand'and x.source_id==source for x in g.events));self.play(g,SOUL);self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)
 def test_f1_horror_hand_acquisition_wait_and_overflow_keep_actual_entity(self):
  g=self.game((KILL,),board=(HORROR,),mode='hand');self.play(g,KILL,self.first(g,HORROR,'board').id);self.fail_wait(g);self.choose(g);self.portable(g)
  g=self.game((KILL,)+(FILLER,)*9,board=(HORROR,),mode='fill');self.play(g,KILL,self.first(g,HORROR,'board').id);lost=[e for e in g.state.entities.values()if e.card_id==SOUL];self.assertEqual(len(lost),1);self.assertEqual((lost[0].zone,lost[0].attack,lost[0].max_health),(Zone.GRAVEYARD,2,1));self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(g.state.draw_history);self.portable(g)
 def test_g0_original_death_controller_routes_child_and_enemy_hero(self):
  for parent,child in((FORAGER,TINYFIN),(MECHAROO,JOE),(HORROR,SOUL)):
   g=self.game((TAKE,KILL),board=(parent,));source=self.first(g,parent,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);zone='hand'if parent==HORROR else'board';self.assertEqual(self.first(g,child,zone,2).controller,2);self.portable(g)
  g=self.game((TAKE,KILL),board=(LEPER,));source=self.first(g,LEPER,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);self.assertEqual((self.hp(g),self.hp(g,2)),(98,100));self.portable(g)
 def test_g1_silence_and_non_death_return_remove_or_reset_native_bodies(self):
  for cid in(FORAGER,MECHAROO,HORROR,BAT,LEPER):
   g=self.game((SILENCE,KILL),board=(cid,));source=self.first(g,cid,'board').id;self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertFalse(g.state.card_summon_history);self.assertFalse(any(e.card_id==SOUL for e in g.state.entities.values()));self.assertFalse(g.state.damage_history)
  g=self.game((RETURN,KILL),board=(MECHAROO,));source=self.first(g,MECHAROO,'board').id;self.play(g,RETURN,source);self.assertFalse(g.state.death_history);self.assertFalse(g.state.card_summon_history);self.play(g,MECHAROO);self.play(g,KILL,source);self.assertEqual(self.first(g,JOE,'board').health,1);self.portable(g)
 def test_h0_bat_native_random_enemy_damage_is_one_and_not_spell_damage(self):
  g=self.game((KILL,),board=(BAT,POWER),enemy=(FILLER,));source=self.first(g,BAT,'board').id;self.play(g,KILL,source);r,=g.state.damage_history;self.assertIn(r.health_result.target_id,(g.state.players[2].hero_id,self.first(g,FILLER,'board',2).id));self.assertEqual((r.health_result.source_id,r.health_result.base_amount,r.health_result.spell_bonus),(source,1,0));self.assertEqual(self.hp(g),100);self.portable(g)
  g=self.game((KILL,),board=(BAT,));self.play(g,KILL,self.first(g,BAT,'board').id);self.assertEqual(self.hp(g,2),99);self.portable(g)
 def test_h1_leper_original_enemy_hero_damage_ignores_spell_power(self):
  g=self.game((KILL,),board=(LEPER,POWER));source=self.first(g,LEPER,'board').id;self.play(g,KILL,source);self.assertEqual((self.hp(g),self.hp(g,2)),(100,98));self.assertEqual(g.state.damage_history[-1].health_result.source_id,source);self.portable(g)
 def test_i0_complete_host_pool_never_crops_qualifying_unknown(self):
  g=self.game((GENERATE,),members=(KVALDIR,UNKNOWN));s=g.snapshot()
  with self.assertRaises((ResolutionError,ValueError)):self.play(g,GENERATE)
  self.assertEqual(g.snapshot(),s)
 def test_z0_twelve_full_rows24_faces_six_api_edges_three_raw_tags_and_preservation(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['official_observations']),len(d['exact_parent_child_links']),len(d['source_tag_links'])),(12,24,6,3));self.assertFalse(d['cards']);self.assertFalse(d['numeric_normalizations']);self.assertFalse(d['new_standard_collectible_roots']);r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),12);self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for cid in DEPENDENCIES:self.assertFalse(r1.card(cid).metadata.collectible);self.assertIsNone(r1.card(cid).deathrattle);self.assertIsNone(r1.card(cid).battlecry)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
