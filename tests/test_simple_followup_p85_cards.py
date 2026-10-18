"""Full historical declarations through original native callbacks and real actions."""
from dataclasses import asdict,replace
from functools import lru_cache
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p85_cards as cards
from hs_sim.cards.simple_followup_p85_cards import (ANSHE,BRUTE,FINJA,TIGER,EARTH,GRIZZLY,CURATOR,BOOMKIN,CLEANER,THRESHER,ROOTS,load_batch,register_simple_followup_p85_cards)
from hs_sim.cards import basic_trigger_cards as basic,simple_battlecry_cards as simple,physical_zone_cards as physical,economy_cards as economy,conditional_cards as conditional
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,DeckPolicy,DeckSpec,EndTurn,Game,IllegalAction,Keyword,MatchSetup,OpeningHook,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeManaCrystals,ChoiceOption,Damage,Destroy,Draw,Heal,InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,HealingKind,LimitedTriggerSpec,Runes
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.cross_zone import TransformStoredCard
from hs_sim.engine.zones import AddToDeck,CardReference,MoveCard

TEST='p85.test.'
HERO,HP,FILLER,BEAST,DRAGON,MURLOC,UNKNOWN,TINY,LETHAL,BOTH,BOOT=(TEST+i for i in('hero','power','filler','beast','dragon','murloc','unknown','tiny','lethal','both','boot'))
NOP,HIT,HEAL,KILL,SILENCE,RECRUIT,ADD,CHANGE,FOREIGN=(TEST+i for i in('nop','hit','heal','kill','silence','recruit','add','change','foreign'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=(),collectible=False):return CardMetadata(collectible,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p85_cards(r)
 elif not all(present):raise AssertionError('Complete P85 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(maxsize=1)
def original_fixture_sources():
 r=build_registry();ids=('CORE_'+TIGER,'CORE_'+THRESHER,'CORE_'+FINJA,'CS2_101t','GAME_005')
 bodies=('cards.attack_followups.finja',r.card('GAME_005').on_play)
 assert all(not r.behavior(k).__code__.co_freevars for k in bodies)
 return tuple(r.card(i)for i in ids),tuple((k,r.behavior(k))for k in bodies)
def registry(mode):
 r=Registry('p85-small-original-callbacks');definitions,bodies=original_fixture_sources()
 for d in definitions:r.register_card(d)
 for k,body in bodies:r.register_behavior(k,body)
 # The original registration functions bind their unchanged callbacks to this registry.
 for module,ids,register in((basic,('CORE_'+ANSHE,'CORE_'+BRUTE),basic.register_basic_trigger_cards),(simple,('CORE_'+GRIZZLY,),simple.register_simple_battlecry_cards),(physical,('CORE_'+CLEANER,),physical.register_physical_zone_cards),(economy,('CORE_'+EARTH,'CORE_'+CURATOR),economy.register_economy_cards),(conditional,('CORE_'+BOOMKIN,),conditional.register_conditional_cards)):
  data=module.load_batch();subset=dict(data,cards=[x for x in data['cards']if x['record']['id']in ids])
  with patch.object(module,'load_batch',return_value=subset):register(r)
 register_simple_followup_p85_cards(r)
 for cid,tribes,atk,hp in((FILLER,(),1,12),(BEAST,('beast',),1,12),(DRAGON,('dragon',),1,12),(MURLOC,('murloc',),1,12),(UNKNOWN,None,1,12),(TINY,(),1,2),(LETHAL,(),7,3)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,attack=atk,health=hp,metadata=meta(tribes,collectible=cid==FILLER)))
 r.register_card(CardDefinition(BOTH,BOTH,CardType.MINION,health=5,choose_both=True,metadata=meta()))
 def fail(c):raise ResolutionError('P85 deliberate continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def wait(c):
  change=()
  if mode=='recruit':
   source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==FINJA);change=(Destroy(source,c.source_id),)
  elif mode=='grizzly':change=(Draw(2,source_id=c.source_id),)
  elif mode=='tutor':
   dragon=next(c.state.entities[i]for i in c.state.players[1].deck if c.state.entities[i].card_id==DRAGON)
   change=(MoveCard(CardReference.capture(dragon),1,Zone.HAND,source_id=c.source_id),)
  elif mode=='boom':change=(Summon(1,BOTH),)
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change current state',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 def original(c):
  ids=set(c.state.opening.original_entities[0]);return next(c.state.entities[i]for i in c.state.players[1].deck if i in ids and c.state.entities[i].card_id==FILLER)
 scripts={NOP:lambda c:(),HIT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.EFFECT),),HEAL:lambda c:(Heal(c.target_id,8,c.source_id,HealingKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),RECRUIT:lambda c:(Summon(c.player_id,EARTH),),ADD:lambda c:tuple(AddToDeck(pid,FILLER,'bottom',c.source_id)for pid in(1,2)),CHANGE:lambda c:(TransformStoredCard(CardReference.capture(original(c)),FILLER,c.source_id),),FOREIGN:lambda c:(MoveCard(CardReference.capture(original(c)),2,Zone.DECK,'bottom',source_id=c.source_id),)}
 for cid,body in scripts.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec()if cid in(HIT,HEAL,KILL,SILENCE)else None,metadata=meta()))
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,on_use=NOP,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='cleaner':return True
   if mode=='tutor':return c.event.player_id==1
   eid=c.event.target_id if mode in('recruit','grizzly')else c.event.source_id
   return eid is not None and c.state.entities[eid].card_id in((MURLOC,)if mode=='recruit'else(GRIZZLY,)if mode=='grizzly'else(BOOMKIN,))
  event='card_destroyed_in_deck'if mode=='cleaner'else'card_drawn'if mode=='tutor'else'card_committed'if mode=='boom'else'minion_summoned'
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra))
 def boot(c):return(ChangeManaCrystals(c.player_id,40,filled=True),*(AddToHand(c.player_id,cid,c.source_id)for cid in(CLEANER,ADD,CHANGE,FOREIGN)))
 r.register_behavior(TEST+'boot',boot);r.register_card(CardDefinition(BOOT,BOOT,CardType.MINION,health=1,opening_hooks=(OpeningHook('after_mulligan',TEST+'boot'),),metadata=meta(collectible=True)))
 r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP85Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),deck=(FILLER,)*8,enemy_hand=(),mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*8,mana=50,max_mana=50,mana_cap=50,hero_power_card_id=HP)),seed=8585),fixture_registry(mode,'writer',SOURCE_PIN))
 def match(self,mode=None):
  self.mode=mode;r=fixture_registry(mode,'writer',SOURCE_PIN);policy=DeckPolicy(TEST+'policy','p85-fixed','experimental',(BOOT,FILLER),deck_size=12,max_copies=12)
  g=Game.from_decks(MatchSetup(tuple(DeckSpec(HERO,HP,CardClass.MAGE,(BOOT,)+(FILLER,)*11)for _ in(1,2)),policy,'GAME_005',seed=85,first_player=1),r)
  while g.state.pending_choice:q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,()))
  return g
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1,branch=None):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None,branch_id=branch));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','original_entities','face_replaced','behavior_id'):self.assertNotIn('"'+key+'"',public)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),snap)
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(g.snapshot(),snap)
 def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health

 def test_a0_all_ten_actual_paid_entries_and_complete_declarations(self):
  for cid in ROOTS:
   if cid==CLEANER:g=self.match()
   else:g=self.game((cid,))
   before=g.state.players[1].mana;eid=self.play(g,cid,branch='first'if cid==BOOMKIN else None)
   e=g.state.entities[eid];raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid)
   self.assertEqual((e.card_id,e.attack,e.health),(cid,raw['attack'],raw['health']));self.assertEqual(before-g.state.players[1].mana,5)
   self.assertEqual(g.state.play_history[-1].card_id,cid)
 def test_b0_anshe_zero_positive_enemy_restoration_and_previous_turn(self):
  for damaged,old in((False,False),(True,False),(True,True)):
   g=self.game((HIT,HEAL,ANSHE),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id
   if damaged:self.play(g,HIT,target)
   self.play(g,HEAL,target)
   if old:self.next_own(g)
   eid=self.play(g,ANSHE);self.assertEqual(g.state.entities[eid].attack,8 if damaged and not old else 5)
 def test_c0_brute_original_surviving_and_lethal_defense_damage_all_enemies(self):
  for attacker in(FILLER,LETHAL):
   g=self.game(board=(attacker,FILLER),enemy=(BRUTE,));brute=self.first(g,BRUTE,'board',2).id;source=g.state.players[1].board[0]
   g.apply(Attack(1,source,brute));self.assertEqual(self.hp(g),29);self.assertEqual(g.state.entities[g.state.players[1].board[-1]].health,11)
   rows=[x for x in g.state.damage_history if x.health_result.damage_kind=='minion_ability'];self.assertTrue(rows);self.assertTrue(all(x.health_result.source_id==brute for x in rows))
 def test_c1_brute_own_attack_and_silenced_defense_do_not_ping(self):
  g=self.game(board=(BRUTE,));g.apply(Attack(1,self.first(g,BRUTE,'board').id,g.state.players[2].hero_id));self.assertEqual(self.hp(g,2),27)
  g=self.game((SILENCE,),board=(FILLER,),enemy=(BRUTE,));self.play(g,SILENCE,self.first(g,BRUTE,'board',2).id);g.apply(Attack(1,self.first(g,FILLER,'board').id,self.first(g,BRUTE,'board',2).id));self.assertEqual(self.hp(g),30)
 def test_d0_finja_kill_recruits_original_two_physical_murlocs_without_battlecry(self):
  g=self.game(board=(FINJA,),enemy=(TINY,),deck=(FILLER,MURLOC,MURLOC));original=set(g.state.players[1].deck[1:]);eid=self.first(g,FINJA,'board').id
  g.apply(Attack(1,eid,self.first(g,TINY,'board',2).id));self.assertTrue(original<=set(g.state.players[1].board));self.assertNotIn(Keyword.STEALTH,g.state.entities[eid].keywords);self.assertFalse(g.state.battlecry_history);self.portable(g)
 def test_d1_finja_nonlethal_and_mutual_lethal_do_not_recruit(self):
  for target in(FILLER,LETHAL):
   g=self.game(board=(FINJA,),enemy=(target,),deck=(MURLOC,MURLOC));g.apply(Attack(1,self.first(g,FINJA,'board').id,self.first(g,target,'board',2).id));self.assertEqual(len(g.state.players[1].deck),2)
 def test_d2_finja_real_first_recruit_wait_keeps_accepted_plan_after_source_death(self):
  g=self.game(board=(FINJA,),enemy=(TINY,),deck=(MURLOC,MURLOC),mode='recruit');eid=self.first(g,FINJA,'board').id;g.apply(Attack(1,eid,self.first(g,TINY,'board',2).id));self.fail_wait(g);self.choose(g,'change')
  self.assertEqual(g.state.entities[eid].zone,Zone.GRAVEYARD);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[MURLOC,MURLOC]);self.portable(g)
 def test_e0_tiger_stealth_is_native_target_and_attack_policy(self):
  g=self.game(board=(TIGER,),enemy=(FILLER,));eid=self.first(g,TIGER,'board').id;self.assertIn(Keyword.STEALTH,g.state.entities[eid].keywords);g.apply(Attack(1,eid,g.state.players[2].hero_id));self.assertNotIn(Keyword.STEALTH,g.state.entities[eid].keywords);self.assertEqual(self.hp(g,2),25)
 def test_f0_earth_paid_on_play_overload_two_and_next_turn_lock(self):
  g=self.game((EARTH,));eid=self.play(g,EARTH);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(7,9));self.assertEqual(g.state.players[1].overload_owed,2);self.assertFalse(g.state.battlecry_history);self.next_own(g);self.assertEqual((g.state.players[1].overload_locked,g.state.players[1].overload_owed,g.state.players[1].mana),(2,0,48));self.portable(g)
 def test_f1_earth_actual_summon_does_not_execute_on_play(self):
  g=self.game((RECRUIT,));self.play(g,RECRUIT);self.assertEqual(self.first(g,EARTH,'board').health,9);self.assertFalse(g.state.overload_history);self.assertEqual(g.state.players[1].overload_owed,0)
 def test_g0_grizzly_health_adjustment_is_not_damage_and_silence_removes(self):
  g=self.game((GRIZZLY,SILENCE),enemy_hand=(FILLER,)*3);eid=self.play(g,GRIZZLY);self.assertEqual(g.state.entities[eid].health,9);self.assertFalse(g.state.damage_history);self.play(g,SILENCE,eid);self.assertEqual(g.state.entities[eid].health,12)
 def test_g1_grizzly_actual_summon_wait_uses_fresh_opponent_hand(self):
  g=self.game((GRIZZLY,),enemy_hand=(FILLER,),mode='grizzly');eid=self.play(g,GRIZZLY);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[eid].health,10);self.portable(g)
 def test_h0_curator_sequential_original_physical_tribe_draws(self):
  g=self.game((CURATOR,),deck=(FILLER,BEAST,DRAGON,MURLOC));ids=tuple(g.state.players[1].deck[1:]);self.play(g,CURATOR);self.assertEqual(tuple(g.state.players[1].hand),ids);self.assertEqual([x.card_id for x in g.state.draw_history],[BEAST,DRAGON,MURLOC]);self.portable(g)
 def test_h1_curator_first_draw_wait_requeries_deck_for_next_tribe(self):
  g=self.game((CURATOR,),deck=(BEAST,DRAGON,MURLOC),mode='tutor');self.play(g,CURATOR);self.fail_wait(g);self.choose(g,'change');self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[BEAST,DRAGON,MURLOC]);self.assertEqual(len(g.state.draw_history),2);self.portable(g)
 def test_h2_curator_unknown_deck_tribes_fail_without_partial_payment_or_draw(self):
  g=self.game((CURATOR,),deck=(UNKNOWN,));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,CURATOR)
  self.assertEqual(g.snapshot(),snap)
 def test_i0_boomkin_complete_two_branches_and_combined_pay_once(self):
  for branch,both in(('first',False),('second',False),('both',True)):
   g=self.game((HIT,BOOMKIN),board=(BOTH,)if both else());self.play(g,HIT,g.state.players[1].hero_id);before=g.state.players[1].mana;self.play(g,BOOMKIN,g.state.players[2].hero_id if branch!='first'else None,branch=branch)
   self.assertEqual(self.hp(g),28 if branch=='second'else 30);self.assertEqual(self.hp(g,2),30 if branch=='first'else 26);self.assertEqual(before-g.state.players[1].mana,5);self.assertEqual(len(g.state.play_history),2)
 def test_i1_boomkin_native_branch_target_validation_and_commit_wait(self):
  g=self.game((BOOMKIN,),mode='boom');e=self.first(g,BOOMKIN);self.denied(g,PlayCard(1,e.id,branch_id='second'));self.denied(g,PlayCard(1,e.id,g.state.players[2].hero_id,branch_id='first'))
  self.play(g,BOOMKIN,branch='first');self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.hp(g,2),30);self.assertEqual(self.first(g,BOOMKIN,'board').health,5);self.portable(g)
 def test_j0_cleaner_missing_opening_facts_fails_and_rolls_back(self):
  g=self.game((CLEANER,));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,CLEANER)
  self.assertEqual(g.snapshot(),snap)
 def test_j1_cleaner_real_opening_preserves_original_transfer_and_destroys_new_both_decks(self):
  g=self.match();self.play(g,FOREIGN);originals={i for group in g.state.opening.original_entities for i in group};self.play(g,ADD);new={i for pid in(1,2)for i in g.state.players[pid].deck if i not in originals};self.assertEqual(len(new),2);self.play(g,CLEANER)
  self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in new));self.assertTrue(all(i in originals for pid in(1,2)for i in g.state.players[pid].deck));self.assertFalse(g.state.death_history);self.portable(g)
 def test_j2_cleaner_same_face_transform_loses_credit_and_real_destroy_wait(self):
  g=self.match(mode='cleaner');before=set(g.state.players[1].deck);self.play(g,CHANGE);changed={i for i in before if g.state.entities[i].face_replaced};self.assertEqual(len(changed),1);self.play(g,CLEANER);self.fail_wait(g);self.choose(g);self.assertTrue(all(g.state.entities[i].zone==Zone.GRAVEYARD for i in changed));self.portable(g)
 def test_k0_thresher_native_cleave_hits_only_defender_neighbors_and_one_retaliation(self):
  g=self.game(board=(THRESHER,),enemy=(FILLER,)*4);ids=list(g.state.players[2].board);source=self.first(g,THRESHER,'board').id;g.apply(Attack(1,source,ids[1]));self.assertEqual([g.state.entities[i].damage for i in ids],[4,4,4,0]);self.assertEqual(g.state.entities[source].damage,1);self.assertEqual(g.state.entities[source].attacks_this_turn,1);self.portable(g)
 def test_z0_full_raw_alias_declarations_and_existing_content_exact(self):
  d=load_batch();self.assertEqual(len(d['dependencies']),10);self.assertEqual(len(d['official_observations']),42);self.assertFalse(d['cards']);self.assertFalse(d['exact_parent_child_links']);self.assertFalse(d['source_tag_links']);r0=build_registry();r1=batch_registry()
  for x in d['dependencies']:
   raw=x['record'];source=d['reviewed_declaration_aliases'][raw['id']];self.assertEqual(r1.card(raw['id']),replace(r0.card(source),id=raw['id'],name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw)))
  self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
  self.assertEqual(len(r1.cards)-len(r0.cards),10)
