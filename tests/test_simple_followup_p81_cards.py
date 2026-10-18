"""Native original entries and distinct survival, copy, Inspire and cost boundaries."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p81_cards as cards
from hs_sim.cards.simple_followup_p81_cards import (FIEND,RECRUITER,EMPEROR,WARLORD,VENTURE,SCRAP,HOG,DOPPEL,PATRON,STONEMAUL,FORTUNE,LURKER,SQUIRE,ROOTS,PREFIX,load_batch,register_simple_followup_p81_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,DamageBatch,Destroy,GrantKeyword,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import BoardPresenceReference,DamageKind,EndTurnRepeatSpec,EndTurnSpec,HealingKind,LimitedTriggerSpec,Runes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference

TEST='p81.test.'
HERO,HP,FILLER,TAUNT,DORMANT,LOCATION,DOUBLE,POWER=(TEST+i for i in('hero','power','filler','taunt','dormant','location','double','spellpower'))
NOP,PING,ZERO,BLAST,KILL,SILENCE,TAKE,SHIELD,IMMUNE,HEAL,TWIN,HAND_BUFF,LOCAL_BUFF,COPY,BOUNCE=(TEST+i for i in('nop','ping','zero','blast','kill','silence','take','shield','immune','heal','twin','hand-buff','local-buff','copy','bounce'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()

def meta():return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=())
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p81_cards(r)
 elif not all(present):raise AssertionError('P81 requires complete assigned assembly')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p81-small-native-fixtures')
 raw=load_batch()['existing_dependencies'][0]['record']
 r.register_card(CardDefinition(SQUIRE,raw['name'],CardType.MINION,cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)))
 register_simple_followup_p81_cards(r)
 r.register_behavior(NOP,lambda c:())
 for cid,k,extra in((FILLER,(),{}),(TAUNT,(Keyword.TAUNT,),{}),(DORMANT,(),{'dormant_turns':2}),(DOUBLE,(),{'end_turn_repeats':(EndTurnRepeatSpec(2,'all'),)}),(POWER,(),{'spell_damage':7})):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=1,health=12,keywords=k,metadata=meta(),**extra))
 r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=3,durability=2,on_use=NOP,metadata=meta()))
 def fail(c):raise ResolutionError('P81 deliberate continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def reenter(c):
  e=c.state.entities[c.target_id]
  return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
 r.register_behavior(TEST+'reenter',reenter)
 def wait(c):
  change=()
  if mode=='health':
   source=c.health_result.target_id
   change=(ReturnToHand(source),InvokeBehavior(TEST+'reenter',c.source_id,c.player_id,source))
  elif mode=='end':
   source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==EMPEROR)
   change=(Destroy(source,c.source_id),AddToHand(1,FILLER,c.source_id))
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original source',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 hp_body=TEST+'wait'if mode=='power'else NOP
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=hp_body,metadata=meta()))
 bodies={PING:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.EFFECT),),BLAST:lambda c:(Damage(c.target_id,12,c.source_id,DamageKind.EFFECT),),
  KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),
  SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),IMMUNE:lambda c:(GrantKeyword(c.target_id,Keyword.IMMUNE,c.source_id),),HEAL:lambda c:(Heal(c.target_id,1,c.source_id,HealingKind.EFFECT),),
  TWIN:lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),Damage(c.target_id,1,c.source_id,DamageKind.EFFECT))),),
  HAND_BUFF:lambda c:(BuffMinionsInZones(c.player_id,2,3,MinionScope((Zone.HAND,)),c.source_id),),LOCAL_BUFF:lambda c:(Buff(c.target_id,2,3,c.source_id),),
  COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),BOUNCE:lambda c:(ReturnToHand(c.target_id),)}
 for cid,body in bodies.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=0,on_play=cid,targeting=None if cid==HAND_BUFF else TargetSpec(),metadata=meta()))
 r.register_card(CardDefinition(NOP,NOP,CardType.SPELL,cost=2,on_play=NOP,metadata=meta()))
 extra={}
 if mode in('health','end'):
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='end':return c.event.player_id==1
   h=c.health_result
   return h is not None and h.target_card_id==PATRON and h.flow=='damage'and h.damage_dealt>0
  r.register_trigger_condition(TEST+'eligible',eligible)
  extra['limited_triggers']=(LimitedTriggerSpec('health_resolved'if mode=='health'else'turn_ended',TEST+'wait',condition_id=TEST+'eligible',end_turn=EndTurnSpec()if mode=='end'else None),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP81Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8181),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind in(CardType.MINION,CardType.LOCATION)else None));return e.id
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def stats(self,g,eid):return(g.state.entities[eid].attack,g.state.entities[eid].health)
 def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
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
 def count(self,g,cid,pid=1):return sum(g.state.entities[i].card_id==cid for i in g.state.players[pid].board)

 def test_a0_all_twelve_actual_paid_entries_and_native_keywords(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,));source=self.play(g,cid);raw=rows[cid];expected=(5,8)if cid==SCRAP else(3,6)if cid==LURKER else(raw['attack'],raw['health'])
   self.assertEqual(self.stats(g,source),expected);self.assertEqual(g.state.players[1].mana,55);self.assertEqual(sum(e.kind=='card_played'for e in g.events),1)
   if cid in(SCRAP,FORTUNE,LURKER):self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)
   if cid in(SCRAP,STONEMAUL):self.assertIn(Keyword.RUSH,g.state.entities[source].keywords)

 def test_b0_warlord_counts_physical_other_minions_including_dormant_not_location(self):
  g=self.game((WARLORD,),board=(FILLER,DORMANT,LOCATION),enemy=(FILLER,));source=self.play(g,WARLORD);self.assertEqual(self.stats(g,source),(6,6))
  self.assertEqual(self.first(g,FILLER,'board').attack,1);self.assertEqual(self.first(g,FILLER,'board',2).attack,1)

 def test_b1_fortune_counts_only_current_spells_remaining_in_hand(self):
  g=self.game((FORTUNE,NOP,NOP,FILLER,LOCATION));source=self.play(g,FORTUNE);self.assertEqual(self.stats(g,source),(5,5));self.assertEqual(len(g.state.players[1].hand),4)
  g=self.game((FORTUNE,));source=self.play(g,FORTUNE);self.assertEqual(self.stats(g,source),(3,3))

 def test_b2_scrap_actual_rush_and_timed_attack_expire_on_original_turn(self):
  g=self.game((SCRAP,),enemy=(FILLER,));source=self.play(g,SCRAP);target=self.first(g,FILLER,'board',2).id;g.apply(Attack(1,source,target));self.assertEqual(g.state.entities[target].health,7)
  g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].attack,1);self.portable(g)

 def test_b3_hogrider_current_enemy_taunt_condition_and_charge_permission(self):
  g=self.game((HOG,),enemy=(TAUNT,));source=self.play(g,HOG);self.assertIn(Keyword.CHARGE,g.state.entities[source].keywords);g.apply(Attack(1,source,self.first(g,TAUNT,'board',2).id))
  g=self.game((HOG,),board=(TAUNT,),enemy=(FILLER,));source=self.play(g,HOG);self.assertNotIn(Keyword.CHARGE,g.state.entities[source].keywords)
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,source,g.state.players[2].hero_id))
  self.assertEqual(g.snapshot(),snap)

 def test_b4_lurker_doubles_current_hand_buffed_health_and_silence_restores_printed(self):
  g=self.game((HAND_BUFF,LURKER,SILENCE));self.play(g,HAND_BUFF);source=self.play(g,LURKER);self.assertEqual(self.stats(g,source),(5,12));self.play(g,SILENCE,source);self.assertEqual(self.stats(g,source),(3,3))

 def test_c0_doppel_summons_two_current_buffed_copies_without_replaying_battlecry(self):
  g=self.game((HAND_BUFF,DOPPEL));self.play(g,HAND_BUFF);source=self.play(g,DOPPEL);ids=g.state.players[1].board
  self.assertEqual(len(ids),3);self.assertEqual(self.count(g,DOPPEL),3);self.assertTrue(all(self.stats(g,i)==(4,5)for i in ids));self.assertEqual(sum(e.kind=='card_played'for e in g.events),2);self.portable(g)

 def test_c1_doppel_respects_real_remaining_board_capacity(self):
  for n,expected in((5,2),(6,1)):
   g=self.game((DOPPEL,),board=(FILLER,)*n);self.play(g,DOPPEL);self.assertEqual(len(g.state.players[1].board),7);self.assertEqual(self.count(g,DOPPEL),expected)

 def test_c2_patron_damage_survival_creates_fresh_printed_body_not_current_copy(self):
  g=self.game((PATRON,LOCAL_BUFF,PING));source=self.play(g,PATRON);self.play(g,LOCAL_BUFF,source);self.play(g,PING,source)
  ids=[i for i in g.state.players[1].board if i!=source];self.assertEqual(self.stats(g,source),(5,5));self.assertEqual(len(ids),1);self.assertEqual(self.stats(g,ids[0]),(3,3));self.portable(g)

 def test_c3_patron_rejects_zero_prevented_heal_unrelated_and_lethal_damage(self):
  g=self.game((PATRON,ZERO,SHIELD,PING,HEAL,PING),board=(FILLER,));source=self.play(g,PATRON);self.play(g,ZERO,source);self.play(g,SHIELD,source);self.play(g,PING,source);self.play(g,HEAL,source);self.play(g,PING,self.first(g,FILLER,'board').id);self.assertEqual(self.count(g,PATRON),1)
  g=self.game((PATRON,BLAST));source=self.play(g,PATRON);self.play(g,BLAST,source);self.assertEqual(self.count(g,PATRON),0)

 def test_c4_patron_two_actual_surviving_packets_and_full_board_capacity(self):
  g=self.game((PATRON,TWIN));source=self.play(g,PATRON);self.play(g,TWIN,source);self.assertEqual(self.count(g,PATRON),3)
  g=self.game((PATRON,PING),board=(FILLER,)*6);source=self.play(g,PATRON);self.play(g,PING,source);self.assertEqual(self.count(g,PATRON),1);self.assertEqual(len(g.state.players[1].board),7)

 def test_c5_accepted_original_survival_keeps_base_reward_after_same_id_source_reentry(self):
  g=self.game((PATRON,PING),mode='health');source=self.play(g,PATRON);self.play(g,PING,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.count(g,PATRON),2);self.assertEqual(self.stats(g,source),(3,3));self.assertTrue(all(self.stats(g,i)==(3,3)for i in g.state.players[1].board));self.portable(g)

 def test_d0_frenzy_draws_once_after_actual_survival_even_two_packets(self):
  g=self.game((STONEMAUL,TWIN,PING));source=self.play(g,STONEMAUL);deck=len(g.state.players[1].deck);self.play(g,TWIN,source);self.assertEqual(len(g.state.players[1].deck),deck-1);self.play(g,PING,source);self.assertEqual(len(g.state.players[1].deck),deck-1)
  self.assertEqual(sum(e.kind=='limited_trigger_used'for e in g.events),1);self.portable(g)

 def test_d1_frenzy_zero_prevention_lethal_silence_and_return_reset(self):
  g=self.game((STONEMAUL,ZERO,SHIELD,PING,PING,BOUNCE,PING));source=self.play(g,STONEMAUL);self.play(g,ZERO,source);self.play(g,SHIELD,source);self.play(g,PING,source);self.assertEqual(len(g.state.players[1].deck),12);self.play(g,PING,source);self.assertEqual(len(g.state.players[1].deck),11)
  self.play(g,BOUNCE,source);self.play(g,STONEMAUL);self.play(g,PING,source);self.assertEqual(len(g.state.players[1].deck),10)
  for op in(BLAST,SILENCE):
   g=self.game((STONEMAUL,op,PING));source=self.play(g,STONEMAUL);self.play(g,op,source)
   if op==SILENCE:self.play(g,PING,source)
   self.assertEqual(len(g.state.players[1].deck),12)

 def test_e0_shadowfiend_real_battlecry_and_own_manual_inspire_each_one_both_hero_batch(self):
  g=self.game((FIEND,),board=(POWER,));source=self.play(g,FIEND);self.assertEqual((self.hp(g),self.hp(g,2)),(26,26));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual((self.hp(g),self.hp(g,2)),(22,22))
  hits=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source];self.assertEqual(len(hits),4);self.assertEqual(len({h.batch_id for h in hits}),2);self.assertTrue(all(h.damage_dealt==4 and h.damage_kind=='minion_ability'for h in hits))
  g.apply(EndTurn(1));g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual((self.hp(g),self.hp(g,2)),(22,22));self.portable(g)

 def test_e1_recruiter_existing_exact_squire_and_real_hand_overflow(self):
  g=self.game((RECRUITER,));self.play(g,RECRUITER);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));squire=self.first(g,SQUIRE);self.assertEqual((squire.attack,squire.health,g.registry.card(SQUIRE).cost),(2,2,1));self.play(g,SQUIRE);self.assertEqual(g.state.players[1].mana,52)
  g=self.game((NOP,)*10,board=(RECRUITER,));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(len(g.state.players[1].hand),10);self.assertFalse(any(g.state.entities[i].card_id==SQUIRE for i in g.state.players[1].hand));self.assertTrue(any(e.card_id==SQUIRE and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()))

 def test_e2_manual_power_wait_delays_inspire_and_restores_independent_reader(self):
  g=self.game((FIEND,RECRUITER),mode='power');self.play(g,FIEND);self.play(g,RECRUITER);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.fail_wait(g);self.assertEqual(self.hp(g),26);self.assertEqual(len(g.state.players[1].hand),0);self.choose(g);self.assertEqual(self.hp(g),22);self.assertEqual(self.first(g,SQUIRE).card_id,SQUIRE);self.portable(g)

 def test_f0_venture_continuous_friendly_minion_cost_and_silence_control_lifecycle(self):
  g=self.game((VENTURE,FILLER,NOP,SILENCE,TAKE),enemy_hand=(FILLER,));source=self.play(g,VENTURE);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,48);self.play(g,NOP);self.assertEqual(g.state.players[1].mana,46);self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,FILLER,pid=2);self.assertEqual(g.state.players[2].mana,53)
  g=self.game((VENTURE,SILENCE,FILLER));source=self.play(g,VENTURE);self.play(g,SILENCE,source);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,51)

 def test_f1_emperor_only_owner_ends_local_discounts_persist_and_floor_zero(self):
  g=self.game((EMPEROR,FILLER,NOP,ZERO));source=self.play(g,EMPEROR);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,NOP);self.assertEqual(g.state.players[1].mana,59);self.play(g,ZERO,g.state.players[1].hero_id);self.assertEqual(g.state.players[1].mana,59);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,56);self.portable(g)
  g=self.game((EMPEROR,FILLER,KILL));source=self.play(g,EMPEROR);g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,KILL,source);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,57)

 def test_f2_accepted_emperor_uses_fresh_hand_after_earlier_source_death_and_real_wait(self):
  g=self.game((EMPEROR,FILLER),mode='end');source=self.play(g,EMPEROR);g.apply(EndTurn(1));self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);g.apply(EndTurn(2))
  self.play(g,FILLER);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,54);self.portable(g)

 def test_f3_emperor_native_repeated_body_stacks_independently(self):
  g=self.game((EMPEROR,FILLER),board=(DOUBLE,));self.play(g,EMPEROR);self.next_own(g);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,58)

 def test_z0_full_source_existing_dependency_and_all_old_programs_before_after_assembly(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(0,12,1,28));rows={x['record']['id']:x['record']for k in('dependencies','existing_dependencies','evidence_only')for x in d[k]}
  self.assertEqual(rows[RECRUITER]['tags']['COLLECTION_RELATED_CARD_DATABASE_ID'],rows[SQUIRE]['dbf_id']);self.assertEqual(rows[SQUIRE]['dbf_id'],482)
  self.assertEqual(d['exact_parent_child_links'],[]);self.assertEqual(d['source_tag_links'],[dict(parent=RECRUITER,child=SQUIRE,tag='COLLECTION_RELATED_CARD_DATABASE_ID',dbf_id=482)])
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  with patch(__name__+'.build_registry',lambda:after):self.assertIs(batch_registry(),after)
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)

if __name__=='__main__':unittest.main()
