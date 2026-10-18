"""Whole Spare Part family and native targeted Battlecry/hand/clock lifetimes."""
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p93_cards as cards
from hs_sim.cards.simple_followup_p93_cards import GNOME,VETERAN,GUARD,LUMI,FILLET,VENDOR,STAFF,PLATING,REWINDER,HORN,CLOAK,COOLANT,SWITCH,BLADES,ROOTS,SPARES,ALL_IDS,load_batch,register_simple_followup_p93_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,InvokeBehavior,RequestChoice,Silence,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.pools import GenerateFromCandidates
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.tribes import ChangeMinionTribes
P='p93.test.'
HERO,FILLER,MECH,ALL,ZERO,WEAPON,POWER,KILL,HIT,BUFF,SILENCE,TAKE,SHIFT,TRIGGER,BADGEN,UNKNOWN=(P+x for x in('hero','filler','mech','all','zero','weapon','power','kill','hit','buff','silence','take','shift','trigger','badgen','unknown'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=tribes,factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p93_cards.register_simple_followup_p93_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ALL_IDS)
 if not any(present):register_simple_followup_p93_cards(r)
 elif not all(present):raise AssertionError('Complete P93 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p93-small-native');register_simple_followup_p93_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P93 deliberate native transaction failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 r.register_behavior(P+'fill',lambda c:(AddToHand(1,FILLER,c.source_id),))
 r.register_behavior(P+'steal',lambda c:(ChangeControl(c.event.target_id,2),InvokeBehavior(P+'wait',c.source_id,1)))
 scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),BUFF:lambda c:(Buff(c.target_id,3,4,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),SHIFT:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('beast',)),c.source_id),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),BADGEN:lambda c:(GenerateFromCandidates(c.player_id,(*SPARES,UNKNOWN),c.source_id),)}
 for cid,fn in scripts.items():
  r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid!=BADGEN else None,metadata=meta()))
 for cid,atk,hp,tribes in((FILLER,2,5,()),(MECH,2,3,('mech',)),(ALL,1,4,('all',)),(ZERO,0,2,())):r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp,metadata=meta(tribes)))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=20,spell_damage=5,metadata=meta()))
 r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=1,durability=2,metadata=meta()))
 extra={}
 if mode:
  event={'hand':'stored_card_buffed','reject':'stored_card_buffed','generated':'card_added_to_hand','fill':'card_committed','armor':'armor_gained','swap':'stats_changed','steal':'spell_cast_started'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='armor':return c.event.player_id==1
   if mode=='generated':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==GNOME
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in((KILL,)if mode=='fill'else(CLOAK,)if mode=='steal'else(SWITCH,)if mode=='swap'else(STAFF,))
  r.register_trigger_condition(P+'eligible',eligible);bid=P+('fill'if mode=='fill'else'fail'if mode=='reject'else'steal'if mode=='steal'else'wait');extra['limited_triggers']=(LimitedTriggerSpec(event,bid,condition_id=P+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=100,metadata=meta(),**extra));r.validate();return r
@lru_cache(None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable independent registry key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP93Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,seed=9393,armor=0):
  self.mode=mode;return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60,armor=armor),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=seed),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def portable(self,g):
  r=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
  for pid in(1,2):
   text=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',text)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);s=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),s)
 def stats(self,g,cid,zone='board',pid=1):
  e=self.first(g,cid,zone,pid);return e.attack,e.health

 def test_a0_all_fourteen_actual_paid_entries_with_real_target_contracts(self):
  for cid in ALL_IDS:
   with self.subTest(cid=cid):
    g=self.game((cid,),board=(FILLER,MECH));target=self.first(g,MECH if cid==LUMI else FILLER,'board').id if cid in(VETERAN,GUARD,LUMI,*SPARES)else g.state.players[2].hero_id if cid==FILLET else None;source=self.play(g,cid,target);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid);self.assertEqual(g.state.players[1].mana,59);self.assertEqual(g.state.play_history[0].card_id,cid);self.assertEqual(g.registry.card(cid).metadata,cards.metadata_from_record(raw))
    if cid in ROOTS:self.assertEqual((g.state.entities[source].attack,g.state.entities[source].max_health),(raw['attack'],raw['health']))
 def test_a1_all_parts_require_minion_and_friendly_rewind_cloak_reject_enemy(self):
  for cid in SPARES:
   g=self.game((cid,));s=g.snapshot()
   for target in(None,g.state.players[1].hero_id):
    with self.assertRaises(IllegalAction):self.play(g,cid,target)
    self.assertEqual(g.snapshot(),s)
  for cid in(REWINDER,CLOAK):
   g=self.game((cid,),enemy=(FILLER,));s=g.snapshot()
   with self.assertRaises(IllegalAction):self.play(g,cid,self.first(g,FILLER,'board',2).id)
   self.assertEqual(g.snapshot(),s)
 def test_b0_friendly_optional_battlecries_buff_or_taunt_and_empty_still_play(self):
  for cid in(VETERAN,GUARD,LUMI):
   g=self.game((cid,));self.play(g,cid);self.assertEqual(len(g.state.players[1].board),1)
  g=self.game((VETERAN,GUARD),board=(FILLER,));target=self.first(g,FILLER,'board').id;self.play(g,VETERAN,target);self.play(g,GUARD,target);self.assertEqual(self.stats(g,FILLER),(3,5));self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords);self.portable(g)
 def test_b1_lumi_uses_current_mech_and_all_tribes_not_printed_membership(self):
  g=self.game((LUMI,),board=(ALL,));self.play(g,LUMI,self.first(g,ALL,'board').id);self.assertEqual(self.stats(g,ALL),(2,5));self.portable(g)
  g=self.game((SHIFT,LUMI),board=(MECH,));target=self.first(g,MECH,'board').id;self.play(g,SHIFT,target);s=g.snapshot()
  with self.assertRaises(IllegalAction):self.play(g,LUMI,target)
  self.assertEqual(g.snapshot(),s);self.play(g,LUMI);self.assertEqual(self.stats(g,MECH),(2,3));self.portable(g)
 def test_b2_fillet_is_actual_minion_ability_damage_without_spell_bonus(self):
  g=self.game((FILLET,),board=(POWER,));source=self.play(g,FILLET,g.state.players[2].hero_id);r,=g.state.damage_history;self.assertEqual((r.health_result.source_id,r.health_result.base_amount,r.health_result.spell_bonus,r.health_result.damage_kind),(source,1,0,DamageKind.MINION_ABILITY.value));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,99);self.portable(g)
 def test_b3_vendor_native_armor_tail_wait_has_no_health_change(self):
  g=self.game((VENDOR,),mode='armor');self.play(g,VENDOR);self.fail_wait(g);self.assertEqual([g.state.entities[g.state.players[p].hero_id].armor for p in(1,2)],[4,0]);self.choose(g);self.assertEqual([g.state.entities[g.state.players[p].hero_id].armor for p in(1,2)],[4,4]);self.assertFalse(g.state.damage_history);self.portable(g)
 def test_c0_staff_health_only_current_hand_minions_persists_into_play(self):
  g=self.game((STAFF,FILLER,MECH,PLATING,WEAPON),board=(FILLER,),enemy_hand=(FILLER,));source=self.play(g,STAFF);self.assertEqual(self.stats(g,FILLER,'hand'),(2,6));self.assertEqual(self.stats(g,MECH,'hand'),(2,4));self.assertEqual(self.stats(g,FILLER),(2,5));self.assertEqual(self.stats(g,FILLER,'hand',2),(2,5));self.assertEqual(self.stats(g,FILLER,'deck'),(2,5));self.assertEqual(g.state.entities[source].max_health,2);self.assertEqual(self.first(g,PLATING).max_health,0);self.assertEqual(self.first(g,WEAPON).durability,2);self.play(g,FILLER);self.assertEqual(g.state.entities[g.state.players[1].board[-1]].health,6);self.portable(g)
 def test_c1_staff_original_ordered_hand_group_wait_no_duplicate_health(self):
  g=self.game((STAFF,FILLER,MECH),mode='hand');self.play(g,STAFF);self.fail_wait(g);self.assertEqual((self.stats(g,FILLER,'hand'),self.stats(g,MECH,'hand')),((2,6),(2,3)));self.choose(g);self.assertEqual((self.stats(g,FILLER,'hand'),self.stats(g,MECH,'hand')),((2,6),(2,4)));self.portable(g)
 def test_c2_staff_failure_rolls_back_actual_hand_health_and_payment(self):
  g=self.game((STAFF,FILLER,MECH),mode='reject');s=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,STAFF)
  self.assertEqual(g.snapshot(),s)
 def test_d0_plating_blades_and_horn_allow_enemy_minions_with_exact_values(self):
  g=self.game((PLATING,BLADES,HORN),enemy=(MECH,));target=self.first(g,MECH,'board',2).id;self.play(g,PLATING,target);self.play(g,BLADES,target);self.play(g,HORN,target);self.assertEqual(self.stats(g,MECH,pid=2),(3,4));self.assertIn(Keyword.TAUNT,g.state.entities[target].keywords);self.portable(g)
 def test_d1_rewinder_returns_original_friendly_entity_and_resets_board_buffs(self):
  g=self.game((BUFF,REWINDER),board=(FILLER,));target=self.first(g,FILLER,'board').id;self.play(g,BUFF,target);self.assertEqual(self.stats(g,FILLER),(5,9));self.play(g,REWINDER,target);self.assertEqual(self.first(g,FILLER).id,target);self.assertEqual(self.stats(g,FILLER,'hand'),(2,5));self.assertFalse(g.state.death_history);self.portable(g)
 def test_d2_coolant_native_freeze_lasts_through_victims_missed_attack_turn(self):
  g=self.game((COOLANT,),enemy=(MECH,));target=self.first(g,MECH,'board',2).id;self.play(g,COOLANT,target);self.assertTrue(g.state.entities[target].frozen);g.apply(EndTurn(1));s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(2,target,g.state.players[1].hero_id))
  self.assertEqual(g.snapshot(),s);g.apply(EndTurn(2));self.assertFalse(g.state.entities[target].frozen);self.portable(g)
 def test_e0_switch_swaps_current_remaining_stats_atomically_before_notification(self):
  g=self.game((HIT,SWITCH),board=(FILLER,),mode='swap');target=self.first(g,FILLER,'board').id;self.play(g,HIT,target);self.assertEqual(self.stats(g,FILLER),(2,4));self.play(g,SWITCH,target);self.fail_wait(g);self.assertEqual(self.stats(g,FILLER),(4,2));self.assertEqual(g.state.entities[target].damage,0);self.assertEqual(len(g.state.damage_history),1);self.choose(g);self.portable(g)
 def test_e1_switch_zero_attack_causes_ordinary_zero_health_death(self):
  g=self.game((SWITCH,),board=(ZERO,));target=self.first(g,ZERO,'board').id;self.play(g,SWITCH,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.death_history[-1].card_id,ZERO);self.assertFalse(g.state.damage_history);self.portable(g)
 def test_f0_cloak_expiry_keeps_caster_clock_after_control_transfer(self):
  g=self.game((CLOAK,TAKE),board=(MECH,));target=self.first(g,MECH,'board').id;self.play(g,CLOAK,target);self.play(g,TAKE,target);self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords);g.apply(EndTurn(1));self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords);self.portable(g);g.apply(EndTurn(2));self.assertNotIn(Keyword.STEALTH,g.state.entities[target].keywords);self.portable(g)
 def test_f1_cloak_body_binds_caster_after_actual_spell_start_control_change(self):
  g=self.game((CLOAK,),board=(MECH,),mode='steal');target=self.first(g,MECH,'board').id;self.play(g,CLOAK,target);self.assertEqual(g.state.entities[target].controller,2);self.assertNotIn(Keyword.STEALTH,g.state.entities[target].keywords);self.fail_wait(g);self.choose(g);self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords);g.apply(EndTurn(1));self.assertIn(Keyword.STEALTH,g.state.entities[target].keywords);self.portable(g);g.apply(EndTurn(2));self.assertNotIn(Keyword.STEALTH,g.state.entities[target].keywords);self.portable(g)
 def test_g0_gnome_native_random_generation_reaches_all_seven_complete_parts(self):
  seen=set()
  for seed in range(64):
   g=self.game((KILL,),board=(GNOME,),seed=seed);source=self.first(g,GNOME,'board').id;before=g.snapshot()['rng_state'];self.play(g,KILL,source);hand=g.state.players[1].hand;self.assertEqual(len(hand),1);cid=g.state.entities[hand[0]].card_id;self.assertIn(cid,SPARES);seen.add(cid);self.assertNotEqual(g.snapshot()['rng_state'],before);self.assertTrue(any(e.kind=='card_added_to_hand'and e.source_id==source for e in g.events))
   if seen==set(SPARES):break
  self.assertEqual(seen,set(SPARES));self.portable(g)
 def test_g1_gnome_live_trigger_stolen_death_and_silence_use_native_source(self):
  g=self.game((TRIGGER,),board=(GNOME,));source=self.first(g,GNOME,'board').id;self.play(g,TRIGGER,source);self.assertEqual(len(g.state.players[1].hand),1);self.assertFalse(g.state.death_history);self.portable(g)
  g=self.game((TAKE,KILL),board=(GNOME,));source=self.first(g,GNOME,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);self.assertIn(g.state.entities[g.state.players[2].hand[0]].card_id,SPARES);self.portable(g)
  g=self.game((SILENCE,KILL),board=(GNOME,));source=self.first(g,GNOME,'board').id;self.play(g,SILENCE,source);rng=g.snapshot()['rng_state'];self.play(g,KILL,source);self.assertEqual(g.state.players[1].hand,[]);self.assertEqual(g.snapshot()['rng_state'],rng)
 def test_g2_gnome_original_random_part_hand_wait_restores_without_resampling(self):
  g=self.game((KILL,),board=(GNOME,),mode='generated');self.play(g,KILL,self.first(g,GNOME,'board').id);self.fail_wait(g);original=tuple(g.state.players[1].hand);rng=g.snapshot()['rng_state'];self.choose(g);self.assertEqual(tuple(g.state.players[1].hand),original);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_g3_gnome_overflow_preserves_actual_complete_selected_part(self):
  g=self.game((KILL,)+(FILLER,)*9,board=(GNOME,),mode='fill');self.play(g,KILL,self.first(g,GNOME,'board').id);parts=[e for e in g.state.entities.values()if e.card_id in SPARES];self.assertEqual(len(parts),1);self.assertEqual(parts[0].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),10);self.assertEqual(g.registry.card(parts[0].card_id).cost,1);self.portable(g)
 def test_g4_explicit_unknown_candidate_is_rejected_before_rng_not_cropped(self):
  g=self.game((BADGEN,));s=g.snapshot()
  with self.assertRaises((ResolutionError,ValueError)):self.play(g,BADGEN)
  self.assertEqual(g.snapshot(),s)
 def test_z0_full_family_rows28_faces14_edges_and_old_assembly_preservation(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['evidence_only']),len(d['official_observations']),len(d['exact_parent_child_links'])),(14,4,28,14));self.assertEqual(tuple(d['spare_part_family']['full_source_spare_part_spell_ids']),SPARES);self.assertTrue(all(x['record']['type']=='ENCHANTMENT'for x in d['evidence_only']));r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),14);self.assertFalse(d['new_standard_collectible_roots']);self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for cid in SPARES:self.assertEqual(r1.card(cid).kind,CardType.SPELL);self.assertFalse(r1.card(cid).metadata.collectible)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
