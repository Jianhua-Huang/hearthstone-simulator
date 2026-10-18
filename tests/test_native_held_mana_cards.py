"""Actual native mana-held branches, exact debits, lifecycle and portability."""
from functools import lru_cache
from dataclasses import replace
import json, unittest
from hs_sim.cards.native_held_mana_cards import ROOTS,TREANT,DRAGON,MERITHRA,WHELP,register_native_held_mana_cards
from hs_sim.engine import CardDefinition,CardType,Game,Registry,PlayerSetup,Scenario,PlayCard,EndTurn,SelectChoice,Zone
from hs_sim.engine.effects import (AddToHand,ChoiceOption,RequestChoice,SpendMana,ReturnToHand,InvokeBehavior,RefreshMana)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.held_mana import ability,validate_progress
from hs_sim.engine.model import PaymentType,HandProgressSpec
from hs_sim.engine.model import CostSpec
from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry
from hs_sim.engine.pools import GenerationContext,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard

P='k183.';HERO=P+'hero';CTX=GenerationContext('k183-bounded','experimental')

@lru_cache(maxsize=4)
def registry(role='writer'):
 r=Registry('k183-native-v1');register_native_held_mana_cards(r)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100))
 def fail(c):raise ResolutionError('k183 late deliberate failure')
 r.register_behavior(P+'fail',fail)
 def target(c):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id in ROOTS)
 scripts={
  'four':(4,lambda c:()),'three':(3,lambda c:()),'eight':(8,lambda c:()),'many':(25,lambda c:()),
  'free':(0,lambda c:()),'health':(4,lambda c:()),
  'consume':(0,lambda c:(SpendMana(c.player_id,4,c.source_id),)),
  'consumeall':(0,lambda c:(SpendMana(c.player_id,None,c.source_id),)),
  'refresh':(0,lambda c:(RefreshMana(c.player_id,20),)),
  'acquire':(4,lambda c:(AddToHand(c.player_id,TREANT),)),
  'discount':(0,lambda c:(AddToHand(c.player_id,P+'four',c.source_id,cost=CostSpec(set_to=1)),)),
  'repeat':(0,lambda c:(RepeatPlayedBattlecry(c.player_id,c.source_id,next(p.id for p in c.state.play_history if p.card_id==TREANT)),)),
  'copy':(0,lambda c:(CopyCard(CardReference.capture(target(c)),c.player_id,source_id=c.source_id),)),
  'deck':(0,lambda c:(MoveCard(CardReference.capture(target(c)),c.player_id,Zone.DECK),)),
  'bounce':(0,lambda c:(ReturnToHand(c.target_id),)),
  'wait':(4,lambda c:(RequestChoice(c.player_id,(ChoiceOption('ok','Continue'),ChoiceOption('bad','Fail',(InvokeBehavior(P+'fail',c.source_id,c.player_id),))),c.source_id),)),
  'fault':(4,lambda c:(InvokeBehavior(P+'fail',c.source_id,c.player_id),)),
 }
 for key,(cost,body)in scripts.items():
  r.register_behavior(P+key,body)
  kwargs=dict(attack=1,health=1,battlecry=P+key)if key=='repeat'else dict(on_play=P+key)
  r.register_card(CardDefinition(P+key,key,CardType.MINION if key=='repeat'else CardType.SPELL,cost=cost,
      cost_payment=PaymentType.HEALTH if key=='health' else PaymentType.MANA,requires_target=key=='bounce',**kwargs))
 r.register_pool(PoolDefinition('constructed.cards','k183-complete-bounded',CTX.target_id,CTX.mode,(PoolMember(DRAGON),),complete=True))
 r.validate();return r

