"""Original death occurrence thresholds feed real native automatic Fireballs."""
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p90_cards as cards
from hs_sim.cards.simple_followup_p90_cards import ARCHMAGE,FIREBALL,ROOTS,DEFERRED,load_batch,register_simple_followup_p90_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GrantDeathrattle,InvokeBehavior,RequestChoice,Silence,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,PlayerEffectSpec,Runes,SecretSpec
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.secrets import SetSecret
P='p90.test.'
HERO,FILLER,KILL,SWEEP,SILENCE,TAKE,TRIGGER,GRANT,POWER,COUNTER,SECRET,RESTRICT=(P+x for x in('hero','filler','kill','sweep','silence','take','trigger','grant','power','counter','secret','restrict'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta():return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=(),factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p90_cards.register_simple_followup_p90_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 if ARCHMAGE not in r.cards:register_simple_followup_p90_cards(r)
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(None)
def original_fireball():
 r=baseline_registry();d=r.card(FIREBALL);b=r.behavior(d.on_play);assert not b.__code__.co_freevars;return d,b
def registry(mode):
 r=Registry('p90-native-small');definition,body=original_fireball();r.register_card(definition);r.register_behavior(definition.on_play,body);register_simple_followup_p90_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P90 deliberate native continuation failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 r.register_secret_condition(P+'counter',lambda c:c.window is not None and c.window.kind=='spell'and c.state.entities[c.window.source_id].card_id==FIREBALL)
 r.register_behavior(P+'counter-spell',lambda c:(CounterSpell(c.window.id),))
 r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(SECRET,('card_committed',),P+'counter',P+'counter-spell'),metadata=meta()))
 r.register_player_effect(PlayerEffectSpec(P+'minions-only',RESTRICT,kind='turn_rule',target_policy='spells_no_heroes'))
 scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),SWEEP:lambda c:(DamageBatch(tuple(Damage(i,10,c.source_id,DamageKind.SPELL)for i in c.state.players[1].board if c.state.entities[i].card_id==ARCHMAGE)),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,1),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),GRANT:lambda c:(GrantDeathrattle(c.target_id,cards.PREFIX+ARCHMAGE,c.source_id),),COUNTER:lambda c:(SetSecret(2,SECRET),),RESTRICT:lambda c:(AddPlayerEffect(c.player_id,P+'minions-only',c.source_id),)}
 for cid,fn in scripts.items():
  r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,SILENCE,TAKE,TRIGGER,GRANT)else None,metadata=meta()))
 r.register_card(CardDefinition(FILLER,FILLER,CardType.MINION,cost=1,attack=1,health=20,metadata=meta()))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,cost=1,health=10,spell_damage=2,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):return c.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==FIREBALL
  r.register_trigger_condition(P+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec('spell_cast_finished'if mode=='finish'else'spell_cast_started',P+'wait',condition_id=P+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=meta(),**extra));r.validate();return r
