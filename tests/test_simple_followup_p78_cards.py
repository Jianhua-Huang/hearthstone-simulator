"""Two actual owner ends and original logical health; ordinary five-cost entries."""
from dataclasses import asdict
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p78_cards as cards
from hs_sim.cards.simple_followup_p78_cards import (APPLE,WHELP,RIDER,SONG,SLUDGE,WATCHER,ALCHEMIST,EMP,HEMET,LONGNECK,RAIDER,BREAKER,ROOTS,PREFIX,PROGRAM,load_batch,register_simple_followup_p78_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.adapt import CHOICE_IDS,PLANT_ID,SPORES_BEHAVIOR
from hs_sim.engine.effects import (Buff,ChangeControl,ChoiceOption,CopyMinion,Damage,Destroy,GainArmor,GrantKeyword,InvokeBehavior,RefreshHeroPower,ReplaceHero,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import (BoardPresenceReference,DamageKind,EndTurnRepeatSpec,EndTurnSpec,LimitedTriggerSpec,Runes,TribeChangeSpec)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.turn_scheduling import QueueTurns
from hs_sim.engine.zones import CardReference,MoveCard
from hs_sim.engine.allocation_facts import SourceAllocationFact
from hs_sim.engine.spent_spells import ReturnSpentSpell

TEST='p78.test.'
HERO,NEW_HERO,HP,FILLER,BEAST,MECH,ALL,UNKNOWN,POWER,DOUBLE,CASTER,OBS,WEAPON=(TEST+i for i in('hero','newhero','power','filler','beast','mech','all','unknown','spellpower','double','caster','observer','weapon'))
HURT,HIT,KILL,SILENCE,COPY,MOVE,REPLACE,EXTRA,ARMOR,TO_MECH,TO_BEAST,REFRESH,SUMMON,AUTO=(TEST+i for i in('hurt','hit','kill','silence','copy','move','replace','extra','armor','to-mech','to-beast','refresh','summon','auto'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.PRIEST,),None,runes=Runes(),tribes=tribes)
@lru_cache(maxsize=1)
def existing_adapt_material():
 r=build_registry();r.freeze()
 return tuple(r.card(i)for i in(*CHOICE_IDS,PLANT_ID))
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p78_cards(r)
 elif not all(present):raise AssertionError('P78 complete assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p78-small-native-fixtures');definitions=existing_adapt_material()
 for definition in definitions:r.register_card(definition)
 register_simple_followup_p78_cards(r)
 r.register_behavior(HP,lambda c:())
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=HP,metadata=meta()))
 for cid in(HERO,NEW_HERO):r.register_card(CardDefinition(cid,cid,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta()))
 for cid,tribes in((FILLER,()),(BEAST,('beast',)),(MECH,('mech',)),(ALL,('all',)),(UNKNOWN,None)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,attack=1,health=20,metadata=meta(tribes)))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=30,spell_damage=7,metadata=meta()))
 r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=30,end_turn_repeats=(EndTurnRepeatSpec(2,'all'),),metadata=meta()))
 r.register_card(CardDefinition(WEAPON,WEAPON,CardType.WEAPON,attack=3,durability=2,metadata=meta()))
 def move(c):
  effect=next(e for e in c.state.players[c.player_id].player_effects if e.spec_id==PROGRAM)
  return(ReturnSpentSpell(SourceAllocationFact.capture(c.state,c.state.entities[effect.source_id]),c.player_id),InvokeBehavior(TEST+'movehand',c.source_id,c.player_id,effect.source_id))
 r.register_behavior(TEST+'movehand',lambda c:(MoveCard(CardReference.capture(c.state.entities[c.target_id]),3-c.player_id,Zone.HAND,reset=True,source_id=c.source_id),))
 bodies={HURT:lambda c:(Damage(c.state.players[c.player_id].hero_id,20,c.source_id,DamageKind.EFFECT),),HIT:lambda c:(Damage(c.target_id,3,c.source_id,DamageKind.EFFECT),),
  KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),COPY:lambda c:(CopyMinion(BoardPresenceReference.capture(c.state,c.target_id),c.player_id,cause=SummonCause.capture(c)),),
  MOVE:move,REPLACE:lambda c:(ReplaceHero(c.player_id,NEW_HERO,health=30,hero_power_card_id=HP),),EXTRA:lambda c:(QueueTurns((c.player_id,),c.source_id),),
  ARMOR:lambda c:(GainArmor(c.player_id,8),),TO_MECH:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('mech',)),c.source_id),),
  TO_BEAST:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('beast',)),c.source_id),),
  REFRESH:lambda c:(RefreshHeroPower(c.player_id),),SUMMON:lambda c:(Summon(c.player_id,WHELP),),AUTO:lambda c:(CastSpell(c.player_id,ARMOR,c.source_id),)}
 for cid,body in bodies.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec()if cid in(HIT,KILL,SILENCE,COPY,TO_MECH,TO_BEAST)else None,metadata=meta()))
 if mode in('caster','opponent-caster'):
  r.register_behavior(TEST+'cast',lambda c:(CastSpell(c.player_id,APPLE,c.source_id),))
  r.register_card(CardDefinition(CASTER,CASTER,CardType.MINION,health=30,metadata=meta(),limited_triggers=(LimitedTriggerSpec('turn_ended',TEST+'cast',end_turn=EndTurnSpec('opponent'if mode=='opponent-caster'else'controller')),)))
 if mode in('install','damage'):
  def eligible(c):
   if mode=='install':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==APPLE
   result=c.health_result;return result is not None and result.source_card_id==APPLE and result.flow=='damage'
  def fail(c):raise ResolutionError('P78 deliberate continuation failure')
  r.register_behavior(TEST+'fail',fail);r.register_trigger_condition(TEST+'eligible',eligible)
  r.register_behavior(TEST+'pause',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,c.player_id),))),c.source_id),))
  r.register_card(CardDefinition(OBS,OBS,CardType.MINION,health=30,metadata=meta(),limited_triggers=(LimitedTriggerSpec('player_effect_added'if mode=='install'else'health_resolved',TEST+'pause',condition_id=TEST+'eligible'),)))
 r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP78Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,enemy_weapon=None,seed=7878):
  self.mode=mode
  if mode in('install','damage'):board=(OBS,)+board
  if mode=='caster':board=(CASTER,)+board
  if mode=='opponent-caster':enemy=(CASTER,)+enemy
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),
   PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP,weapon_card_id=enemy_weapon)),seed=seed),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def end(self,g):g.apply(EndTurn(g.state.active_player))
 def next_own(self,g):self.end(g);self.end(g)
 def effects(self,g,pid=1):return[e for e in g.state.players[pid].player_effects if e.spec_id==PROGRAM]
 def hits(self,g):return[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_card_id==APPLE and health_result(e).flow=='damage']
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(g.snapshot(),snap)
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   visible=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','source_player_id','original_entities'):self.assertNotIn('"'+key+'"',visible)

 def test_a0_apple_heals_twelve_and_only_two_actual_owner_ends_damage_three(self):
  g=self.game((HURT,APPLE));self.play(g,HURT);source=self.play(g,APPLE);self.assertEqual(self.hp(g),22);self.assertEqual(g.state.players[1].mana,58)
  self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.effects(g)[0].remaining_turns,2)
  self.end(g);self.assertEqual(self.hp(g),19);self.assertEqual(self.effects(g)[0].remaining_turns,1);self.end(g);self.assertEqual(self.hp(g),19)
  self.end(g);self.assertEqual(self.hp(g),16);self.assertEqual(self.effects(g),[]);self.next_own(g);self.assertEqual(len(self.hits(g)),2);self.portable(g)

 def test_a1_separate_apples_and_extra_actual_owner_turn_each_keep_two_independent_boundaries(self):
  g=self.game((APPLE,APPLE,EXTRA));self.play(g,APPLE);self.play(g,APPLE);ids=[e.id for e in self.effects(g)];self.assertEqual(len(set(ids)),2)
  self.play(g,EXTRA);self.end(g);self.assertEqual(g.state.active_player,1);self.assertEqual(self.hp(g),24);self.assertEqual([e.remaining_turns for e in self.effects(g)],[1,1])
  self.end(g);self.assertEqual(self.hp(g),18);self.assertEqual(self.effects(g),[]);self.assertEqual(len(self.hits(g)),4)

 def test_a2_repeated_classified_end_bodies_do_not_double_tick_the_natural_clock(self):
  g=self.game((APPLE,),board=(DOUBLE,));self.play(g,APPLE);self.end(g);self.assertEqual(self.hp(g),24);self.assertEqual(self.effects(g)[0].remaining_turns,1)
  self.end(g);self.end(g);self.assertEqual(self.hp(g),18);self.assertEqual(self.effects(g),[]);self.assertEqual(len(self.hits(g)),4);self.portable(g)

 def test_a3_install_inside_already_captured_owner_end_waits_for_two_later_ends(self):
  g=self.game(mode='caster');self.end(g);self.assertEqual(self.hp(g),30);self.assertEqual(self.effects(g)[0].remaining_turns,2);self.assertEqual(self.hits(g),[])
  self.end(g);self.end(g);self.assertEqual(self.hp(g),27);self.end(g);self.end(g);self.assertEqual(self.hp(g),24);self.assertEqual(self.effects(g),[]);self.portable(g)

 def test_a4_opponent_end_cast_uses_actual_actor_own_clock_and_hero(self):
  g=self.game(mode='opponent-caster');self.end(g);self.assertEqual(self.effects(g),[]);self.assertEqual(self.effects(g,2)[0].remaining_turns,2)
  self.end(g);self.assertEqual((self.hp(g),self.hp(g,2)),(30,27));self.end(g);self.end(g);self.assertEqual(self.hp(g,2),24);self.assertEqual(self.effects(g,2),[])

 def test_a5_source_move_and_control_reset_do_not_move_actor_and_current_replacement_hero_is_hit(self):
  g=self.game((HURT,APPLE,MOVE,REPLACE));self.play(g,HURT);source=self.play(g,APPLE);original=self.effects(g)[0].source_allocation;self.play(g,MOVE)
  self.assertIn(source,g.state.players[2].hand);self.assertEqual(g.state.entities[source].controller,2);oldhero=g.state.players[1].hero_id;self.play(g,REPLACE);newhero=g.state.players[1].hero_id;self.assertNotEqual(oldhero,newhero)
  self.end(g);hit=self.hits(g)[0];self.assertEqual((hit.source_id,hit.source_card_id,hit.source_controller,hit.target_id),(source,APPLE,1,newhero));self.assertEqual(hit.source_zone_epoch,dict(original)['zone_epoch'])
  self.assertEqual((self.hp(g),self.hp(g,2)),(27,30));self.portable(g)

 def test_a6_logical_debt_uses_native_effect_damage_and_armor_not_current_spellpower(self):
  g=self.game((APPLE,ARMOR),board=(POWER,));self.play(g,APPLE);self.play(g,ARMOR);self.end(g)
  hero=g.state.entities[g.state.players[1].hero_id];self.assertEqual((hero.health,hero.armor),(30,5));self.assertEqual(self.hits(g)[0].damage_dealt,3)

 def test_a7_install_and_damage_waits_restore_replay_and_exception_rollback_without_extra_ticks(self):
  for mode in('install','damage'):
   g=self.game((APPLE,),mode=mode);self.play(g,APPLE)
   if mode=='damage':self.end(g)
   self.assertIsNotNone(g.state.pending_choice);self.assertEqual(self.effects(g)[0].remaining_turns,2);self.portable(g);snap=g.snapshot();q=g.state.pending_choice
   with self.assertRaises(ResolutionError):g.apply(SelectChoice(1,q.id,('fail',)))
   self.assertEqual(g.snapshot(),snap);g.apply(SelectChoice(1,q.id,('ok',)))
   if mode=='install':self.end(g)
   self.assertEqual(self.effects(g)[0].remaining_turns,1);self.assertEqual(len(self.hits(g)),1);self.portable(g)

 def test_b0_whelp_real_battlecry_draws_once_and_ordinary_summon_does_not(self):
  g=self.game((WHELP,SUMMON,COPY));source=self.play(g,WHELP);self.assertEqual(len(g.state.draw_history),1);self.play(g,SUMMON);self.play(g,COPY,source)
  self.assertEqual(len(g.state.draw_history),1);self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(g.state.players[1].mana,55)

 def test_b1_rider_uses_actual_combo_only_and_original_stat_buff_is_silenceable(self):
  g=self.game((RIDER,));source=self.play(g,RIDER);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,7))
  g=self.game((ARMOR,RIDER,SILENCE));self.play(g,ARMOR);source=self.play(g,RIDER);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(7,7));self.play(g,SILENCE,source);self.assertEqual(g.state.entities[source].attack,3)

 def test_b2_songstealer_silences_actual_target_and_is_playable_without_an_available_target(self):
  from hs_sim.engine.lifecycle import active_abilities
  g=self.game((SONG,),enemy=(DOUBLE,));target=self.first(g,DOUBLE,'board',2).id;self.play(g,SONG,target);self.assertTrue(g.state.entities[target].silenced);self.assertEqual(active_abilities(g.state.entities[target],'end_turn_repeat'),())
  g=self.game((SONG,));self.play(g,SONG);self.assertEqual(len(g.state.players[1].board),1)

 def test_b3_sludge_destroys_only_actual_enemy_weapon_and_no_weapon_is_noop(self):
  g=self.game((SLUDGE,),enemy_weapon=WEAPON);weapon=g.state.players[2].weapon_id;self.play(g,SLUDGE);self.assertIsNone(g.state.players[2].weapon_id);self.assertEqual(g.state.entities[weapon].zone,Zone.GRAVEYARD)
  g=self.game((SLUDGE,));self.play(g,SLUDGE);self.assertIsNone(g.state.players[2].weapon_id)

 def test_b4_fixed_battlecry_heals_characters_eight_or_five_and_clamps_to_maximum(self):
  for cid,expected in((WATCHER,18),(ALCHEMIST,15)):
   g=self.game((HURT,cid));self.play(g,HURT);self.play(g,cid,g.state.players[1].hero_id);self.assertEqual(self.hp(g),expected)
  g=self.game((WATCHER,HIT),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.play(g,HIT,target);self.play(g,WATCHER,target);self.assertEqual(g.state.entities[target].health,20)

 def test_b5_emp_and_hemet_target_current_tribe_all_and_optional_empty_domain(self):
  for cid,tribe,tool in((EMP,MECH,TO_MECH),(HEMET,BEAST,TO_BEAST)):
   for targetcid in(tribe,ALL):
    g=self.game((cid,),enemy=(targetcid,));target=self.first(g,targetcid,'board',2).id;self.play(g,cid,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
   g=self.game((tool,cid),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.play(g,tool,target);self.play(g,cid,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD)
   g=self.game((cid,),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.denied(g,PlayCard(1,self.first(g,cid).id,target_id=target,position=0));self.play(g,cid)

 def test_b6_unknown_target_tribe_fails_explicitly_without_payment_or_rng_changes(self):
  g=self.game((EMP,),enemy=(UNKNOWN,));snap=g.snapshot()
  with self.assertRaises((ResolutionError,ValueError)):self.play(g,EMP,self.first(g,UNKNOWN,'board',2).id)
  self.assertEqual(g.snapshot(),snap)

 def test_b7_longneck_one_actual_adapt_wait_preserves_original_payment_and_all_fixed_outcomes(self):
  g=self.game((LONGNECK,));source=self.play(g,LONGNECK);q=g.state.pending_choice;self.assertEqual(len(q.options),3);self.assertTrue({o.card_id for o in q.options}<=set(CHOICE_IDS));self.portable(g)
  self.denied(g,SelectChoice(1,q.id,('not-an-offer',)));g.apply(SelectChoice(1,q.id,(q.options[0].id,)));self.assertEqual(g.state.players[1].mana,55);self.assertEqual(len(g.state.battlecry_history),1);self.assertIn(source,g.state.players[1].board);self.portable(g)

 def test_b8_raider_inspire_follows_completed_owner_manual_power_and_native_lifecycle(self):
  g=self.game((RAIDER,REFRESH,AUTO,SILENCE));source=self.play(g,RAIDER);self.play(g,AUTO);self.assertEqual(g.state.entities[source].attack,4)
  g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(6,6));self.play(g,REFRESH);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(g.state.entities[source].attack,8)
  self.end(g);g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual(g.state.entities[source].attack,8);self.end(g);self.play(g,SILENCE,source);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(g.state.entities[source].attack,4)

 def test_b8a_real_offered_living_spores_uses_the_existing_shared_death_body_and_both_plants(self):
  for seed in range(12):
   g=self.game((LONGNECK,KILL),seed=seed);source=self.play(g,LONGNECK);q=g.state.pending_choice;option=next((o for o in q.options if o.card_id=='UNG_999t2'),None)
   if option is None:continue
   g.apply(SelectChoice(1,q.id,(option.id,)));self.play(g,KILL,source)
   self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[PLANT_ID,PLANT_ID]);self.portable(g);return
  self.fail('No actual Living Spores offer in the explicit twelve native seeds')

 def test_b9_platebreaker_removes_all_actual_enemy_armor_and_keeps_hero_health(self):
  g=self.game((BREAKER,),enemy_hand=(ARMOR,ARMOR));self.end(g);self.play(g,ARMOR,pid=2);self.play(g,ARMOR,pid=2);self.end(g);self.play(g,BREAKER)
  hero=g.state.entities[g.state.players[2].hero_id];self.assertEqual((hero.armor,hero.health),(0,30));g=self.game((BREAKER,));self.play(g,BREAKER);self.assertEqual(self.hp(g,2),30)

 def test_z0_complete_source_pins_old_programs_and_existing_adapt_definitions_are_preserved(self):
  from tools.card_batch import check_face
  from hs_sim.targets import canonical_digest
  d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(1,11,11,26))
  rows={x['record']['id']:x['record']for k in('cards','dependencies','evidence_only')for x in d[k]}
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  self.assertIn('end of your turn',rows['EDR_482e']['text_en']);self.assertFalse(d['timing_evidence']['direct_relationship_certified'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  for pid,p in before.player_effects.items():self.assertEqual(after.player_effect(pid),p)
  self.assertEqual(set(after.player_effects)-set(before.player_effects),{PROGRAM}-set(before.player_effects));self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for cid,pin in d['existing_dependency_definition_pins'].items():self.assertEqual(canonical_digest(asdict(after.card(cid))),pin['sha256'])
  for key in('fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)

if __name__=='__main__':unittest.main()
