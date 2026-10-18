"""Original named death rewards, conditional current copies and actual awakening."""
from dataclasses import replace
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p84_cards as cards
from hs_sim.cards.simple_followup_p84_cards import (BELCHER,WHITE,DIREHORN,SORIDORMI,ROC,BLACKWING,OMEGA,ELITE,SLIME,STORM,MATRIARCH,ROOTS,PREFIX,load_batch,register_simple_followup_p84_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,Zone)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.cross_zone import BuffMinionsInZones,MinionScope
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,Draw,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.hero_attack_history import hero_attack_count
from hs_sim.engine.model import DamageKind,HeroAttackQuery,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.summon_quantities import SummonCause
from hs_sim.engine.tribes import ChangeMinionTribes,has_any_tribe
from hs_sim.engine.zones import CardReference

TEST='p84.test.'
HERO,HP,FILLER,DRAGON,ALL,UNKNOWN,DORMANT,LOCATION=(TEST+i for i in('hero','power','filler','dragon','all','unknown','dormant','location'))
NOP,KILL,SILENCE,TAKE,BUFF,HAND_BUFF,HERO_BUFF,BARE,DRAW,BOUNCE,TO_DRAGON,TO_BEAST=(TEST+i for i in('nop','kill','silence','take','buff','hand-buff','hero-buff','bare','draw','bounce','to-dragon','to-beast'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p84_cards(r)
 elif not all(present):raise AssertionError('P84 complete assigned assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(maxsize=1)
def original_fixture_source():
 r=build_registry();card=r.card('WON_329');handler=r.target_rule(card.target_rule)
 assert not handler.__code__.co_freevars
 return card,r.player_target_rule(card.target_rule),handler
def registry(mode):
 r=Registry('p84-small-native-fixtures');original,spec,handler=original_fixture_source();r.register_player_target_rule(spec,handler)
 def old_blackwing(c):
  held=any(c.state.entities[i].kind==CardType.MINION and has_any_tribe(r,c.state.entities[i],('dragon',))for i in c.state.players[c.player_id].hand if i!=c.source_id)
  return(Damage(c.target_id,5,c.source_id,DamageKind.MINION_ABILITY),)if c.target_id is not None and held else()
 r.register_behavior(original.battlecry,old_blackwing);r.register_card(original);register_simple_followup_p84_cards(r)
 r.register_behavior(NOP,lambda c:())
 for cid,cost,tribes,extra in((FILLER,4,(),{}),(DRAGON,7,('dragon',),{}),(ALL,7,('all',),{}),(UNKNOWN,4,None,{}),(DORMANT,4,(),{'dormant_turns':2})):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=12,metadata=meta(tribes),**extra))
 r.register_card(CardDefinition(LOCATION,LOCATION,CardType.LOCATION,cost=3,durability=2,on_use=NOP,metadata=meta()))
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=NOP,metadata=meta()))
 def fail(c):raise ResolutionError('P84 deliberate continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def reenter(c):
  e=c.state.entities[c.target_id];return(SummonStoredCard(CardReference.capture(e),e.controller,cause=SummonCause.capture(c)),)
 r.register_behavior(TEST+'reenter',reenter)
 def wait(c):
  change=()
  if mode=='copy':
   original_id=dict(c.event.data)['copied_from'];change=(ReturnToHand(original_id),InvokeBehavior(TEST+'reenter',c.source_id,1,original_id))
  elif mode=='awake':change=(Destroy(c.event.target_id,c.source_id),AddToHand(1,DRAGON,c.source_id))
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original source',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),BUFF:lambda c:(Buff(c.target_id,3,2,c.source_id),),
  HAND_BUFF:lambda c:(BuffMinionsInZones(c.player_id,2,3,MinionScope((Zone.HAND,)),c.source_id),),HERO_BUFF:lambda c:(Buff(c.state.players[c.player_id].hero_id,attack=3,source_id=c.source_id,expires_turn=c.state.turn),),
  BARE:lambda c:(Damage(c.state.players[3-c.player_id].hero_id,3,c.state.players[c.player_id].hero_id,DamageKind.EFFECT),),DRAW:lambda c:(Draw(c.player_id,source_id=c.source_id),),BOUNCE:lambda c:(ReturnToHand(c.target_id),)}
 for cid,tribe in((TO_DRAGON,'dragon'),(TO_BEAST,'beast')):scripts[cid]=lambda c,tribe=tribe:(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',(tribe,)),c.source_id),)
 for cid,body in scripts.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid in(TO_DRAGON,TO_BEAST)else None if cid in(HAND_BUFF,HERO_BUFF,BARE,DRAW)else TargetSpec(),metadata=meta()))
 r.register_card(CardDefinition(NOP,NOP,CardType.SPELL,on_play=NOP,metadata=meta()))
 extra={}
 if mode is not None:
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='copy':return dict(c.event.data).get('copied_from')is not None and c.state.entities[c.event.source_id].card_id in(OMEGA,ELITE)
   if mode=='awake':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==SORIDORMI
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in(BELCHER,WHITE,DIREHORN)
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec('minion_summoned'if mode=='copy'else'minion_awakened'if mode=='awake'else'minion_died',TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP84Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,crystals=60,mana=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=crystals if mana is None else mana,max_mana=crystals,mana_cap=60,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8484),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def count(self,g,cid,zone='board',pid=1):return sum(g.state.entities[i].card_id==cid for i in getattr(g.state.players[pid],zone))
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

 def test_a0_all_eleven_actual_paid_entries_stats_tokens_and_native_keywords(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,));source=self.play(g,cid);raw=rows[cid];e=g.state.entities[source];self.assertEqual((e.attack,e.health),(raw['attack'],raw['health']));self.assertEqual(g.state.players[1].mana,60-raw['cost'])
   if cid in(BELCHER,WHITE,DIREHORN,ELITE,SLIME,STORM,MATRIARCH):self.assertIn(Keyword.TAUNT,e.keywords)
   if cid==SORIDORMI:self.assertEqual(e.dormancy.remaining_turns,2)

 def test_b0_belcher_actual_death_summons_exact_slime_at_original_slot(self):
  g=self.game((BELCHER,KILL),board=(FILLER,));source=self.play(g,BELCHER);self.play(g,KILL,source);slime=self.first(g,SLIME,'board');self.assertEqual((slime.attack,slime.health),(1,2));self.assertEqual(g.state.players[1].board[-1],slime.id);self.assertIn(Keyword.TAUNT,slime.keywords);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)

 def test_b1_two_actual_death_shuffles_create_exact_fresh_tokens_and_one_semantic_operation(self):
  for cid,token,stats in((WHITE,STORM,(10,10)),(DIREHORN,MATRIARCH,(8,12))):
   g=self.game((cid,BUFF,KILL));source=self.play(g,cid);self.play(g,BUFF,source);old=len(g.state.players[1].deck);self.play(g,KILL,source);e=self.first(g,token,'deck');self.assertNotEqual(e.id,source);self.assertEqual((e.attack,e.health),stats);self.assertIn(Keyword.TAUNT,e.keywords);self.assertEqual(len(g.state.players[1].deck),old+1);self.assertEqual(len(g.state.deck_shuffle_history),1);self.assertEqual(g.state.deck_shuffle_history[0].first_card.entity_id,e.id);self.portable(g)

 def test_b2_death_rewards_silence_and_captured_controller_not_original_owner(self):
  for cid in(BELCHER,WHITE,DIREHORN):
   g=self.game((cid,SILENCE,KILL));source=self.play(g,cid);self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertEqual(g.state.players[1].board,[]);self.assertEqual(len(g.state.deck_shuffle_history),0)
  g=self.game((WHITE,TAKE),enemy_hand=(KILL,));source=self.play(g,WHITE);self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,KILL,source,pid=2);self.assertEqual(self.count(g,STORM,'deck',1),0);self.assertEqual(self.count(g,STORM,'deck',2),1);self.assertEqual(g.state.deck_shuffle_history[-1].player_id,2)

 def test_b3_dead_source_reward_wait_restores_and_resumes_original_shuffle_once(self):
  g=self.game((DIREHORN,KILL),mode='death');source=self.play(g,DIREHORN);self.play(g,KILL,source);self.fail_wait(g);self.choose(g);self.assertEqual(self.count(g,MATRIARCH,'deck'),1);self.assertEqual(len(g.state.deck_shuffle_history),1);self.portable(g)

 def test_c0_omega_uses_actual_crystal_threshold_not_spendable_mana(self):
  for crystals,mana,expected in((9,9,1),(10,5,3),(11,5,3)):
   g=self.game((OMEGA,),crystals=crystals,mana=mana);self.play(g,OMEGA);self.assertEqual(self.count(g,OMEGA),expected);self.assertEqual(g.state.players[1].mana,mana-5)

 def test_c1_omega_copies_full_current_hand_buffs_and_respects_capacity(self):
  g=self.game((HAND_BUFF,OMEGA));self.play(g,HAND_BUFF);self.play(g,OMEGA);self.assertEqual(self.count(g,OMEGA),3);self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(6,8)for i in g.state.players[1].board));self.portable(g)
  for n,expected in((5,2),(6,1)):
   g=self.game((OMEGA,),board=(FILLER,)*n);self.play(g,OMEGA);self.assertEqual(self.count(g,OMEGA),expected);self.assertEqual(len(g.state.players[1].board),7)

 def test_c2_original_copy_residence_is_not_borrowed_after_first_entry_wait_and_return(self):
  g=self.game((OMEGA,),mode='copy');source=self.play(g,OMEGA);self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.count(g,OMEGA),2);self.assertIn(source,g.state.players[1].board);self.portable(g)

 def test_d0_elite_requires_original_completed_hero_attack_and_copies_current_material(self):
  g=self.game((HERO_BUFF,HAND_BUFF,ELITE));self.play(g,HERO_BUFF);self.play(g,HAND_BUFF);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.assertEqual(hero_attack_count(g.state,1,HeroAttackQuery(window='owner_turn')),1);self.play(g,ELITE);self.assertEqual(self.count(g,ELITE),2);self.assertTrue(all((g.state.entities[i].attack,g.state.entities[i].health)==(6,7)for i in g.state.players[1].board));self.portable(g)

 def test_d1_elite_ignores_attack_stat_bare_hero_damage_minion_attacks_and_previous_turn(self):
  for op in(HERO_BUFF,BARE):
   g=self.game((op,ELITE));self.play(g,op);self.play(g,ELITE);self.assertEqual(self.count(g,ELITE),1)
  g=self.game((ELITE,),board=(FILLER,),enemy=(FILLER,));g.apply(Attack(1,self.first(g,FILLER,'board').id,self.first(g,FILLER,'board',2).id));self.play(g,ELITE);self.assertEqual(self.count(g,ELITE),1)
  g=self.game((HERO_BUFF,ELITE));self.play(g,HERO_BUFF);g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id));self.next_own(g);self.play(g,ELITE);self.assertEqual(self.count(g,ELITE),1)

 def test_d2_elite_does_not_borrow_opponent_hero_attack(self):
  g=self.game((ELITE,),enemy_hand=(HERO_BUFF,));g.apply(EndTurn(1));self.play(g,HERO_BUFF,pid=2);g.apply(Attack(2,g.state.players[2].hero_id,g.state.players[1].hero_id));g.apply(EndTurn(2));self.play(g,ELITE);self.assertEqual(self.count(g,ELITE),1)

 def test_e0_soridormi_real_two_owner_starts_awaken_same_entity_and_discount_only_current_dragons(self):
  g=self.game((SORIDORMI,DRAGON,ALL,FILLER));source=self.play(g,SORIDORMI);dragon=self.first(g,DRAGON).id;all_id=self.first(g,ALL).id;filler=self.first(g,FILLER).id;self.next_own(g);self.assertEqual(g.state.entities[source].dormancy.remaining_turns,1);self.assertEqual(g.state.entities[dragon].cost,7);self.next_own(g);self.assertIsNone(g.state.entities[source].dormancy);self.assertEqual((g.state.entities[dragon].cost,g.state.entities[all_id].cost,g.state.entities[filler].cost),(3,3,4));self.assertEqual(sum(e.kind=='minion_awakened'for e in g.events),1);self.portable(g)

 def test_e1_awakening_uses_current_changed_hand_tribes_and_floor_zero(self):
  g=self.game((SORIDORMI,FILLER,DRAGON,TO_DRAGON,TO_BEAST));source=self.play(g,SORIDORMI);filler=self.first(g,FILLER).id;dragon=self.first(g,DRAGON).id;self.play(g,TO_DRAGON,filler);self.play(g,TO_BEAST,dragon);self.next_own(g);self.next_own(g);self.assertEqual((g.state.entities[filler].cost,g.state.entities[dragon].cost),(0,7))

 def test_e2_accepted_awakening_wait_refreshes_hand_and_reward_survives_source_death(self):
  g=self.game((SORIDORMI,DRAGON),mode='awake');source=self.play(g,SORIDORMI);self.next_own(g);self.next_own(g);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);dragons=[g.state.entities[i]for i in g.state.players[1].hand if g.state.entities[i].card_id==DRAGON];self.assertEqual(len(dragons),2);self.assertTrue(all(e.cost==3 for e in dragons));self.portable(g)

 def test_e3_awakening_unknown_current_hand_tribes_roll_back_actual_turn_boundary(self):
  g=self.game((SORIDORMI,UNKNOWN));self.play(g,SORIDORMI);self.next_own(g);g.apply(EndTurn(1));snap=g.snapshot()
  with self.assertRaises(ResolutionError):g.apply(EndTurn(2))
  self.assertEqual(g.snapshot(),snap)

 def test_f0_roc_counts_other_physical_friends_including_dormant_not_location_or_enemy(self):
  for board,enemy,expected in(((FILLER,FILLER),(),True),((FILLER,DORMANT),(),True),((FILLER,LOCATION),(),False),((FILLER,),(FILLER,),False),((),(FILLER,FILLER),False)):
   g=self.game((ROC,),board=board,enemy=enemy);source=self.play(g,ROC);self.assertEqual(Keyword.TAUNT in g.state.entities[source].keywords,expected)

 def test_f1_roc_grant_is_ordinary_permanent_keyword_not_rechecked_aura_and_silence_removes(self):
  g=self.game((ROC,KILL,KILL,SILENCE),board=(FILLER,FILLER));source=self.play(g,ROC)
  for _ in range(2):self.play(g,KILL,self.first(g,FILLER,'board').id)
  self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.play(g,SILENCE,source);self.assertNotIn(Keyword.TAUNT,g.state.entities[source].keywords)

 def test_g0_blackwing_alias_full_declaration_and_actual_full_registry_five_damage(self):
  r=batch_registry();raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==BLACKWING);expected=replace(r.card('WON_329'),id=BLACKWING,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw));self.assertEqual(r.card(BLACKWING),expected)
  g=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=(BLACKWING,'DRG_054'),mana=10,max_mana=10),PlayerSetup('HERO_08')),seed=8485),r);source=g.state.players[1].hand[0];g.apply(PlayCard(1,source,target_id=g.state.players[2].hero_id,position=0));self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,25);self.assertEqual(g.state.players[1].mana,5)

 def test_z0_full_raw_tokens_source_tag_schema_and_all_old_content_preserved(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(11,1,26));self.assertEqual(d['exact_parent_child_links'],[]);self.assertEqual(len(d['source_tag_links']),3)
  rows={x['record']['id']:x['record']for k in('dependencies','existing_dependencies','evidence_only')for x in d[k]}
  for edge in d['source_tag_links']:self.assertEqual(rows[edge['parent']]['tags'][edge['tag']],edge['dbf_id']);self.assertEqual(edge['dbf_id'],rows[edge['child']]['dbf_id'])
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)
  with patch(__name__+'.build_registry',lambda:after):self.assertIs(batch_registry(),after)

if __name__=='__main__':unittest.main()
