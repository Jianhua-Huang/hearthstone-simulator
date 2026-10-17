"""Native buff entry groups and original physical recipients across real waits."""
from functools import lru_cache
import hashlib,json,random
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p79_cards as cards
from hs_sim.cards.simple_followup_p79_cards import (KNIGHT,REPAIR,FUNGAL,TECH,SPEAKER,HAN,CHAMPION,VALIANT,SENTINEL,CRYO,REVENANT,WYRM,ROOTS,PREFIX,load_batch,register_simple_followup_p79_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SecretSpec,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import (ChangeControl,ChoiceOption,Damage,Destroy,Freeze,InvokeBehavior,RefreshHeroPower,RequestChoice,ReturnToHand,Silence)
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,MoveCard

TEST='p79.test.'
HERO,HP,FILLER,MECH,DRAGON,TOTEM,ALL,UNKNOWN,LOCATION,OBS,COUNTER=(TEST+i for i in('hero','power','filler','mech','dragon','totem','all','unknown','location','observer','counter'))
NOP,HIT,KILL,SILENCE,BOUNCE,TAKE,FREEZE,TO_MECH,TO_DRAGON,TO_TOTEM,REFRESH,AUTO=(TEST+i for i in('nop','hit','kill','silence','bounce','take','freeze','to-mech','to-dragon','to-totem','refresh','auto'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p79_cards(r)
 elif not all(present):raise AssertionError('P79 complete assigned assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p79-small-native-fixtures');register_simple_followup_p79_cards(r)
 r.register_behavior(NOP,lambda c:())
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=NOP,metadata=meta()))
 hero_extra={}
 for cid,tribes in((FILLER,()),(MECH,('mech',)),(DRAGON,('dragon',)),(TOTEM,('totem',)),(ALL,('all',)),(UNKNOWN,None)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=5,metadata=meta(tribes)))
 r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,durability=2,on_use=NOP,metadata=meta()))
 bodies={NOP:lambda c:(),HIT:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),
  SILENCE:lambda c:(Silence(c.target_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),FREEZE:lambda c:(Freeze(c.target_id,c.source_id),),
  REFRESH:lambda c:(RefreshHeroPower(c.player_id),),AUTO:lambda c:(CastSpell(c.player_id,NOP,c.source_id),)}
 for cid,tribe in((TO_MECH,'mech'),(TO_DRAGON,'dragon'),(TO_TOTEM,'totem')):
  def change(c,tribe=tribe):
   e=c.state.entities[c.target_id];ref=MinionReference.capture(e)if e.zone==Zone.BOARD else CardReference.capture(e)
   return(ChangeMinionTribes(ref,TribeChangeSpec('set',(tribe,)),c.source_id),)
  bodies[cid]=change
 for cid,body in bodies.items():
  if cid!=NOP:r.register_behavior(cid,body)
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec()if cid in(HIT,KILL,SILENCE,BOUNCE,TAKE,FREEZE)else
   TargetSpec(zones=(Zone.BOARD,Zone.HAND),kinds=(CardType.MINION,),relation='friendly')if cid in(TO_MECH,TO_DRAGON,TO_TOTEM)else None,metadata=meta()))
 r.register_secret_condition(TEST+'counter-condition',lambda c:c.window is not None and c.window.kind=='spell')
 r.register_behavior(TEST+'counter',lambda c:(CounterSpell(c.window.id),))
 r.register_card(CardDefinition(COUNTER,COUNTER,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(TEST+'counter',('card_committed',),TEST+'counter-condition',TEST+'counter'),metadata=meta()))
 if mode is not None:
  event={'board':'stats_changed','hand':'stored_card_buffed','sentinel':'choice_skipped','spell':'spell_cast_finished','inspire':'hero_power_used','selfdamage':'minion_summoned'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='board':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==FUNGAL and c.state.entities[c.event.target_id].card_id==MECH
   if mode=='hand':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==TECH and c.state.entities[c.event.target_id].card_id==MECH
   if mode=='sentinel':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==SENTINEL
   if mode=='spell':return c.event.player_id==1 and c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==NOP
   if mode=='inspire':return c.event.player_id==1
   return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==REVENANT
  def reenter(c):return(SummonStoredCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,cause=SummonCause.capture(c)),)
  def moveback(c):return(MoveCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,Zone.HAND,source_id=c.source_id),)
  def fail(c):raise ResolutionError('P79 deliberate continuation failure')
  for name,body in(('reenter',reenter),('moveback',moveback),('fail',fail)):r.register_behavior(TEST+name,body)
  def wait(c):
   if mode=='selfdamage':return(Damage(c.event.target_id,1,c.source_id,DamageKind.EFFECT),)
   card=WYRM if mode=='spell'else TOTEM if mode=='inspire'else DRAGON
   zone='hand'if mode=='hand'else'board';target=next(c.state.entities[i]for i in getattr(c.state.players[1],zone)if c.state.entities[i].card_id==card)
   if mode=='hand':change=(MoveCard(CardReference.capture(target),1,Zone.DECK,source_id=c.source_id),InvokeBehavior(TEST+'moveback',c.source_id,1,target.id))
   elif mode=='inspire':change=(ChangeControl(target.id,2),)
   else:change=(ReturnToHand(target.id),InvokeBehavior(TEST+'reenter',c.source_id,1,target.id))
   return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original recipient',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
  r.register_behavior(TEST+'wait',wait);r.register_trigger_condition(TEST+'eligible',eligible)
  r.register_card(CardDefinition(OBS,OBS,CardType.LOCATION,durability=2,on_use=NOP,metadata=meta()))
  hero_extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**hero_extra))
 r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP79Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode
  if mode:board=(OBS,)+board
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),
   PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=7979),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1,position=None):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=(len(g.state.players[pid].board)if position is None else position)if e.kind==CardType.MINION else None));return e.id
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

 def test_a0_all_twelve_actual_paid_entries_have_complete_original_printed_bodies(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,),board=(MECH,));target=self.first(g,MECH,'board').id if cid in(KNIGHT,REPAIR)else None;source=self.play(g,cid,target);raw=rows[cid]
   self.assertEqual(self.stats(g,source),(raw['attack'],raw['health']));self.assertEqual(g.state.players[1].mana,55);self.assertEqual(sum(e.kind=='card_played'for e in g.events),1)

 def test_a1_targeted_mech_buffs_current_all_and_preserves_damage_and_silence_reset(self):
  for cid,delta in((KNIGHT,(1,1)),(REPAIR,(0,4))):
   g=self.game((HIT,cid,SILENCE),board=(ALL,));target=self.first(g,ALL,'board').id;self.play(g,HIT,target);self.play(g,cid,target)
   self.assertEqual(self.stats(g,target),(1+delta[0],2+delta[1]));self.assertEqual(g.state.entities[target].damage,3);self.play(g,SILENCE,target);self.assertEqual(self.stats(g,target),(1,min(5,2+delta[1])));self.assertEqual(g.state.entities[target].max_health,5)
  g=self.game((TO_MECH,KNIGHT),board=(FILLER,));target=self.first(g,FILLER,'board').id;self.play(g,TO_MECH,target);self.play(g,KNIGHT,target);self.assertEqual(self.stats(g,target),(2,6))

 def test_a2_mech_target_side_unknown_and_empty_available_domain_use_native_legality(self):
  g=self.game((KNIGHT,),board=(FILLER,),enemy=(MECH,));target=self.first(g,MECH,'board',2).id;self.denied(g,PlayCard(1,self.first(g,KNIGHT).id,target_id=target,position=1));self.play(g,KNIGHT)
  g=self.game((REPAIR,),board=(UNKNOWN,));snap=g.snapshot()
  with self.assertRaises((ValueError,ResolutionError)):self.play(g,REPAIR,self.first(g,UNKNOWN,'board').id)
  self.assertEqual(g.snapshot(),snap)

 def test_b0_fungalmancer_only_immediate_physical_neighbors_and_location_does_not_bridge(self):
  g=self.game((FUNGAL,),board=(FILLER,MECH,DRAGON));left=self.first(g,MECH,'board').id;right=self.first(g,DRAGON,'board').id;far=self.first(g,FILLER,'board').id
  self.play(g,FUNGAL,position=2);self.assertEqual((self.stats(g,left),self.stats(g,right),self.stats(g,far)),((3,7),(3,7),(1,5)))
  g=self.game((FUNGAL,),board=(MECH,LOCATION,DRAGON));left=self.first(g,MECH,'board').id;right=self.first(g,DRAGON,'board').id;self.play(g,FUNGAL,position=1)
  self.assertEqual((self.stats(g,left),self.stats(g,right)),((3,7),(1,5)))

 def test_b1_accepted_adjacent_recipient_cannot_rebind_after_same_id_bounce_reentry(self):
  g=self.game((FUNGAL,),board=(MECH,DRAGON),mode='board');right=self.first(g,DRAGON,'board').id;self.play(g,FUNGAL,position=2);self.fail_wait(g);self.choose(g,'change')
  self.assertIn(right,g.state.players[1].board);self.assertEqual(self.stats(g,right),(1,5));self.assertEqual(self.stats(g,self.first(g,MECH,'board').id),(3,7));self.portable(g)

 def test_c0_glowstone_buffs_only_actual_hand_minions_even_at_capacity_then_play_keeps_buff(self):
  g=self.game((TECH,MECH,NOP),board=(DRAGON,),enemy_hand=(FILLER,));target=self.first(g,MECH).id;self.play(g,TECH);self.assertEqual(self.stats(g,target),(3,7));self.assertEqual(self.stats(g,self.first(g,DRAGON,'board').id),(1,5))
  self.play(g,MECH);self.assertEqual(self.stats(g,target),(3,7));self.assertEqual(len(g.state.players[2].hand),1)
  g=self.game((TECH,)+(FILLER,)*9);self.play(g,TECH);self.assertEqual(len(g.state.players[1].hand),9);self.assertTrue(all(self.stats(g,i)==(3,7)for i in g.state.players[1].hand))

 def test_c1_dragonspeaker_current_types_all_and_unknown_are_not_printed_only_or_silently_skipped(self):
  g=self.game((SPEAKER,DRAGON,ALL,MECH));self.play(g,SPEAKER);self.assertEqual(self.stats(g,self.first(g,DRAGON).id),(4,8));self.assertEqual(self.stats(g,self.first(g,ALL).id),(4,8));self.assertEqual(self.stats(g,self.first(g,MECH).id),(1,5))
  g=self.game((TO_DRAGON,SPEAKER,MECH));target=self.first(g,MECH).id;self.play(g,TO_DRAGON,target);self.play(g,SPEAKER);self.assertEqual(self.stats(g,target),(4,8))
  g=self.game((SPEAKER,DRAGON,UNKNOWN));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,SPEAKER)
  self.assertEqual(g.snapshot(),snap)

 def test_c2_hand_batch_original_second_reference_expires_across_real_move_out_and_back(self):
  g=self.game((TECH,MECH,DRAGON),mode='hand');target=self.first(g,DRAGON).id;self.play(g,TECH);self.fail_wait(g);self.choose(g,'change')
  self.assertEqual(self.first(g,DRAGON).id,target);self.assertEqual(self.stats(g,target),(1,5));self.assertEqual(self.stats(g,self.first(g,MECH).id),(3,7));self.portable(g)

 def test_c3_han_samples_each_physical_hand_minion_once_for_both_stats_and_empty_does_not_draw_rng(self):
  g=self.game((HAN,FILLER,FILLER,FILLER,NOP));candidates=tuple(i for i in g.state.players[1].hand if g.state.entities[i].card_id==FILLER);rng=random.Random();rng.setstate(g._rng.getstate());expected=rng.choice(candidates)
  self.play(g,HAN);self.assertEqual(g._rng.getstate(),rng.getstate());self.assertEqual(self.stats(g,expected),(6,10));self.assertEqual(sum(self.stats(g,i)==(6,10)for i in candidates),1);self.portable(g)
  g=self.game((HAN,NOP));rng=g.snapshot()['rng_state'];self.play(g,HAN);self.assertEqual(g.snapshot()['rng_state'],rng)

 def test_d0_champion_and_valiant_have_distinct_actual_inspire_and_valiant_battlecry_entries(self):
  g=self.game((VALIANT,CHAMPION,REFRESH),board=(TOTEM,ALL,MECH));totem=self.first(g,TOTEM,'board').id;allid=self.first(g,ALL,'board').id;mech=self.first(g,MECH,'board').id
  self.play(g,VALIANT);self.assertEqual((self.stats(g,totem),self.stats(g,allid),self.stats(g,mech)),((3,5),(3,5),(1,5)));source=self.play(g,CHAMPION)
  g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(self.stats(g,totem),(6,6));self.assertEqual(self.stats(g,mech),(2,6));self.assertEqual(self.stats(g,source),(5,3))
  self.play(g,REFRESH);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(self.stats(g,totem),(9,7));g.apply(EndTurn(1));g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual(self.stats(g,totem),(9,7))

 def test_d1_inspire_original_recipients_follow_control_and_silence_lifecycle_without_new_clock(self):
  g=self.game((CHAMPION,),board=(TOTEM,),mode='inspire');target=self.first(g,TOTEM,'board').id;self.play(g,CHAMPION);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.fail_wait(g);self.choose(g,'change')
  self.assertIn(target,g.state.players[2].board);self.assertEqual(self.stats(g,target),(1,5));self.portable(g)
  g=self.game((CHAMPION,SILENCE),board=(TOTEM,));source=self.play(g,CHAMPION);self.play(g,SILENCE,source);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(self.stats(g,self.first(g,TOTEM,'board').id),(1,5))

 def test_e0_sentinel_real_death_buffs_one_friendly_survivor_and_empty_does_not_advance_rng(self):
  g=self.game((SENTINEL,KILL),board=(DRAGON,),enemy=(MECH,));source=self.play(g,SENTINEL);self.play(g,KILL,source);self.assertEqual(self.stats(g,self.first(g,DRAGON,'board').id),(4,8));self.assertEqual(self.stats(g,self.first(g,MECH,'board',2).id),(1,5))
  g=self.game((SENTINEL,KILL));source=self.play(g,SENTINEL);rng=g.snapshot()['rng_state'];self.play(g,KILL,source);self.assertEqual(g.snapshot()['rng_state'],rng)

 def test_e1_sentinel_sampled_original_reference_survives_wait_but_not_same_id_reentry(self):
  g=self.game((SENTINEL,KILL),board=(DRAGON,),mode='sentinel');target=self.first(g,DRAGON,'board').id;source=self.play(g,SENTINEL);self.play(g,KILL,source);self.fail_wait(g);rng=g.snapshot()['rng_state'];self.choose(g,'change')
  self.assertEqual(self.stats(g,target),(1,5));self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

 def test_f0_cryo_counts_frozen_enemy_hero_or_minion_and_never_friendly_frozen(self):
  for targetkind in('hero','minion','friendly'):
   g=self.game((FREEZE,CRYO),enemy=(FILLER,));target=g.state.players[2].hero_id if targetkind=='hero'else self.first(g,FILLER,'board',2).id if targetkind=='minion'else g.state.players[1].hero_id
   self.play(g,FREEZE,target);source=self.play(g,CRYO);self.assertEqual(self.stats(g,source),(5,5)if targetkind=='friendly'else(7,7))

 def test_f1_revenant_counts_damaged_minions_on_both_sides_but_not_heroes(self):
  g=self.game((HIT,HIT,HIT,REVENANT),board=(MECH,),enemy=(DRAGON,));self.play(g,HIT,self.first(g,MECH,'board').id);self.play(g,HIT,self.first(g,DRAGON,'board',2).id);self.play(g,HIT,g.state.players[1].hero_id)
  source=self.play(g,REVENANT);self.assertEqual(self.stats(g,source),(5,5));g=self.game((REVENANT,));source=self.play(g,REVENANT);self.assertEqual(self.stats(g,source),(3,3))

 def test_f2_revenant_includes_its_own_actual_entry_damage_and_keeps_damage_separate(self):
  g=self.game((REVENANT,),mode='selfdamage');source=self.play(g,REVENANT);e=g.state.entities[source];self.assertEqual((e.attack,e.max_health,e.damage),(4,4,1))

 def test_g0_red_wyrm_uses_real_owner_successful_cast_completions_including_native_automatic(self):
  g=self.game((WYRM,FILLER,NOP,AUTO),enemy_hand=(NOP,));source=self.play(g,WYRM);self.play(g,FILLER);self.assertEqual(g.state.entities[source].attack,2)
  self.play(g,NOP);self.assertEqual(g.state.entities[source].attack,4);self.play(g,AUTO);self.assertEqual(g.state.entities[source].attack,8)
  g.apply(EndTurn(1));self.play(g,NOP,pid=2);self.assertEqual(g.state.entities[source].attack,8)

 def test_g1_countered_cast_or_payload_source_death_cannot_award_completed_cast_buff(self):
  g=self.game((WYRM,NOP),enemy_hand=(COUNTER,));source=self.play(g,WYRM);g.apply(EndTurn(1));self.play(g,COUNTER,pid=2);g.apply(EndTurn(2));self.play(g,NOP);self.assertEqual(g.state.entities[source].attack,2)
  self.assertTrue(g.state.play_history[-1].countered);g=self.game((WYRM,KILL));source=self.play(g,WYRM);self.play(g,KILL,source);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[source].attack,2)

 def test_g2_accepted_wyrm_residence_does_not_rebind_after_completion_wait_and_same_id_reentry(self):
  g=self.game((WYRM,NOP),mode='spell');source=self.play(g,WYRM);self.play(g,NOP);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].attack,2);self.portable(g)

 def test_z0_complete_sources_and_assembled_or_unassembled_old_content_and_programs_are_exact(self):
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
