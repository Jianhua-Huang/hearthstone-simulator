"""Actual Standard roots consume explicit complete host past pools, never infer them."""
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p89_cards as cards
from hs_sim.cards.simple_followup_p89_cards import WO,NEON,MEMORY,WARDEN,GLAIVE,ALTER,WINGS,LORD,REALITY,ROOTS,DEFERRED,PAST_POOL,load_batch,register_simple_followup_p89_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.effects import AddToHand,ChoiceOption,Destroy,InvokeBehavior,RequestChoice,Silence
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.costs import local_cost
from hs_sim.engine.model import AppendageSpec,ChooseBranch,ChooseOneSpec,LimitedTriggerSpec,PaymentType,Runes,SecretSpec,SpellRepeatSpec,SpellSchool
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.interrupts import CounterSpell
from hs_sim.engine.secrets import SetSecret

P='p89.test.'
HERO,FILLER,KILL,SILENCE,NOP,AUTO,UNKNOWN=(P+x for x in('hero','filler','kill','silence','nop','auto','unknown'))
NATURE,MAGE_NATURE,FOREIGN_NATURE,ARCANE,MAGE_ARCANE,FOREIGN_ARCANE,MECH,NEUTRAL_MECH,MAGE_MECH,FIVE,DEMON,DRAGON,COLOSSAL,LIMB,CHOOSE=(P+x for x in('nature','mage-nature','foreign-nature','arcane','mage-arcane','foreign-arcane','paladin-mech','neutral-mech','mage-mech','five','demon','dragon','colossal','limb','choose'))
MEMBERS=(NATURE,MAGE_NATURE,FOREIGN_NATURE,ARCANE,MAGE_ARCANE,FOREIGN_ARCANE,MECH,NEUTRAL_MECH,MAGE_MECH,FIVE,DEMON,DRAGON,COLOSSAL,CHOOSE)
CONTEXT=GenerationContext('p89-explicit-bounded-past','experimental')
REPEAT,COUNTER,SECRET,MISS,MISS_DRIVER,FAILSPELL,FAIL_DRIVER=(P+x for x in('repeat','counter','secret','miss','miss-driver','failspell','fail-driver'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()

def meta(cls=CardClass.NEUTRAL,tribes=(),collectible=True):return CardMetadata(collectible,(cls,),Rarity.COMMON,runes=Runes(),tribes=tribes,factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p89_cards.register_simple_followup_p89_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(i in r.cards for i in ROOTS)
 if not any(present):register_simple_followup_p89_cards(r)
 elif not all(present):raise AssertionError('Complete P89 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r

def registry(members,mode,pool,complete):
 r=Registry('p89-explicit-small-complete-test-host');register_simple_followup_p89_cards(r)
 r.register_behavior(P+'nop',lambda c:())
 r.register_behavior(P+'kill',lambda c:(Destroy(c.target_id,c.source_id),))
 r.register_behavior(P+'silence',lambda c:(Silence(c.target_id),))
 r.register_behavior(P+'auto',lambda c:(CastSpell(c.player_id,NOP,c.source_id),))
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P89 deliberate waiting continuation failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 for cid,school,cls in((NATURE,SpellSchool.NATURE,CardClass.NEUTRAL),(MAGE_NATURE,SpellSchool.NATURE,CardClass.MAGE),(FOREIGN_NATURE,SpellSchool.NATURE,CardClass.WARLOCK),(ARCANE,SpellSchool.ARCANE,CardClass.NEUTRAL),(MAGE_ARCANE,SpellSchool.ARCANE,CardClass.MAGE),(FOREIGN_ARCANE,SpellSchool.ARCANE,CardClass.WARLOCK),(NOP,None,CardClass.NEUTRAL)):
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,cost=3,on_play=P+'nop',spell_school=school,metadata=meta(cls)))
 for cid,cls,tribes,cost,attack,health in((FILLER,CardClass.NEUTRAL,(),1,1,20),(MECH,CardClass.PALADIN,('mech',),2,2,3),(NEUTRAL_MECH,CardClass.NEUTRAL,('mech',),2,1,2),(MAGE_MECH,CardClass.MAGE,('mech',),2,3,4),(FIVE,CardClass.WARLOCK,(),5,4,6),(DEMON,CardClass.WARLOCK,('demon',),2,3,4),(DRAGON,CardClass.NEUTRAL,('dragon',),4,4,5),(LIMB,CardClass.NEUTRAL,(),1,1,1)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=attack,health=health,metadata=meta(cls,tribes,cid!=LIMB),battlecry=P+'nop'if cid==DRAGON else None))
 r.register_card(CardDefinition(COLOSSAL,COLOSSAL,CardType.MINION,cost=8,attack=6,health=6,keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec(LIMB),),metadata=meta(CardClass.WARLOCK)))
 branches=tuple(ChooseBranch(str(i),str(i),P+'nop')for i in range(3))
 r.register_card(CardDefinition(CHOOSE,CHOOSE,CardType.SPELL,cost=4,choose_one=ChooseOneSpec(branches[:2],branches[2]),metadata=meta(CardClass.DRUID)))
 r.register_card(CardDefinition(AUTO,AUTO,CardType.MINION,cost=1,health=3,battlecry=P+'auto',metadata=meta()))
 r.register_card(CardDefinition(REPEAT,REPEAT,CardType.MINION,health=3,spell_repeats=(SpellRepeatSpec(2,class_mode='any'),),metadata=meta()))
 r.register_secret_condition(P+'counter',lambda c:c.window is not None and c.window.kind=='spell'and not c.window.countered)
 r.register_behavior(P+'counter',lambda c:(CounterSpell(c.window.id),))
 r.register_behavior(P+'set-counter',lambda c:(SetSecret(2,SECRET),))
 r.register_card(CardDefinition(SECRET,SECRET,CardType.SPELL,keywords=(Keyword.SECRET,),secret=SecretSpec(SECRET,('card_committed',),P+'counter',P+'counter'),metadata=meta(collectible=False)))
 r.register_card(CardDefinition(COUNTER,COUNTER,CardType.MINION,health=3,battlecry=P+'set-counter',metadata=meta()))
 r.register_card(CardDefinition(MISS,MISS,CardType.SPELL,on_play=P+'nop',targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,),relation='enemy'),metadata=meta()))
 r.register_card(CardDefinition(FAILSPELL,FAILSPELL,CardType.SPELL,on_play=P+'fail',metadata=meta()))
 for cid,spell in((MISS_DRIVER,MISS),(FAIL_DRIVER,FAILSPELL)):
  r.register_behavior(cid,lambda c,spell=spell:(CastSpell(c.player_id,spell,c.source_id),));r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=1,health=3,battlecry=cid,metadata=meta()))
 for cid,bid in((KILL,P+'kill'),(SILENCE,P+'silence')):
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=bid,targeting=TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,)),metadata=meta()))
 extra={}
 if mode:
  event={'hand':'card_added_to_hand','deck':'card_added_to_deck','removed':'cards_removed_from_game','summon':'minion_summoned','fill':'choice_selected'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='summon':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==FIVE
   return c.event.source_id is not None and c.state.entities[c.event.source_id].card_id in ROOTS
  r.register_trigger_condition(P+'eligible',eligible)
  r.register_behavior(P+'fill',lambda c:(AddToHand(1,FILLER,c.source_id),))
  extra['limited_triggers']=(LimitedTriggerSpec(event,P+'fill'if mode=='fill'else P+'wait',condition_id=P+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,metadata=meta(CardClass.MAGE,collectible=False),**extra))
 for cid in MEMBERS:r.register_pool_card(PoolCard.from_definition(r.card(cid)))
 if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.MINION,5,CardMetadata(True,(CardClass.PALADIN,CardClass.MAGE),Rarity.COMMON,runes=Runes(),tribes=('mech','demon','dragon'),factions=(),subtypes=()),keywords=(Keyword.COLOSSAL,),battlecry=False,deathrattle=False,choose_one=True,attack=4))
 if pool:r.register_pool(PoolDefinition(PAST_POOL,'p89-test-explicit-complete',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(i)for i in members),complete=complete))
 r.validate();return r
