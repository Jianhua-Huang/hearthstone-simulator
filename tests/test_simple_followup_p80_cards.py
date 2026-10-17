"""Real native health and trigger entries, including retired accepted sources."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p80_cards as cards
from hs_sim.cards.simple_followup_p80_cards import (HEALBOT,APPLEBAUM,LOBBER,SCORCHER,SQUAD,HYDRA,DREADLORD,WATCHER,CRUSHER,GUARD,INSPECTOR,JUNKBOT,ROOTS,PREFIX,load_batch,register_simple_followup_p80_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SecretSpec,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GainArmor,GrantKeyword,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,EndTurnRepeatSpec,EndTurnSpec,HealingKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference

TEST='p80.test.'
HERO,HP,FILLER,MECH,ALL,UNKNOWN,SHIELDED,POWER,DOUBLE=(TEST+i for i in('hero','power','filler','mech','all','unknown','shielded','spellpower','double'))
NOP,PING,ZERO,BLAST,KILL,SILENCE,TAKE,SHIELD,IMMUNE,ARMOR,HEAL,TO_MECH,TO_BEAST,TWIN=(TEST+i for i in('nop','ping','zero','blast','kill','silence','take','shield','immune','armor','heal','to-mech','to-beast','twin'))
SA,SB,SC=(TEST+i for i in('secret-a','secret-b','secret-c'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p80_cards(r)
 elif not all(present):raise AssertionError('P80 complete assigned assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p80-small-native-fixtures');register_simple_followup_p80_cards(r);hero_extra={}
 r.register_behavior(NOP,lambda c:())
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=NOP,metadata=meta()))
 for cid,tribes,k in((FILLER,(),()),(MECH,('mech',),()),(ALL,('all',),()),(UNKNOWN,None,()),(SHIELDED,(),(Keyword.DIVINE_SHIELD,))):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=12,keywords=k,metadata=meta(tribes)))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=30,spell_damage=7,metadata=meta()))
 r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,end_turn_repeats=(EndTurnRepeatSpec(2,'all'),),metadata=meta()))
 bodies={NOP:lambda c:(),PING:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.EFFECT),),BLAST:lambda c:(Damage(c.target_id,12,c.source_id,DamageKind.EFFECT),),
  KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),
  SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),IMMUNE:lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),),
  ARMOR:lambda c:(GainArmor(c.player_id,8),),HEAL:lambda c:(Heal(c.target_id,1,c.source_id,HealingKind.EFFECT),),
  TWIN:lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),Damage(c.target_id,1,c.source_id,DamageKind.EFFECT))),)}
 for cid,tribe in((TO_MECH,'mech'),(TO_BEAST,'beast')):
  bodies[cid]=lambda c,tribe=tribe:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',(tribe,)),c.source_id),)
 for cid,body in bodies.items():
  if cid!=NOP:r.register_behavior(cid,body)
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=None if cid in(NOP,ARMOR)else TargetSpec(),metadata=meta()))
 r.register_secret_condition(TEST+'never',lambda c:False)
 for cid in(SA,SB,SC):r.register_card(CardDefinition(cid,cid,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(cid,('card_committed',),TEST+'never',NOP),metadata=meta()))
 if mode is not None:
  event={'random':'choice_skipped','death':'minion_died','health':'health_resolved','attack':'attack_finished','end':'turn_ended'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='random':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==LOBBER
   if mode=='death':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in(HEALBOT,APPLEBAUM,SQUAD)
   if mode=='health':return c.health_result is not None and c.health_result.target_card_id==HYDRA and c.health_result.flow=='damage'and c.health_result.damage_dealt>0
   if mode=='attack':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==CRUSHER
   return c.event.player_id==1
  def reenter(c):
   e=c.state.entities[c.target_id]
   return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
  def fail(c):raise ResolutionError('P80 deliberate continuation failure')
  r.register_behavior(TEST+'reenter',reenter);r.register_behavior(TEST+'fail',fail)
  def wait(c):
   change=()
   if mode in('random','attack'):
    pid=2 if mode=='random'else 1;card=FILLER if mode=='random'else CRUSHER;target=next(c.state.entities[i]for i in c.state.players[pid].board if c.state.entities[i].card_id==card)
    change=(ReturnToHand(target.id),InvokeBehavior(TEST+'reenter',c.source_id,1,target.id))
   elif mode=='health':change=(Destroy(c.health_result.target_id,c.source_id),)
   elif mode=='end':
    target=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==DREADLORD)
    change=(Destroy(target,c.source_id),Summon(2,FILLER))
   return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original source or target',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
  r.register_behavior(TEST+'wait',wait);r.register_trigger_condition(TEST+'eligible',eligible)
  hero_extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible',end_turn=EndTurnSpec()if mode=='end'else None),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**hero_extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP80Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),
   PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8080),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def stats(self,g,eid):return(g.state.entities[eid].attack,g.state.entities[eid].health)
 def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(g.snapshot(),snap)
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',visible)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),snap)

 def test_a0_all_twelve_actual_paid_entries_have_complete_printed_stats_and_one_payment(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id if cid==SQUAD else None;source=self.play(g,cid,target);raw=rows[cid]
   self.assertEqual(self.stats(g,source),(raw['attack'],raw['health']));self.assertEqual(g.state.players[1].mana,55);self.assertEqual(sum(e.kind=='card_played'for e in g.events),1)
   if cid==APPLEBAUM:self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)

 def test_b0_actual_graveyard_deathrattles_heal_exact_enemy_eight_or_own_six(self):
  for cid,pid,expected in((HEALBOT,2,26),(APPLEBAUM,1,24)):
   g=self.game((BLAST,cid,KILL));self.play(g,BLAST,g.state.players[pid].hero_id);source=self.play(g,cid);self.play(g,KILL,source)
   self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g,pid),expected)
  g=self.game((HEALBOT,SILENCE,KILL));source=self.play(g,HEALBOT);self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertFalse(any(e.kind=='healed'for e in g.events))

 def test_b1_death_controller_not_original_owner_drives_heal_and_real_death_wait_recovers(self):
  g=self.game((BLAST,HEALBOT,TAKE),enemy_hand=(KILL,));self.play(g,BLAST,g.state.players[1].hero_id);source=self.play(g,HEALBOT);self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,KILL,source,pid=2)
  self.assertEqual(self.hp(g),26);self.assertEqual((g.state.death_history[-1].owner,g.state.death_history[-1].controller),(1,2));self.portable(g)
  g=self.game((BLAST,APPLEBAUM,KILL),mode='death');self.play(g,BLAST,g.state.players[1].hero_id);source=self.play(g,APPLEBAUM);self.play(g,KILL,source);self.fail_wait(g);self.choose(g);self.assertEqual(self.hp(g),24);self.portable(g)

 def test_c0_lobber_hits_one_actual_enemy_minion_four_without_spellpower_and_empty_has_no_rng(self):
  g=self.game((LOBBER,),board=(POWER,),enemy=(FILLER,MECH));source=self.play(g,LOBBER);hits=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
  self.assertEqual(len(hits),1);self.assertEqual((hits[0].damage_dealt,hits[0].damage_kind),(4,DamageKind.MINION_ABILITY.value));self.assertIn(hits[0].target_id,g.state.players[2].board);self.assertEqual(self.hp(g,2),30)
  g=self.game((LOBBER,));rng=g.snapshot()['rng_state'];self.play(g,LOBBER);self.assertEqual(g.snapshot()['rng_state'],rng)

 def test_c1_sampled_lobber_target_does_not_rebind_after_real_wait_and_same_id_reentry(self):
  g=self.game((LOBBER,),enemy=(FILLER,),mode='random');target=self.first(g,FILLER,'board',2).id;self.play(g,LOBBER);self.fail_wait(g);rng=g.snapshot()['rng_state'];self.choose(g,'change')
  self.assertEqual(self.stats(g,target),(1,12));self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

 def test_c2_scorcher_submits_one_actual_batch_to_both_sides_excluding_itself_and_heroes(self):
  g=self.game((SCORCHER,),board=(MECH,POWER),enemy=(FILLER,SHIELDED));source=self.play(g,SCORCHER);hits=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source]
  self.assertEqual(len(hits),4);self.assertEqual(len({h.batch_id for h in hits}),1);self.assertNotIn(source,{h.target_id for h in hits});self.assertEqual((self.hp(g),self.hp(g,2)),(30,30))
  self.assertEqual(self.first(g,FILLER,'board',2).health,11);self.assertEqual(self.first(g,SHIELDED,'board',2).health,12);self.assertEqual(g.state.entities[source].health,6)

 def test_c3_bomb_squad_has_enemy_only_optional_target_and_independent_grave_damage_five(self):
  g=self.game((SQUAD,KILL),board=(POWER,),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;source=self.play(g,SQUAD,target);self.assertEqual(g.state.entities[target].health,7)
  self.play(g,KILL,source);self.assertEqual(self.hp(g),25);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
  g=self.game((SQUAD,),board=(FILLER,));self.denied(g,PlayCard(1,self.first(g,SQUAD).id,target_id=self.first(g,FILLER,'board').id,position=1));self.play(g,SQUAD)

 def test_d0_hydra_counts_actual_positive_packets_not_shield_zero_heal_or_unrelated_targets(self):
  g=self.game((HYDRA,ZERO,SHIELD,PING,PING,HEAL,TWIN),board=(FILLER,));source=self.play(g,HYDRA);self.play(g,ZERO,source);self.play(g,SHIELD,source);self.play(g,PING,source);self.assertEqual(self.hp(g),30)
  self.play(g,PING,self.first(g,FILLER,'board').id);self.play(g,HEAL,source);self.assertEqual(self.hp(g),30);self.play(g,TWIN,source);self.assertEqual(self.hp(g),24)

 def test_d1_lethal_hydra_damage_and_later_source_death_keep_the_accepted_hero_penalty(self):
  g=self.game((HYDRA,BLAST));source=self.play(g,HYDRA);self.play(g,BLAST,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g),27)
  g=self.game((HYDRA,PING),mode='health');source=self.play(g,HYDRA);self.play(g,PING,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.hp(g),27);self.portable(g)

 def test_d2_blood_guard_buffs_all_original_living_friends_and_external_reward_survives_lethal_hit(self):
  g=self.game((GUARD,PING),board=(MECH,),enemy=(FILLER,));source=self.play(g,GUARD);self.play(g,PING,source);self.assertEqual(g.state.entities[source].attack,5);self.assertEqual(self.first(g,MECH,'board').attack,2);self.assertEqual(self.first(g,FILLER,'board',2).attack,1)
  g=self.game((GUARD,BLAST),board=(MECH,));source=self.play(g,GUARD);self.play(g,BLAST,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.first(g,MECH,'board').attack,2)

 def test_e0_dreadlord_uses_only_owner_ends_and_native_extra_body_count(self):
  g=self.game((DREADLORD,),board=(POWER,DOUBLE),enemy=(FILLER,MECH));self.play(g,DREADLORD);g.apply(EndTurn(1));self.assertEqual(self.first(g,FILLER,'board',2).health,10);self.assertEqual(self.hp(g,2),30)
  g.apply(EndTurn(2));self.assertEqual(self.first(g,FILLER,'board',2).health,10);self.portable(g)

 def test_e1_accepted_end_survives_source_death_and_refreshes_current_enemy_batch_after_prior_body(self):
  g=self.game((DREADLORD,),enemy=(FILLER,),mode='end');source=self.play(g,DREADLORD);g.apply(EndTurn(1));self.fail_wait(g);self.choose(g,'change')
  self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[2].board),2);self.assertTrue(all(g.state.entities[i].health==11 for i in g.state.players[2].board));self.portable(g)

 def test_f0_watcher_uses_actual_owner_turn_hero_damage_including_armor_and_not_heal_or_prevention(self):
  g=self.game((WATCHER,ARMOR,PING,ZERO,HEAL),enemy_hand=(PING,));source=self.play(g,WATCHER);hero=g.state.players[1].hero_id;self.play(g,ARMOR);self.play(g,PING,hero)
  self.assertEqual((self.stats(g,source),self.hp(g)),((6,6),30));self.play(g,ZERO,hero);self.play(g,HEAL,hero);self.assertEqual(self.stats(g,source),(6,6))
  g.apply(EndTurn(1));self.play(g,PING,hero,pid=2);self.assertEqual(self.stats(g,source),(6,6))
  g=self.game((WATCHER,IMMUNE,PING));source=self.play(g,WATCHER);hero=g.state.players[1].hero_id;self.play(g,IMMUNE,hero);self.play(g,PING,hero);self.assertEqual(self.stats(g,source),(4,4))

 def test_f1_damage_trigger_control_changes_follow_actual_captured_controller_and_silence_removes_future_text(self):
  g=self.game((HYDRA,TAKE),enemy_hand=(PING,));source=self.play(g,HYDRA);self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,PING,source,pid=2);self.assertEqual((self.hp(g),self.hp(g,2)),(30,27))
  g=self.game((HYDRA,SILENCE,PING));source=self.play(g,HYDRA);self.play(g,SILENCE,source);self.play(g,PING,source);self.assertEqual(self.hp(g),30)

 def test_g0_crusher_freezes_after_its_real_attack_but_not_after_defending_or_ordinary_damage(self):
  g=self.game((CRUSHER,),enemy=(FILLER,));source=self.play(g,CRUSHER);self.next_own(g);target=self.first(g,FILLER,'board',2).id;g.apply(Attack(1,source,target));self.assertTrue(g.state.entities[source].frozen);self.denied(g,Attack(1,source,g.state.players[2].hero_id))
  g=self.game((CRUSHER,PING),enemy=(FILLER,));source=self.play(g,CRUSHER);self.play(g,PING,source);self.assertFalse(g.state.entities[source].frozen);g.apply(EndTurn(1));g.apply(Attack(2,self.first(g,FILLER,'board',2).id,source));self.assertFalse(g.state.entities[source].frozen)

 def test_g1_original_attack_freeze_does_not_rebind_to_same_id_returned_body_across_wait(self):
  g=self.game((CRUSHER,),enemy=(FILLER,),mode='attack');source=self.play(g,CRUSHER);self.next_own(g);g.apply(Attack(1,source,self.first(g,FILLER,'board',2).id));self.fail_wait(g);self.choose(g,'change')
  self.assertIn(source,g.state.players[1].board);self.assertFalse(g.state.entities[source].frozen);self.assertEqual(self.stats(g,source),(8,8));self.portable(g)

 def test_h0_junkbot_reads_friendly_frozen_current_mech_all_and_changed_tribes(self):
  for cid in(MECH,ALL):
   g=self.game((JUNKBOT,KILL),board=(cid,));source=self.play(g,JUNKBOT);self.play(g,KILL,self.first(g,cid,'board').id);self.assertEqual(self.stats(g,source),(3,7))
  g=self.game((JUNKBOT,TO_MECH,KILL),board=(FILLER,));source=self.play(g,JUNKBOT);target=self.first(g,FILLER,'board').id;self.play(g,TO_MECH,target);self.play(g,KILL,target);self.assertEqual(self.stats(g,source),(3,7))
  g=self.game((JUNKBOT,TO_BEAST,KILL),board=(MECH,));source=self.play(g,JUNKBOT);target=self.first(g,MECH,'board').id;self.play(g,TO_BEAST,target);self.play(g,KILL,target);self.assertEqual(self.stats(g,source),(1,5))

 def test_h1_junkbot_uses_death_controller_and_rejects_unknown_relevant_tribe_transactionally(self):
  g=self.game((JUNKBOT,TAKE),board=(MECH,),enemy_hand=(KILL,));source=self.play(g,JUNKBOT);target=self.first(g,MECH,'board').id;self.play(g,TAKE,target);g.apply(EndTurn(1));self.play(g,KILL,target,pid=2);self.assertEqual(self.stats(g,source),(1,5))
  g=self.game((JUNKBOT,KILL),board=(UNKNOWN,));self.play(g,JUNKBOT);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,KILL,self.first(g,UNKNOWN,'board').id)
  self.assertEqual(g.snapshot(),snap)

 def test_i0_inspector_uses_native_enemy_secret_retirement_and_preserves_own_secret_without_minion_death(self):
  g=self.game((SC,INSPECTOR),enemy_hand=(SA,SB));self.play(g,SC);g.apply(EndTurn(1));self.play(g,SA,pid=2);self.play(g,SB,pid=2);g.apply(EndTurn(2))
  hidden=g.observe(1)['players'][1]['secrets'];self.assertTrue(all(e['card_id']is None for e in hidden));self.play(g,INSPECTOR)
  self.assertEqual(g.state.players[2].secrets,[]);self.assertEqual(len(g.state.players[1].secrets),1);self.assertEqual(len(g.state.death_history),0);self.assertEqual(sum(e.kind=='secret_removed'for e in g.events),2);self.portable(g)

 def test_z0_complete_sources_and_all_old_programs_are_preserved_before_and_after_assembly(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['official_observations'])),(0,12,26));rows={x['record']['id']:x['record']for k in('dependencies','evidence_only')for x in d[k]}
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  with patch(__name__+'.build_registry',lambda:after):self.assertIs(batch_registry(),after)
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)

if __name__=='__main__':unittest.main()
