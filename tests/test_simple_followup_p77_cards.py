"""Real paid keyword dependencies; distinct combat and lifecycle paths share fixtures."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch

from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p77_cards as cards
from hs_sim.cards.simple_followup_p77_cards import (MASTER,CREEPER,FENCER,KNIGHT,PLAGUE,WORM,RECYCLER,HORSE,SPIDER,TROGG,ANNOY,ASSASSIN,ROOTS,load_batch,register_simple_followup_p77_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (Buff,ChoiceOption,CopyMinion,Damage,Destroy,InvokeBehavior,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import BoardPresenceReference,DamageKind,LimitedTriggerSpec,Runes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause

TEST='p77.test.'
HERO,HP,BIG,HARD,ZERO,SHIELDED,PING,WATCH,HIT,KILL,SILENCE,BOUNCE,COPY,GROW,HURT=(TEST+i for i in
 ('hero','power','big','hard','zero','shielded','battlecry','watch','hit','kill','silence','bounce','copy','grow','hurt'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
EXPECTED={MASTER:(3,5,(Keyword.WINDFURY,)),CREEPER:(3,6,(Keyword.TAUNT,)),FENCER:(5,4,(Keyword.DIVINE_SHIELD,)),KNIGHT:(4,6,(Keyword.ELUSIVE,)),PLAGUE:(2,5,(Keyword.POISONOUS,)),WORM:(4,4,(Keyword.LIFESTEAL,)),
 RECYCLER:(2,6,(Keyword.TAUNT,Keyword.LIFESTEAL)),HORSE:(3,4,(Keyword.DIVINE_SHIELD,Keyword.RUSH)),SPIDER:(1,3,(Keyword.POISONOUS,Keyword.RUSH)),TROGG:(1,5,(Keyword.TAUNT,Keyword.POISONOUS)),ANNOY:(3,4,(Keyword.TAUNT,Keyword.DIVINE_SHIELD)),ASSASSIN:(4,2,(Keyword.STEALTH,Keyword.REBORN))}
def metadata():return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=())
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p77_cards(r)
 elif not all(present):raise AssertionError('P77 requires complete assigned assembly')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p77-small-keyword-fixtures');register_simple_followup_p77_cards(r)
 r.register_behavior(HP,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.HERO_POWER),))
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=HP,targeting=TargetSpec(),metadata=metadata()))
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=metadata()))
 for cid,a,h,k in((BIG,2,30,()),(HARD,8,30,()),(ZERO,0,30,()),(SHIELDED,0,30,(Keyword.DIVINE_SHIELD,))):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=a,health=h,keywords=k,metadata=metadata()))
 r.register_behavior(PING,lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.MINION_ABILITY),))
 r.register_card(CardDefinition(PING,PING,CardType.MINION,health=20,battlecry=PING,targeting=TargetSpec(),metadata=metadata()))
 bodies={HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),
  BOUNCE:lambda c:(ReturnToHand(c.target_id),),COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
  GROW:lambda c:(Buff(c.target_id,2,3,source_id=c.source_id),),HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,6,c.source_id,DamageKind.EFFECT),)}
 for cid,body in bodies.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=None if cid==HURT else TargetSpec(),metadata=metadata()))
 if mode in('combat','death'):
  def eligible(c):
   if mode=='combat':return c.health_result is not None and c.health_result.source_card_id==HORSE and c.health_result.damage_dealt>0
   row=next((d for d in c.state.death_history if d.id==dict(c.event.data).get('death_id')),None)
   return row is not None and row.card_id==ASSASSIN
  def fail(c):raise ResolutionError('P77 deliberate continuation failure')
  r.register_behavior(TEST+'fail',fail);r.register_trigger_condition(TEST+'eligible',eligible)
  r.register_behavior(TEST+'pause',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))),c.source_id),))
  r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=30,metadata=metadata(),limited_triggers=(LimitedTriggerSpec('health_resolved'if mode=='combat'else'minion_died',TEST+'pause',condition_id=TEST+'eligible'),)))
 r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if mode not in(None,'combat','death')or role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP77Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,mana=50):
  self.mode=mode
  if mode:board=(WATCH,)+board
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(ZERO,)*8,mana=mana,max_mana=mana,mana_cap=50,hero_power_card_id=HP),
   PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(ZERO,)*8,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP)),seed=7777),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def health(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(snap,g.snapshot())
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint())
  snap=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for p in(1,2):
   visible=json.dumps(g.for_player(p).observe())+json.dumps(g.for_player(p).legal_actions())+json.dumps(g.player_events(p))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',visible)

 def test_a0_every_actual_paid_entry_has_exact_stats_keywords_and_single_payment(self):
  self.assertEqual(set(EXPECTED),set(ROOTS))
  for cid,(a,h,k)in EXPECTED.items():
   with self.subTest(card=cid):
    g=self.game((cid,));eid=self.play(g,cid);e=g.state.entities[eid]
    self.assertEqual((e.attack,e.health,set(e.keywords)),(a,h,set(k)));self.assertEqual(g.state.players[1].mana,45)
    self.assertEqual(g.state.players[1].board,[eid]);self.assertEqual(sum(e.kind=='card_played'for e in g.events),1)
    self.assertEqual(len(g.state.battlecry_history),0);self.assertEqual(sum(e.kind=='minion_summoned'for e in g.events),1)

 def test_a1_insufficient_mana_and_full_board_are_atomic_and_unseen_hand_is_private(self):
  g=self.game((ASSASSIN,),mana=4);own=g.observe(1)['players'][0]['hand'][0];hidden=g.observe(2)['players'][0]['hand'][0]
  self.assertEqual(own['card_id'],ASSASSIN);self.assertIsNone(hidden['card_id']);self.denied(g,PlayCard(1,self.first(g,ASSASSIN).id,position=0))
  g=self.game((CREEPER,),board=(ZERO,)*7);self.denied(g,PlayCard(1,self.first(g,CREEPER).id,position=7))

 def test_b0_windfury_does_not_grant_charge_and_only_two_attacks_are_allowed(self):
  g=self.game((MASTER,));source=self.play(g,MASTER);target=g.state.players[2].hero_id;self.denied(g,Attack(1,source,target));self.next_own(g)
  g.apply(Attack(1,source,target));g.apply(Attack(1,source,target));self.denied(g,Attack(1,source,target));self.assertEqual(self.health(g,2),24)

 def test_b1_plain_and_paired_taunts_gate_real_attacks_with_their_own_damage_rules(self):
  for cid in(CREEPER,RECYCLER,TROGG,ANNOY):
   g=self.game((cid,HURT),enemy=(BIG,));self.play(g,HURT);source=self.play(g,cid);g.apply(EndTurn(1));enemy=self.first(g,BIG,'board',2).id
   self.denied(g,Attack(2,enemy,g.state.players[1].hero_id));g.apply(Attack(2,enemy,source))
   self.assertEqual(g.state.entities[source].health,EXPECTED[cid][1]-(0 if cid==ANNOY else 2))
   if cid==RECYCLER:self.assertEqual(self.health(g),26)
   if cid==TROGG:self.assertEqual(g.state.entities[enemy].zone,Zone.GRAVEYARD)
   if cid==ANNOY:self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)

 def test_b2_plain_divine_shield_consumes_once_and_silence_removes_unspent_shield(self):
  g=self.game((FENCER,HIT,HIT));source=self.play(g,FENCER);self.play(g,HIT,source);self.assertEqual(g.state.entities[source].health,4)
  self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords);self.play(g,HIT,source);self.assertEqual(g.state.entities[source].health,3)
  g=self.game((FENCER,SILENCE,HIT));source=self.play(g,FENCER);self.play(g,SILENCE,source);self.play(g,HIT,source);self.assertEqual(g.state.entities[source].health,3)

 def test_b3_elusive_blocks_both_players_spells_and_hero_powers_but_not_battlecry_or_combat(self):
  g=self.game((KNIGHT,HIT,PING),enemy=(BIG,),enemy_hand=(HIT,));source=self.play(g,KNIGHT)
  self.denied(g,PlayCard(1,self.first(g,HIT).id,target_id=source));self.denied(g,UseHeroPower(1,g.state.players[1].hero_power_id,source))
  self.play(g,PING,source);self.assertEqual(g.state.entities[source].health,5);g.apply(EndTurn(1))
  self.denied(g,PlayCard(2,self.first(g,HIT,pid=2).id,target_id=source));self.denied(g,UseHeroPower(2,g.state.players[2].hero_power_id,source))
  g.apply(Attack(2,self.first(g,BIG,'board',2).id,source));self.assertEqual(g.state.entities[source].health,3)

 def test_b4_plain_poison_and_real_rush_poison_kill_large_minions_only_after_positive_damage(self):
  g=self.game((PLAGUE,),enemy=(BIG,));source=self.play(g,PLAGUE);self.next_own(g);target=self.first(g,BIG,'board',2).id
  g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[source].health,3)
  g=self.game((SPIDER,),enemy=(BIG,SHIELDED));source=self.play(g,SPIDER);self.denied(g,Attack(1,source,g.state.players[2].hero_id));target=self.first(g,SHIELDED,'board',2).id
  g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].zone,Zone.BOARD);self.assertEqual(g.state.entities[target].health,30)
  g=self.game((SPIDER,),enemy=(BIG,));source=self.play(g,SPIDER);target=self.first(g,BIG,'board',2).id;g.apply(Attack(1,source,target))
  self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[source].health,1)

 def test_b5_bloodworm_lifesteal_uses_actual_damage_and_shield_prevents_healing(self):
  for cid,expected in((ZERO,28),(SHIELDED,24)):
   g=self.game((WORM,HURT),enemy=(cid,));self.play(g,HURT);source=self.play(g,WORM);self.next_own(g)
   g.apply(Attack(1,source,self.first(g,cid,'board',2).id));self.assertEqual(self.health(g),expected)

 def test_b6_rush_shield_horse_attacks_minion_immediately_and_blocks_real_retaliation(self):
  g=self.game((HORSE,),enemy=(HARD,));source=self.play(g,HORSE);self.denied(g,Attack(1,source,g.state.players[2].hero_id));target=self.first(g,HARD,'board',2).id
  g.apply(Attack(1,source,target));self.assertEqual((g.state.entities[source].health,g.state.entities[target].health),(4,27));self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
  self.denied(g,Attack(1,source,target))

 def test_c0_assassin_stealth_breaks_on_attack_and_reborn_has_new_identity_one_health_and_stealth(self):
  g=self.game((ASSASSIN,),enemy=(BIG,),enemy_hand=(HIT,));source=self.play(g,ASSASSIN);g.apply(EndTurn(1))
  self.denied(g,Attack(2,self.first(g,BIG,'board',2).id,source));self.denied(g,PlayCard(2,self.first(g,HIT,pid=2).id,target_id=source));g.apply(EndTurn(2))
  g.apply(Attack(1,source,self.first(g,BIG,'board',2).id));returned=self.first(g,ASSASSIN,'board').id
  self.assertNotEqual(source,returned);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertNotIn(Keyword.STEALTH,g.state.entities[source].keywords)
  self.assertEqual((g.state.entities[returned].attack,g.state.entities[returned].health),(4,1));self.assertIn(Keyword.STEALTH,g.state.entities[returned].keywords);self.assertNotIn(Keyword.REBORN,g.state.entities[returned].keywords);self.portable(g)

 def test_c1_native_silence_bounce_and_current_copy_preserve_consumption_and_reset_boundaries(self):
  g=self.game((HORSE,HIT,COPY,BOUNCE,SILENCE));source=self.play(g,HORSE);self.play(g,HIT,source);self.play(g,COPY,source)
  copies=[i for i in g.state.players[1].board if g.state.entities[i].card_id==HORSE];self.assertEqual(len(copies),2)
  self.assertTrue(all(Keyword.DIVINE_SHIELD not in g.state.entities[i].keywords for i in copies))
  self.play(g,BOUNCE,source);self.assertEqual(self.first(g,HORSE).id,source);self.play(g,HORSE);self.assertIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords)
  self.play(g,SILENCE,source);self.assertNotIn(Keyword.DIVINE_SHIELD,g.state.entities[source].keywords);self.assertNotIn(Keyword.RUSH,g.state.entities[source].keywords);self.portable(g)

 def test_c2_reborn_resets_buff_and_consumes_once_while_silence_removes_both_printed_keywords(self):
  g=self.game((ASSASSIN,GROW,KILL,KILL));source=self.play(g,ASSASSIN);self.play(g,GROW,source);self.play(g,KILL,source);returned=self.first(g,ASSASSIN,'board').id
  self.assertEqual((g.state.entities[returned].attack,g.state.entities[returned].max_health,g.state.entities[returned].health),(4,2,1));self.play(g,KILL,returned);self.assertEqual(g.state.players[1].board,[])
  g=self.game((ASSASSIN,SILENCE,KILL));source=self.play(g,ASSASSIN);self.play(g,SILENCE,source);self.assertFalse(set(g.state.entities[source].keywords)&{Keyword.REBORN,Keyword.STEALTH})
  self.play(g,KILL,source);self.assertEqual(g.state.players[1].board,[])

 def test_c3_distinct_combat_and_reborn_waits_restore_replay_and_roll_back_failed_continuations(self):
  for mode,cid in(('combat',HORSE),('death',ASSASSIN)):
   g=self.game((cid,KILL),enemy=(HARD,),mode=mode);source=self.play(g,cid)
   if mode=='combat':g.apply(Attack(1,source,self.first(g,HARD,'board',2).id))
   else:self.play(g,KILL,source)
   self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot();q=g.state.pending_choice
   with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('fail',)))
   self.assertEqual(g.snapshot(),snap);g.apply(SelectChoice(1,q.id,('ok',)));self.assertIsNone(g.state.pending_choice)
   if mode=='combat':self.assertEqual(g.state.entities[source].health,4)
   else:self.assertEqual(self.first(g,ASSASSIN,'board').health,1)
   self.portable(g)

 def test_z0_complete_sources_preserve_old_assembly_and_do_not_claim_past_pool_or_standard_roots(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(0,12,26));self.assertEqual(d['collectible_candidate_roots'],[])
  rows={x['record']['id']:x['record']for k in('dependencies','evidence_only')for x in d[k]}
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards));self.assertTrue(set(ROOTS)<=set(after.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)

if __name__=='__main__':unittest.main()