@lru_cache(None)
def fixture_registry(members,mode,pool,complete,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Frozen independent registry key required')
 r=registry(members,mode,pool,complete);r.freeze();return r

class SimpleFollowupP89Tests(unittest.TestCase):
 def game(self,hand=(),board=(),deck=(FILLER,)*4,enemy=(),enemy_hand=(),members=MEMBERS,mode=None,pool=True,complete=True,context=CONTEXT,hand_cap=None):
  self.config=(members,mode,pool,complete)
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,hand_cap=hand_cap),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*4,mana=60,max_mana=60,mana_cap=60)),seed=8989,generation_context=context),fixture_registry(*self.config,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key=None):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key or q.options[0].id,)))
 def finish(self,g):
  while g.state.pending_choice:self.choose(g)
 def portable(self,g):
  reader=fixture_registry(*self.config,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',public)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),snap)
 def hand_ids(self,g):return tuple(g.state.entities[i].card_id for i in g.state.players[1].hand)

 def test_a0_all_nine_actual_paid_entries_printed_scalars_and_school(self):
  for cid in ROOTS:
   with self.subTest(cid=cid):
    g=self.game((cid,));mana=g.state.players[1].mana;source=self.play(g,cid);self.finish(g);raw=next(x['record']for x in load_batch()['cards']if x['record']['id']==cid)
    self.assertEqual(mana-g.state.players[1].mana,raw['cost']);self.assertEqual(g.state.play_history[0].card_id,cid)
    if g.state.entities[source].kind==CardType.MINION:self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(raw['attack'],raw['health']))
  self.assertEqual(cards.SCHOOLS[load_batch()['cards'][1]['record']['tags']['SPELL_SCHOOL']],SpellSchool.HOLY)
  self.assertIsNone(fixture_registry(MEMBERS,None,True,True,'writer',SOURCE_PIN).card(WINGS).spell_school)
 def test_b0_wo_completed_own_automatic_and_manual_spells_exclude_minion_and_opponent(self):
  g=self.game((AUTO,FILLER,NOP),board=(WO,),enemy_hand=(AUTO,NOP));wo=self.first(g,WO,'board');self.assertIn(Keyword.ELUSIVE,wo.keywords)
  self.play(g,AUTO);self.assertIsNotNone(g.state.pending_choice);self.assertEqual(g.state.cast_history[-1].origin,'effect');self.assertTrue(g.state.cast_history[-1].completed);self.portable(g);self.choose(g)
  self.play(g,FILLER);self.assertIsNone(g.state.pending_choice);self.play(g,NOP);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g)
  self.assertEqual(sum(cid in(NATURE,MAGE_NATURE)for cid in self.hand_ids(g)),2);g.apply(EndTurn(1));self.play(g,AUTO,pid=2);self.play(g,NOP,pid=2);self.assertIsNone(g.state.pending_choice);self.portable(g)
 def test_b1_wo_after_original_discovery_completes_and_elusive_blocks_enemy_target(self):
  g=self.game((NEON,),board=(WO,),enemy_hand=(KILL,));self.play(g,NEON);first=g.state.pending_choice.id;self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.assertNotEqual(first,g.state.pending_choice.id);self.portable(g);self.choose(g);g.apply(EndTurn(1));snap=g.snapshot()
  with self.assertRaises(IllegalAction):self.play(g,KILL,self.first(g,WO,'board').id,pid=2)
  self.assertEqual(g.snapshot(),snap)
 def test_b2_wo_each_real_hand_repetition_discovers_with_one_original_payment(self):
  g=self.game((NOP,),board=(WO,REPEAT));self.play(g,NOP)
  for count in(1,2):
   self.assertEqual(len(g.state.cast_history),count);self.assertTrue(g.state.cast_history[-1].completed);self.portable(g);self.choose(g)
  self.assertIsNone(g.state.pending_choice);self.assertEqual([r.origin for r in g.state.cast_history],['hand','repeat']);self.assertEqual((g.state.players[1].mana,len(g.state.play_history),len(g.state.players[1].hand)),(57,1,2));self.portable(g)
 def test_b3_wo_countered_spell_has_no_completion_or_discovery(self):
  g=self.game((COUNTER,NOP),board=(WO,));self.play(g,COUNTER);self.play(g,NOP);self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.cast_history[-1].failure,'countered');self.assertFalse(any(e.kind=='spell_cast_finished'for e in g.events));self.assertEqual(self.hand_ids(g),());self.portable(g)
 def test_b4_wo_failed_automatic_target_and_payload_error_cannot_reward(self):
  g=self.game((MISS_DRIVER,),board=(WO,));self.play(g,MISS_DRIVER);self.assertIsNone(g.state.pending_choice);self.assertIsNotNone(g.state.cast_history[-1].failure);self.assertFalse(any(e.kind=='spell_cast_finished'for e in g.events));self.portable(g)
  g=self.game((FAIL_DRIVER,),board=(WO,));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,FAIL_DRIVER)
  self.assertEqual(g.snapshot(),snap)
 def test_c0_neon_paladin_only_and_stats_before_first_acquisition_wait(self):
  g=self.game((NEON,),mode='hand');self.play(g,NEON);self.portable(g);self.choose(g);self.fail_wait(g);e=self.first(g,MECH);self.assertEqual((e.attack,e.health),(7,8));self.assertEqual(self.hand_ids(g),(MECH,));self.choose(g);self.portable(g)
 def test_c1_neon_full_hand_burn_keeps_native_creation_grant(self):
  g=self.game((NEON,),hand_cap=1,mode='fill');self.play(g,NEON);self.choose(g);created=[e for e in g.state.entities.values()if e.card_id==MECH];self.assertEqual(len(created),1);self.assertEqual((created[0].attack,created[0].health),(7,8));self.assertEqual(created[0].zone,Zone.GRAVEYARD)
 def test_d0_memory_original_death_and_silence(self):
  for silenced in(False,True):
   g=self.game((SILENCE,KILL),board=(MEMORY,),members=(FIVE,));source=self.first(g,MEMORY,'board').id
   if silenced:self.play(g,SILENCE,source)
   self.play(g,KILL,source);self.assertEqual(self.hand_ids(g).count(FIVE),0 if silenced else 1);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.portable(g)
 def test_d1_memory_actual_generated_hand_wait_rollback_and_source(self):
  g=self.game((KILL,),board=(MEMORY,),members=(FIVE,),mode='hand');source=self.first(g,MEMORY,'board').id;self.play(g,KILL,source);self.fail_wait(g);self.assertTrue(any(e.kind=='card_added_to_hand'and e.source_id==source for e in g.events));self.choose(g);self.portable(g)
 def test_e0_warden_original_position_native_cause_and_no_battlecry(self):
  g=self.game((KILL,),board=(FILLER,WARDEN,FILLER),members=(FIVE,));source=self.first(g,WARDEN,'board').id;self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords);self.play(g,KILL,source);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[FILLER,FIVE,FILLER]);self.assertEqual(len(g.state.play_history),1);cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.origin,cause.source.card_id,cause.player_id,cause.cast_id),('card_effect',WARDEN,1,None));self.portable(g)
 def test_e1_warden_actual_summon_wait_retains_original_death_cause(self):
  g=self.game((KILL,),board=(WARDEN,),members=(FIVE,),mode='summon');self.play(g,KILL,self.first(g,WARDEN,'board').id);self.fail_wait(g);self.choose(g);self.portable(g)
 def test_f0_glaive_two_real_attacks_break_and_generate_any_class_demon(self):
  g=self.game((GLAIVE,),members=(DEMON,));source=self.play(g,GLAIVE);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].durability),(2,2))
  for i in range(2):
   g.apply(Attack(1,g.state.players[1].hero_id,g.state.players[2].hero_id))
   if i==0:g.apply(EndTurn(1));g.apply(EndTurn(2))
  self.assertIn(DEMON,self.hand_ids(g));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertTrue(any(e.kind=='card_added_to_hand'and e.source_id==source for e in g.events));self.portable(g)
 def test_f1_glaive_real_weapon_replacement_death_uses_retired_source(self):
  g=self.game((GLAIVE,GLAIVE),members=(DEMON,));old=self.play(g,GLAIVE);new=self.play(g,GLAIVE);self.assertNotEqual(old,new);self.assertEqual(self.hand_ids(g),(DEMON,));self.assertEqual(g.state.entities[old].zone,Zone.GRAVEYARD);self.portable(g)
 def test_g0_alter_two_native_choices_each_reduced_before_delivery_once_paid(self):
  g=self.game((ALTER,));self.play(g,ALTER)
  for i in range(2):
   self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g);self.assertEqual(len(g.state.players[1].hand),i+1)
   for eid in g.state.players[1].hand:self.assertIn(g.state.entities[eid].card_id,(ARCANE,MAGE_ARCANE));self.assertEqual(g.quote_cost(eid).amount,1)
  self.assertIsNone(g.state.pending_choice);self.assertEqual((g.state.players[1].mana,len(g.state.play_history)),(56,1));self.portable(g)
 def test_g1_alter_first_acquisition_wait_keeps_second_choice_and_rollback(self):
  g=self.game((ALTER,),mode='hand');self.play(g,ALTER);self.choose(g);self.fail_wait(g);self.assertEqual(g.quote_cost(g.state.players[1].hand[0]).amount,1);self.choose(g);self.assertIsNotNone(g.state.pending_choice);self.portable(g);self.choose(g);self.assertEqual(len(g.state.players[1].hand),2);self.portable(g)
 def test_h0_wings_native_host_dark_gift_pair_is_portable_and_playable(self):
  g=self.game((WINGS,),members=(DRAGON,));self.play(g,WINGS);self.portable(g);self.choose(g);self.assertIsNone(g.state.pending_choice);created=[e for e in g.state.entities.values()if e.card_id==DRAGON];self.assertEqual(len(created),1);self.assertTrue(created[0].enchantments);self.portable(g)
  if created[0].zone==Zone.HAND:self.play(g,DRAGON);self.finish(g);self.portable(g)
 def test_i0_lord_real_colossal_keyword_any_class_no_appendages_until_play(self):
  g=self.game((LORD,),members=(COLOSSAL,FIVE));self.play(g,LORD);self.assertEqual(self.hand_ids(g),(COLOSSAL,));self.assertEqual(len(g.state.players[1].board),1);self.assertFalse(g.state.colossal_history);self.play(g,COLOSSAL);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[LORD,COLOSSAL,LIMB]);self.portable(g)
 def test_j0_reality_replaces_whole_hand_deck_fresh_and_prepriced_no_draw_discard_death(self):
  g=self.game((REALITY,FILLER,NOP),deck=(FILLER,)*3,members=(CHOOSE,));old=tuple(g.state.players[1].hand[1:])+tuple(g.state.players[1].deck);source=self.play(g,REALITY)
  self.assertEqual((len(g.state.players[1].hand),len(g.state.players[1].deck)),(2,3));self.assertTrue(all(g.state.entities[i].zone==Zone.SETASIDE for i in old));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
  for eid in(*g.state.players[1].hand,*g.state.players[1].deck):self.assertEqual((g.state.entities[eid].card_id,local_cost(g.state.entities[eid])),(CHOOSE,(3,PaymentType.MANA)))
  self.assertFalse(g.state.draw_history);self.assertFalse(g.state.death_history);self.assertFalse(any(e.kind in('card_discarded','deck_card_destroyed')for e in g.events));self.assertEqual(sum(e.kind=='cards_removed_from_game'for e in g.events),1);self.portable(g)
 def test_j1_reality_removal_and_delivery_native_waits_restore_atomic_count(self):
  for mode in('removed','hand','deck'):
   g=self.game((REALITY,FILLER),deck=(FILLER,)*2,members=(CHOOSE,),mode=mode);self.play(g,REALITY);self.fail_wait(g)
   for eid in(*g.state.players[1].hand,*g.state.players[1].deck):self.assertEqual((g.state.entities[eid].card_id,local_cost(g.state.entities[eid])),(CHOOSE,(3,PaymentType.MANA)))
   self.choose(g);self.assertEqual((len(g.state.players[1].hand),len(g.state.players[1].deck)),(1,2));self.portable(g)
 def test_j2_reality_empty_hand_deck_no_fake_output_or_rng(self):
  g=self.game((REALITY,),deck=(),members=(CHOOSE,));rng=g.snapshot()['rng_state'];self.play(g,REALITY);self.assertEqual((g.state.players[1].hand,g.state.players[1].deck),([],[]));self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_k0_missing_context_pool_incomplete_and_unknown_fail_entire_paid_action(self):
  for cid in(NEON,WINGS,LORD,REALITY):
   for config in({'context':None},{'pool':False},{'context':GenerationContext('p89-wrong-target','experimental')},{'members':(UNKNOWN,)}):
    with self.subTest(card=cid,config=config):
     g=self.game((cid,FILLER),**config);snap=g.snapshot()
     with self.assertRaises((ResolutionError,ValueError)):self.play(g,cid)
     self.assertEqual(g.snapshot(),snap)
  for mode in('standard','wild'):
   with self.assertRaises(ValueError):PoolDefinition(PAST_POOL,'p89-incomplete-formal',CONTEXT.target_id,mode,(),complete=False)
 def test_k1_death_unknown_pool_rolls_back_original_death_payment_and_rng(self):
  for cid in(MEMORY,WARDEN):
   g=self.game((KILL,),board=(cid,),members=(UNKNOWN,));snap=g.snapshot()
   with self.assertRaises((ResolutionError,ValueError)):self.play(g,KILL,self.first(g,cid,'board').id)
   self.assertEqual(g.snapshot(),snap)
 def test_z0_full_sources_four_whole_gaps_and_old_registry_preservation(self):
  d=load_batch();self.assertEqual((len(d['cards']),len(d['evidence_only']),len(d['official_observations'])),(9,4,26));self.assertEqual(tuple(x['record']['id']for x in d['evidence_only']),DEFERRED);r0=baseline_registry();r1=batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),9);self.assertTrue(all(i not in r1.cards for i in DEFERRED));self.assertNotIn(PAST_POOL,r1.pools)
  self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