class NativeHeldManaCardTests(unittest.TestCase):
 def test_central_registry_reuses_complete_existing_whelp(self):
  from hs_sim.cards import build_registry
  from hs_sim.cards.native_held_mana_cards import load_batch
  from dataclasses import asdict
  r=build_registry();self.assertTrue(set(ROOTS)<=set(r.cards))
  self.assertEqual(json.loads(json.dumps(asdict(r.card(WHELP)))),load_batch()['existing_definition_pins'][WHELP])
 def game(self,hand=(),enemy=(),board=(),mana=40):
  def names(xs):return tuple(x if x in ROOTS else P+x for x in xs)
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=names(hand),board=board,mana=mana,max_mana=40,mana_cap=60),
      PlayerSetup(HERO,hand=names(enemy),mana=40,max_mana=40,mana_cap=60)),seed=183,generation_context=CTX),registry())
 def eid(self,g,cid,zone='hand',pid=1):return next(i for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None):
  if cid not in ROOTS:cid=P+cid
  pid=g.state.active_player;eid=self.eid(g,cid,pid=pid)
  g.apply(PlayCard(pid,eid,target,position=len(g.state.players[pid].board)if g.state.entities[eid].kind==CardType.MINION else None));return eid
 def progress(self,g,cid=TREANT):return ability(g.state.entities[self.eid(g,cid)])
 def portable(self,g):
  s=json.loads(json.dumps(g.snapshot()));r=registry('reader');self.assertEqual(Game.from_snapshot(s,r).snapshot(),s)
  self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),registry('replay')).snapshot(),s)
 def test_treant_unready_temporary_and_ready_permanent(self):
  for ready in(False,True):
   g=self.game(('four',TREANT));
   if ready:self.play(g,'four')
   self.play(g,TREANT);p=g.state.players[1]
   self.assertEqual((p.max_mana,p.temporary_mana),(41,0)if ready else(40,1))
   self.assertEqual(g.state.play_history[-1].held_mana.completed,ready);self.portable(g)
 def test_actual_spend_not_printed_price_own_payment_or_health(self):
  g=self.game(('three','health','free',TREANT));self.play(g,'three');self.play(g,'health');self.play(g,'free')
  self.assertEqual(self.progress(g).progress_value,3);eid=self.play(g,TREANT)
  self.assertFalse(g.state.play_history[-1].held_mana.completed);self.assertEqual(ability(g.state.entities[eid]).progress_value,3);self.portable(g)
 def test_direct_consumption_combines_with_payment_once_and_caps(self):
  g=self.game(('three','consume',DRAGON));self.play(g,'three');self.play(g,'consume')
  a=self.progress(g,DRAGON);self.assertEqual((a.progress_value,a.progress_units),(7,(3,4)))
  self.assertEqual(tuple(x.split(':')[0]for x in a.progress_keys),('payment','consumption'));self.portable(g)
 def test_short_actual_consume_and_zero_mana_do_not_invent_spending(self):
  g=self.game(('consume','consume',TREANT),mana=2);self.play(g,'consume');self.play(g,'consume')
  self.assertEqual((self.progress(g).progress_value,self.progress(g).progress_units),(2,(2,)));self.portable(g)
 def test_opponent_payments_and_mana_refresh_do_not_advance(self):
  g=self.game((TREANT,'refresh'),enemy=('four',));g.apply(EndTurn(1));self.play(g,'four');g.apply(EndTurn(2));self.play(g,'refresh')
  self.assertEqual(self.progress(g).progress_value,0);self.portable(g)
 def test_acquired_after_payment_has_no_retroactive_credit(self):
  g=self.game(('acquire',));self.play(g,'acquire');self.assertEqual(self.progress(g).progress_value,0);self.portable(g)
 def test_reduced_actual_quote_credits_one_instead_of_four_printed(self):
  g=self.game(('discount',TREANT));self.play(g,'discount');self.play(g,'four')
  self.assertEqual(self.progress(g).progress_value,1);self.assertEqual(g.state.play_history[-1].cost,1);self.portable(g)
 def test_historical_battlecry_uses_original_condition_after_current_card_reset(self):
  g=self.game(('four',TREANT,'bounce','repeat'));self.play(g,'four');source=self.play(g,TREANT)
  self.play(g,'bounce',source);self.assertEqual(self.progress(g).progress_value,0)
  self.play(g,'repeat');self.assertEqual(g.state.players[1].max_mana,42);self.portable(g)
 def test_current_hand_copy_inherits_earned_counter_but_new_acquisition_resets(self):
  g=self.game(('three','copy',TREANT));self.play(g,'three');self.play(g,'copy')
  self.assertEqual([ability(g.state.entities[i]).progress_value for i in g.state.players[1].hand if g.state.entities[i].card_id==TREANT],[3,3]);self.portable(g)
  g=self.game(('four','bounce',TREANT));self.play(g,'four');eid=self.play(g,TREANT);self.play(g,'bounce',eid)
  self.assertEqual(self.progress(g).progress_value,0);self.portable(g)
 def test_two_ready_whelps_use_board_unready_ones_use_hand(self):
  for ready in(False,True):
   g=self.game(('eight',DRAGON));
   if ready:self.play(g,'eight')
   self.play(g,DRAGON);p=g.state.players[1];zone=p.board if ready else p.hand
   self.assertEqual(sum(g.state.entities[i].card_id==WHELP for i in zone),2);self.portable(g)
 def test_merithra_fills_actual_hand_and_binds_price_before_delivery(self):
  for ready in(False,True):
   g=self.game(('many',MERITHRA));
   if ready:self.play(g,'many')
   self.play(g,MERITHRA);self.assertEqual(len(g.state.players[1].hand),10)
   for eid in g.state.players[1].hand:
    if g.state.entities[eid].card_id==DRAGON:self.assertEqual(g.quote_cost(eid).amount,1 if ready else 4)
   self.portable(g)
 def test_mana_spend_wait_and_failure_restore_whole_condition(self):
  g=self.game(('wait',TREANT));self.play(g,'wait');self.assertTrue(self.progress(g).consumed);self.portable(g);s=g.snapshot();q=g.state.pending_choice
  with self.assertRaises(ResolutionError):g.apply(SelectChoice(q.player_id,q.id,('bad',)))
  self.assertEqual(g.snapshot(),s);g.apply(SelectChoice(q.player_id,q.id,('ok',)));self.play(g,TREANT);self.portable(g)
 def test_late_action_failure_reverts_progress_debit_and_history(self):
  g=self.game(('fault',TREANT));s=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,'fault')
  self.assertEqual(g.snapshot(),s)
 def test_frozen_paid_condition_rejects_mutated_units_and_wrong_profile(self):
  g=self.game(('four',TREANT));self.play(g,'four');self.play(g,TREANT);p=g.state.play_history[-1]
  validate_progress(g.state,registry(),p.held_mana,p)
  with self.assertRaises(ValueError):validate_progress(g.state,registry(),replace(p.held_mana,units=(3,)),p)
  with self.assertRaises(ValueError):validate_progress(g.state,registry(),replace(p.held_mana,before_payment_id=1),p)
  with self.assertRaises(ValueError):HandProgressSpec('mana_spent',goal=4)
  visible=json.dumps(g.observe(1));self.assertNotIn('before_payment_id',visible);self.assertNotIn('payment:',visible)

if __name__=='__main__':unittest.main()