@lru_cache(None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Frozen independent fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP90Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode;return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=9090),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def kill(self,g,count=1,pid=1):
  for _ in range(count):self.play(g,KILL,self.first(g,ARCHMAGE,'board',pid).id)
 def casts(self,g):return [x for x in g.state.cast_history if x.card_id==FIREBALL]
 def hp(self,g,pid=2):return g.state.entities[g.state.players[pid].hero_id].health
 def portable(self,g):
  r=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
  for pid in(1,2):
   text=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',text)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);s=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),s)

 def test_a0_actual_paid_root_and_printed_complete_metadata(self):
  g=self.game((ARCHMAGE,));eid=self.play(g,ARCHMAGE);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health,g.state.players[1].mana),(3,2,58));self.assertEqual(g.state.play_history[0].card_id,ARCHMAGE);self.assertFalse(self.casts(g));self.portable(g)
 def test_b0_first_four_do_not_count_own_death_as_other_fifth_casts_once(self):
  g=self.game((KILL,)*5,board=(ARCHMAGE,)*5)
  for count in range(1,6):self.kill(g);self.assertEqual(len(self.casts(g)),int(count==5))
  self.assertEqual((self.hp(g),g.state.players[1].mana),(94,60));cast,=self.casts(g);self.assertEqual((cast.origin,cast.play_id,cast.completed),('effect',None,True));self.assertEqual(len(g.state.play_history),5);self.portable(g)
 def test_b1_five_committed_simultaneous_deaths_each_see_four_others(self):
  g=self.game((SWEEP,),board=(ARCHMAGE,)*5);self.play(g,SWEEP);self.assertEqual((len(g.state.death_history),len(self.casts(g)),self.hp(g)),(5,5,70));self.assertEqual(len({d.batch for d in g.state.death_history}),1);self.portable(g)
 def test_b2_enemy_occurrences_and_unrelated_friendly_deaths_do_not_count(self):
  g=self.game((KILL,)*6,board=(ARCHMAGE,FILLER),enemy=(ARCHMAGE,)*4);self.kill(g,4,2);self.play(g,KILL,self.first(g,FILLER,'board').id);self.kill(g);self.assertFalse(self.casts(g));self.portable(g)
 def test_b3_actual_stolen_death_uses_current_controller(self):
  g=self.game((KILL,)*5+(TAKE,),board=(ARCHMAGE,)*4,enemy=(ARCHMAGE,));self.kill(g,4);eid=self.first(g,ARCHMAGE,'board',2).id;self.play(g,TAKE,eid);self.play(g,KILL,eid);self.assertEqual((len(self.casts(g)),self.hp(g)),(1,94));self.portable(g)
 def test_c0_live_trigger_uses_four_actual_other_deaths(self):
  g=self.game((KILL,)*4+(TRIGGER,),board=(ARCHMAGE,)*5);self.kill(g,4);self.play(g,TRIGGER,self.first(g,ARCHMAGE,'board').id);self.assertEqual((len(g.state.death_history),len(self.casts(g)),self.hp(g)),(4,1,94));self.portable(g)
 def test_c1_granted_native_deathrattle_uses_actual_different_carrier(self):
  g=self.game((KILL,)*5+(GRANT,),board=(ARCHMAGE,)*4+(FILLER,));self.kill(g,4);eid=self.first(g,FILLER,'board').id;self.play(g,GRANT,eid);self.play(g,KILL,eid);self.assertEqual((len(self.casts(g)),self.hp(g)),(1,94));self.portable(g)
 def test_c2_silenced_carrier_has_no_actual_deathrattle(self):
  g=self.game((KILL,)*5+(SILENCE,),board=(ARCHMAGE,)*5);self.kill(g,4);eid=self.first(g,ARCHMAGE,'board').id;self.play(g,SILENCE,eid);self.play(g,KILL,eid);self.assertFalse(self.casts(g));self.portable(g)
 def test_d0_native_fireball_spell_damage_is_not_minion_ability_damage(self):
  g=self.game((KILL,)*5,board=(ARCHMAGE,)*5+(POWER,));self.kill(g,5);self.assertEqual(self.hp(g),92);self.assertEqual(self.hp(g,1),100);self.assertTrue(all(x.health_result.damage_kind==DamageKind.SPELL.value for x in g.state.damage_history));self.portable(g)
 def test_d1_automatic_fireball_bypasses_hand_commit_secret_without_second_play(self):
  g=self.game((COUNTER,)+(KILL,)*5,board=(ARCHMAGE,)*5);self.play(g,COUNTER);self.kill(g,5);cast,=self.casts(g);self.assertIsNone(cast.failure);self.assertTrue(cast.completed);self.assertEqual(self.hp(g),94);self.assertTrue(any(e.card_id==SECRET and e.zone==Zone.SECRET for e in g.state.entities.values()));self.assertEqual(len(g.state.play_history),6);self.assertFalse(any(e.kind=='card_committed'and g.state.entities[e.source_id].card_id==FIREBALL for e in g.events));self.portable(g)
 def test_d2_empty_restricted_enemy_domain_never_falls_back_to_friendly(self):
  g=self.game((RESTRICT,)+(KILL,)*5,board=(ARCHMAGE,)*5+(FILLER,));self.play(g,RESTRICT);self.kill(g,5);cast,=self.casts(g);self.assertIsNotNone(cast.failure);self.assertFalse(cast.payload_started);self.assertEqual(self.hp(g,1),100);self.assertEqual(self.first(g,FILLER,'board').health,20);self.portable(g)
 def test_e0_actual_cast_start_and_finish_wait_restore_replay_and_failed_resume(self):
  for mode in('start','finish'):
   g=self.game((KILL,)*5,board=(ARCHMAGE,)*5,mode=mode);self.kill(g,5);self.fail_wait(g);self.assertEqual(self.hp(g),100 if mode=='start' else 94);self.choose(g);self.assertEqual(self.hp(g),94);self.assertEqual(len(self.casts(g)),1);self.portable(g)
 def test_z0_one_definition_four_raws_two_strict_faces_and_four_rejected_preserved(self):
  d=load_batch();self.assertEqual((len(d['cards']),len(d['existing_dependencies']),len(d['evidence_only']),len(d['official_observations']),len(d['rejected_complete_primary_observations'])),(1,1,2,2,4));r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),1);self.assertTrue(all(i not in r1.cards for i in DEFERRED));self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
