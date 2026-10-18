"""Actual native source, ordered physical tutors and declared complete dependencies."""
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p82_cards as cards
from hs_sim.cards.simple_followup_p82_cards import (GUIDE,RAIDER,SMITH,KODO,BULLY,ARMOR,INFIL,WHATLEY,ACOLYTE,INVENTOR,DEMON,ANNOY,COIN,ROOTS,DEFERRED,PREFIX,load_batch,register_simple_followup_p82_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.effects import (AddToHand,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,GainTemporaryMana,GrantKeyword,Heal,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import CostSpec,DamageKind,HealingKind,LimitedTriggerSpec,Runes,SpellSchool
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.zones import CardReference,ModifyStoredCost

TEST='p82.test.'
HERO,HP,FILLER,LOW,BIG,MECH,DRAGON,PIRATE,ALL,MULTI,UNKNOWN,SHIELDED=(TEST+i for i in('hero','power','filler','low','big','mech','dragon','pirate','all','multi','unknown','shielded'))
NOP,PING,ZERO,BLAST,KILL,SILENCE,TAKE,SHIELD,HEAL,TWIN,DECK_ONE=(TEST+i for i in('nop','ping','zero','blast','kill','silence','take','shield','heal','twin','deck-one'))
S1,S2,S3,S4,HOLY,SHADOW=(TEST+i for i in('one','two','three','four','holy','shadow'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p82_cards(r)
 elif not all(present):raise AssertionError('P82 complete assigned supported assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p82-small-native-fixtures');raw=load_batch()['existing_dependencies'][0]['record']
 r.register_behavior('m2.temporary_mana',lambda c:(GainTemporaryMana(c.player_id,1),))
 r.register_card(CardDefinition(COIN,raw['name'],CardType.SPELL,cost=0,on_play='m2.temporary_mana',metadata=metadata_from_record(raw)))
 register_simple_followup_p82_cards(r);r.register_behavior(NOP,lambda c:())
 for cid,a,h,tribes,kw in((FILLER,1,12,(),()),(LOW,1,1,(),()),(BIG,8,12,(),()),(MECH,1,12,('mech',),()),(DRAGON,1,12,('dragon',),()),(PIRATE,1,12,('pirate',),()),(ALL,1,12,('all',),()),(MULTI,1,12,('mech','dragon','pirate'),()),(UNKNOWN,1,12,None,()),(SHIELDED,1,12,(),(Keyword.DIVINE_SHIELD,))):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=a,health=h,keywords=kw,metadata=meta(tribes)))
 for cid,cost,school in((S1,1,None),(S2,2,None),(S3,3,None),(S4,4,None),(HOLY,4,SpellSchool.HOLY),(SHADOW,4,SpellSchool.SHADOW)):
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=cost,spell_school=school,on_play=NOP,metadata=meta()))
 def deck_cost(c,n):
  target=next(c.state.entities[i]for i in c.state.players[1].deck if c.state.entities[i].card_id==S4)
  return(ModifyStoredCost(CardReference.capture(target),CostSpec(set_to=n),c.source_id),)
 def fail(c):raise ResolutionError('P82 deliberate continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def reenter(c):
  e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
 r.register_behavior(TEST+'reenter',reenter)
 def wait(c):
  change=()
  if mode=='attack':
   source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==RAIDER)
   change=(ReturnToHand(source),InvokeBehavior(TEST+'reenter',c.source_id,1,source))
  elif mode=='health':change=(Destroy(c.health_result.source_id,c.source_id),)
  elif mode=='draw':change=deck_cost(c,2)
  elif mode=='spell':
   source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==BULLY);change=(Destroy(source,c.source_id),)
  elif mode=='death':
   target=next(i for i in c.state.players[2].board if c.state.entities[i].card_id==FILLER)
   change=(Destroy(target,c.source_id),Summon(2,LOW))
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original context',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=NOP,metadata=meta()))
 bodies={PING:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),ZERO:lambda c:(Damage(c.target_id,0,c.source_id,DamageKind.EFFECT),),BLAST:lambda c:(Damage(c.target_id,20,c.source_id,DamageKind.EFFECT),),
  KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),SHIELD:lambda c:(GrantKeyword(c.target_id,Keyword.DIVINE_SHIELD,c.source_id),),HEAL:lambda c:(Heal(c.target_id,1,c.source_id,HealingKind.EFFECT),),
  TWIN:lambda c:(DamageBatch((Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),Damage(c.target_id,1,c.source_id,DamageKind.EFFECT))),),DECK_ONE:lambda c:deck_cost(c,1)}
 for cid,body in bodies.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=None if cid==DECK_ONE else TargetSpec(),metadata=meta()))
 r.register_card(CardDefinition(NOP,NOP,CardType.SPELL,cost=0,on_play=NOP,metadata=meta()))
 extra={}
 if mode is not None:
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='attack':return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id==RAIDER
   if mode=='health':return c.health_result is not None and c.health_result.source_card_id==ARMOR and c.health_result.damage_dealt>0
   if mode=='draw':return c.event.player_id==1
   if mode=='spell':return c.event.player_id==2
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in(GUIDE,INFIL,ACOLYTE)
  event={'attack':'choice_skipped','health':'health_resolved','draw':'card_drawn','spell':'spell_cast_started','death':'minion_died'}[mode]
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP82Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=None,mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12 if deck is None else deck,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8282),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
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
 def drawn(self,g):return[(r.card_id,r.entity_id)for r in g.state.draw_history if r.player_id==1]
 def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor

 def test_a0_all_twelve_actual_paid_entries_and_native_keywords(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,));source=self.play(g,cid);raw=rows[cid];e=g.state.entities[source]
   self.assertEqual((e.attack,e.health),(raw['attack'],raw['health']));self.assertEqual(g.state.players[1].mana,60-raw['cost']);self.assertEqual(sum(e.kind=='card_played'for e in g.events),1)
   if cid in(GUIDE,ARMOR,INFIL,DEMON,ANNOY):self.assertIn(Keyword.TAUNT,e.keywords)
   if cid==ANNOY:self.assertIn(Keyword.DIVINE_SHIELD,e.keywords)

 def test_b0_smith_frenzy_buffs_other_friends_once_not_self_or_enemy(self):
  g=self.game((SMITH,TWIN,PING),board=(FILLER,),enemy=(FILLER,));source=self.play(g,SMITH);self.play(g,TWIN,source);friend=self.first(g,FILLER,'board');self.assertEqual((friend.attack,friend.health),(3,14));self.assertEqual(g.state.entities[source].attack,3);self.assertEqual(self.first(g,FILLER,'board',2).attack,1);self.play(g,PING,source);self.assertEqual(friend.attack,3)

 def test_b1_frenzy_rejects_zero_shield_heal_lethal_and_silence(self):
  g=self.game((SMITH,ZERO,SHIELD,PING,HEAL),board=(FILLER,));source=self.play(g,SMITH);self.play(g,ZERO,source);self.play(g,SHIELD,source);self.play(g,PING,source);self.play(g,HEAL,source);self.assertEqual(self.first(g,FILLER,'board').attack,1)
  for op in(BLAST,SILENCE):
   g=self.game((SMITH,op,PING),board=(FILLER,));source=self.play(g,SMITH);self.play(g,op,source)
   if op==SILENCE:self.play(g,PING,source)
   self.assertEqual(self.first(g,FILLER,'board').attack,1)

 def test_b2_raider_frenzy_forces_one_actual_attack_including_enemy_hero(self):
  g=self.game((RAIDER,PING));source=self.play(g,RAIDER);self.play(g,PING,source);self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.assertEqual(len(g.state.character_attack_history),1);self.assertEqual(g.state.character_attack_history[0].declaration.source_id,source);self.portable(g)

 def test_b3_raider_original_attacker_residence_is_not_rebound_after_real_random_wait(self):
  g=self.game((RAIDER,PING),mode='attack');source=self.play(g,RAIDER);self.play(g,PING,source);self.fail_wait(g);rng=g.snapshot()['rng_state'];self.choose(g,'change');self.assertEqual(g.state.entities[source].health,6);self.assertEqual(len(g.state.character_attack_history),0);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)

 def test_c0_armorsmith_reward_uses_actual_dealt_damage_including_overkill(self):
  for target in(FILLER,LOW):
   g=self.game(board=(ARMOR,),enemy=(target,));source=self.first(g,ARMOR,'board').id;g.apply(Attack(1,source,self.first(g,target,'board',2).id));self.assertEqual(self.armor(g),3)
   hits=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source];self.assertEqual(hits[0].damage_dealt,3)

 def test_c1_armorsmith_does_not_reward_taken_blocked_zero_or_healing(self):
  g=self.game((PING,ZERO,HEAL),board=(ARMOR,));source=self.first(g,ARMOR,'board').id;self.play(g,PING,source);self.play(g,ZERO,source);self.play(g,HEAL,source);self.assertEqual(self.armor(g),0)
  g=self.game(board=(ARMOR,),enemy=(SHIELDED,));g.apply(Attack(1,self.first(g,ARMOR,'board').id,self.first(g,SHIELDED,'board',2).id));self.assertEqual(self.armor(g),0)

 def test_c2_armorsmith_original_external_reward_survives_lethal_combat_and_later_source_death(self):
  g=self.game(board=(ARMOR,),enemy=(BIG,));source=self.first(g,ARMOR,'board').id;g.apply(EndTurn(1));g.apply(Attack(2,self.first(g,BIG,'board',2).id,source));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.armor(g),3)
  g=self.game(board=(ARMOR,),enemy=(FILLER,),mode='health');source=self.first(g,ARMOR,'board').id;g.apply(Attack(1,source,self.first(g,FILLER,'board',2).id));self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.armor(g),3);self.portable(g)

 def test_d0_spirit_guide_actual_death_draws_holy_then_shadow_physical_entities(self):
  g=self.game((GUIDE,KILL),deck=(SHADOW,FILLER,HOLY));original={g.state.entities[i].card_id:i for i in g.state.players[1].deck};source=self.play(g,GUIDE);self.play(g,KILL,source)
  self.assertEqual(self.drawn(g),[(HOLY,original[HOLY]),(SHADOW,original[SHADOW])]);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

 def test_d1_empty_matching_death_draws_skip_without_fatigue_or_rng_and_silence_removes_text(self):
  g=self.game((GUIDE,KILL),deck=());source=self.play(g,GUIDE);rng=g.snapshot()['rng_state'];self.play(g,KILL,source);self.assertEqual(self.drawn(g),[]);self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,30)
  g=self.game((GUIDE,SILENCE,KILL),deck=(HOLY,SHADOW));source=self.play(g,GUIDE);self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertEqual(self.drawn(g),[])

 def test_d2_kodobane_matches_current_local_deck_cost_not_printed(self):
  g=self.game((DECK_ONE,KODO),deck=(S4,S2,S3,FILLER));self.play(g,DECK_ONE);self.play(g,KODO);self.assertEqual([i[0]for i in self.drawn(g)],[S4,S2,S3]);self.assertEqual(len(g.state.players[1].deck),1)

 def test_d3_ordered_physical_tutor_requeries_later_cost_after_real_draw_wait(self):
  g=self.game((KODO,),deck=(S1,S4,S3),mode='draw');self.play(g,KODO);self.fail_wait(g);self.assertEqual([i[0]for i in self.drawn(g)],[S1]);self.choose(g,'change');self.assertEqual([i[0]for i in self.drawn(g)],[S1,S4,S3]);self.portable(g)

 def test_d4_whatley_draws_ordered_current_mech_dragon_pirate_without_reusing_one_physical_card(self):
  for first in(MULTI,ALL):
   g=self.game((WHATLEY,),deck=(first,));source=self.play(g,WHATLEY);self.assertEqual([i[0]for i in self.drawn(g)],[first]);self.assertEqual(len(g.state.players[1].deck),0)
  g=self.game((WHATLEY,),deck=(PIRATE,DRAGON,MECH));self.play(g,WHATLEY);self.assertEqual([i[0]for i in self.drawn(g)],[MECH,DRAGON,PIRATE]);self.assertEqual(len({i[1]for i in self.drawn(g)}),3)

 def test_d5_unknown_relevant_current_tribe_fails_and_rolls_back_native_draw_group(self):
  g=self.game((WHATLEY,),deck=(UNKNOWN,MECH));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,WHATLEY)
  self.assertEqual(g.snapshot(),snap)

 def test_e0_bully_only_opponent_real_spell_start_gives_existing_coin_not_minion_or_power(self):
  g=self.game((BULLY,NOP),enemy_hand=(NOP,FILLER));self.play(g,BULLY);self.play(g,NOP);self.assertEqual(self.count(g,COIN,'hand'),0);g.apply(EndTurn(1));self.play(g,FILLER,pid=2);g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual(self.count(g,COIN,'hand'),0);self.play(g,NOP,pid=2);self.assertEqual(self.count(g,COIN,'hand'),1);self.portable(g)

 def test_e1_bully_original_cast_start_external_coin_survives_later_source_death_across_wait(self):
  g=self.game((BULLY,),enemy_hand=(NOP,),mode='spell');source=self.play(g,BULLY);g.apply(EndTurn(1));self.play(g,NOP,pid=2);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.count(g,COIN,'hand'),1);self.portable(g)

 def test_e2_bully_silence_and_control_change_follow_native_current_controller(self):
  g=self.game((BULLY,SILENCE),enemy_hand=(NOP,));source=self.play(g,BULLY);self.play(g,SILENCE,source);g.apply(EndTurn(1));self.play(g,NOP,pid=2);self.assertEqual(self.count(g,COIN,'hand'),0)
  g=self.game((BULLY,TAKE,NOP));source=self.play(g,BULLY);self.play(g,TAKE,source);self.play(g,NOP);self.assertEqual(self.count(g,COIN,'hand',2),1)

 def test_f0_infiltrator_natural_grave_random_destroy_enemy_minion_and_empty_no_rng(self):
  g=self.game((INFIL,KILL),enemy=(FILLER,));source=self.play(g,INFIL);target=self.first(g,FILLER,'board',2).id;self.play(g,KILL,source);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
  g=self.game((INFIL,KILL));source=self.play(g,INFIL);rng=g.snapshot()['rng_state'];self.play(g,KILL,source);self.assertEqual(g.snapshot()['rng_state'],rng)

 def test_f1_death_random_destroy_uses_current_enemy_after_earlier_reaction_and_retains_dead_source(self):
  g=self.game((INFIL,KILL),enemy=(FILLER,),mode='death');source=self.play(g,INFIL);self.play(g,KILL,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.players[2].board,[]);self.assertTrue(any(e.card_id==LOW and e.zone==Zone.GRAVEYARD for e in g.state.entities.values()));self.portable(g)

 def test_f2_burning_blade_actual_death_summons_exact_five_eight_taunt_demon_and_capacity(self):
  g=self.game((ACOLYTE,KILL));source=self.play(g,ACOLYTE);self.play(g,KILL,source);token=self.first(g,DEMON,'board');self.assertEqual((token.attack,token.health,g.registry.card(DEMON).cost),(5,8,6));self.assertIn(Keyword.TAUNT,token.keywords);self.assertIn('demon',g.registry.card(DEMON).metadata.tribes);self.portable(g)

 def test_f3_inventor_two_exact_taunt_shield_mechs_and_physical_capacity(self):
  for n,expected in((0,2),(5,1),(6,0)):
   g=self.game((INVENTOR,),board=(FILLER,)*n);self.play(g,INVENTOR);self.assertEqual(self.count(g,ANNOY),expected)
   for i in g.state.players[1].board:
    e=g.state.entities[i]
    if e.card_id==ANNOY:self.assertEqual((e.attack,e.health),(1,2));self.assertIn(Keyword.TAUNT,e.keywords);self.assertIn(Keyword.DIVINE_SHIELD,e.keywords)

 def test_z0_full_raw_source_schema_zero_declaration_and_old_content_preserved_before_after_assembly(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['cards']),len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(0,12,1,32));self.assertEqual(d['exact_parent_child_links'],[]);self.assertEqual(len(d['source_tag_links']),3);self.assertEqual(d['numeric_normalizations'],{COIN:{'cost':0}})
  rows={x['record']['id']:x['record']for k in('dependencies','existing_dependencies','evidence_only')for x in d[k]}
  for edge in d['source_tag_links']:self.assertEqual(rows[edge['parent']]['tags'][edge['tag']],rows[edge['child']]['dbf_id']);self.assertEqual(edge['dbf_id'],rows[edge['child']]['dbf_id'])
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'],numeric_normalizations=d['numeric_normalizations'].get(o['card_id']))
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  self.assertTrue(all(cid not in after.cards for cid in('TIME_040',)+DEFERRED))
  with patch(__name__+'.build_registry',lambda:after):self.assertIs(batch_registry(),after)

if __name__=='__main__':unittest.main()
