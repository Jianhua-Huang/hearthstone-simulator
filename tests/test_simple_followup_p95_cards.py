"""Actual healing/turn sources, full host generation and native death rewards."""
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch
import hashlib,json,unittest
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p95_cards as cards
from hs_sim.cards.simple_followup_p95_cards import BUTTERFLY,DEPTH,WARDEN,PRIESTESS,BALLOON,ZEALOT,BROOM,HATCHLING,BOMBER,VILLAGER,TENTACLE,SHADOW,ROOTS,DEPENDENCIES,ALL_IDS,POOL_ID,load_batch,register_simple_followup_p95_cards
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.engine import Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,Zone
from hs_sim.engine.costs import quote_unselected_cost
from hs_sim.engine.effects import AddToHand,ChangeControl,ChoiceOption,Damage,DamageBatch,Destroy,Heal,HealBatch,InvokeBehavior,RequestChoice,Silence,TriggerDeathrattles
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,HealingKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference
P='p95.test.'
HERO,LOW,FILLER,ONE,POWER,BEAST,ALL,ZERO,KILL,HIT,HEAL,HEAL2,WOUND2,SILENCE,TAKE,TRIGGER,BECOME,REMOVE,HA,HB,NEUTRAL,OTHER,UNCOLLECTIBLE,UNKNOWN=(P+x for x in('hero','low','filler','one','power','beast','all','zero','kill','hit','heal','heal2','wound2','silence','take','trigger','become','remove','hunter_a','hunter_b','neutral','other','uncollectible','unknown'))
MEMBERS=(HA,HB,NEUTRAL,OTHER,UNCOLLECTIBLE,BEAST);CONTEXT=GenerationContext('p95-bounded-complete-host','experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=(),classes=(CardClass.MAGE,),collectible=False):return CardMetadata(collectible,classes,Rarity.COMMON,runes=Runes(),tribes=tribes,factions=(),subtypes=())
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p95_cards.register_simple_followup_p95_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ALL_IDS)
 if not any(present):register_simple_followup_p95_cards(r)
 elif not all(present):raise AssertionError('Complete P95 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode,members):
 r=Registry('p95-small-native');register_simple_followup_p95_cards(r)
 r.register_behavior(P+'fail',lambda c:(_ for _ in()).throw(ResolutionError('P95 deliberate native transaction failure')))
 r.register_behavior(P+'wait',lambda c:(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('fail','Fail',(InvokeBehavior(P+'fail',c.source_id,1),))),c.source_id),))
 r.register_behavior(P+'fill',lambda c:(AddToHand(1,FILLER,c.source_id),))
 def hand(c,cid):return next(c.state.entities[i]for i in c.state.players[c.player_id].hand if c.state.entities[i].card_id==cid)
 def board(c,pid):return next(i for i in c.state.players[pid].board if c.state.entities[i].card_id==FILLER)
 scripts={KILL:lambda c:(Destroy(c.target_id,c.source_id),),HIT:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.SPELL),),HEAL:lambda c:(Heal(c.target_id,3,c.source_id,HealingKind.EFFECT),),
  HEAL2:lambda c:(HealBatch(tuple(Heal(board(c,p),3,c.source_id,HealingKind.EFFECT)for p in(1,2))),),WOUND2:lambda c:(DamageBatch(tuple(Damage(board(c,p),2,c.source_id,DamageKind.SPELL)for p in(1,2))),),
  SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),TRIGGER:lambda c:(TriggerDeathrattles(c.target_id,c.source_id),),
  BECOME:lambda c:(ChangeMinionTribes(CardReference.capture(hand(c,FILLER)),TribeChangeSpec('set',('beast',)),c.source_id),),REMOVE:lambda c:(ChangeMinionTribes(CardReference.capture(hand(c,BEAST)),TribeChangeSpec('remove',('beast',)),c.source_id),)}
 for cid,fn in scripts.items():
  r.register_behavior(cid,fn);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec()if cid==HEAL else TargetSpec(zones=(Zone.BOARD,),kinds=(CardType.MINION,))if cid in(KILL,SILENCE,TAKE,TRIGGER)else TargetSpec()if cid==HIT else None,metadata=meta()))
 for cid,atk,hp,cost,tribes in((FILLER,2,10,2,()),(ONE,1,1,1,()),(BEAST,2,10,2,('beast',)),(ALL,2,10,2,('all',)),(ZERO,1,2,0,('beast',))):r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=atk,health=hp,metadata=meta(tribes,classes=(CardClass.HUNTER,),collectible=True)))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=20,spell_damage=5,metadata=meta()))
 for cid,classes,collectible in((HA,(CardClass.HUNTER,),True),(HB,(CardClass.HUNTER,CardClass.MAGE),True),(NEUTRAL,(CardClass.NEUTRAL,),True),(OTHER,(CardClass.MAGE,),True),(UNCOLLECTIBLE,(CardClass.HUNTER,),False)):
  r.register_behavior(cid,lambda c:());definition=CardDefinition(cid,cid,CardType.SPELL,cost=1,on_play=cid,metadata=meta(classes=classes,collectible=collectible));r.register_card(definition);r.register_pool_card(PoolCard.from_definition(definition))
 r.register_pool_card(PoolCard.from_definition(r.card(BEAST)))
 if members is not None:
  if UNKNOWN in members:r.register_pool_card(PoolCard(UNKNOWN,CardType.SPELL,1,meta(classes=(CardClass.HUNTER,),collectible=True),battlecry=False,deathrattle=False,choose_one=False))
  r.register_pool(PoolDefinition(POOL_ID,'p95-explicit-complete-host',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(i)for i in members),complete=True))
 extra={}
 if mode:
  event={'heal':'stats_changed','damage':'health_resolved','buff':'stats_changed','stored':'stored_card_buffed','grant':'ability_granted','entry':'minion_summoned','hand':'card_added_to_hand','reject':'card_added_to_hand','fill':'card_committed'}[mode]
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='entry':return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id==SHADOW
   if mode in('hand','reject'):return c.event.target_id is not None and c.state.entities[c.event.target_id].card_id in(HA,HB)
   if c.event.source_id is None:return False
   return c.state.entities[c.event.source_id].card_id in((WARDEN,)if mode=='heal'else(BOMBER,DEPTH,TENTACLE)if mode=='damage'else(PRIESTESS,ZEALOT)if mode=='buff'else(HATCHLING,)if mode=='stored'else(BROOM,)if mode=='grant'else(KILL,))
  r.register_trigger_condition(P+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,P+('fill'if mode=='fill'else'fail'if mode=='reject'else'wait'),condition_id=P+'eligible'),)
 for cid,hp in((HERO,100),(LOW,3)):r.register_card(CardDefinition(cid,cid,CardType.HERO,health=hp,metadata=meta(),**extra))
 r.validate();return r
@lru_cache(None)
def fixture_registry(mode,members,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable independent registry key required')
 r=registry(mode,members);r.freeze();return r

class SimpleFollowupP95Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None,members=MEMBERS,hero=HERO,enemy_hero=HERO,seed=9595):
  self.config=(mode,members);return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60),PlayerSetup(enemy_hero,board=enemy,hand=enemy_hand,deck=(FILLER,)*8,mana=60,max_mana=60,mana_cap=60)),seed=seed,generation_context=CONTEXT),fixture_registry(mode,members,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1,position=None):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if position is None and e.kind==CardType.MINION else position));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def cost(self,g,cid,pid=1):return quote_unselected_cost(g.state,g.registry,self.first(g,cid,pid=pid)).amount
 def portable(self,g):
  r=fixture_registry(*self.config,'reader',SOURCE_PIN);self.assertIsNot(r,g.registry);self.assertEqual(r.fingerprint(),g.registry.fingerprint());s=json.loads(json.dumps(g.snapshot()));self.assertEqual(Game.from_snapshot(s,r).snapshot(),s);self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),r).snapshot(),s)
  for pid in(1,2):
   text=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','behavior_id','original_entities','health_result'):self.assertNotIn('"'+key+'"',text)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);s=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),s)
 def test_a0_all_twelve_actual_paid_entries_and_complete_original_metadata(self):
  for item in load_batch()['dependencies']:
   raw=item['record'];cid=raw['id']
   with self.subTest(cid=cid):
    g=self.game((cid,));source=self.play(g,cid);e=g.state.entities[source];self.assertEqual((e.attack,e.max_health,g.state.players[1].mana),(0 if cid==DEPTH else raw['attack'],raw['health'],59));self.assertEqual(g.registry.card(cid).metadata,cards.metadata_from_record(raw));self.assertEqual(g.state.play_history[0].card_id,cid)
 def test_b0_depth_only_owner_start_is_one_minion_ability_batch_including_self(self):
  g=self.game((DEPTH,),board=(FILLER,POWER),enemy=(FILLER,));source=self.play(g,DEPTH);g.apply(EndTurn(1));self.assertFalse(g.state.damage_history);g.apply(EndTurn(2));self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual((self.first(g,FILLER,'board').health,self.first(g,FILLER,'board',2).health),(5,5));self.assertEqual((self.hp(g),self.hp(g,2)),(100,100));rows=g.state.damage_history;self.assertEqual(len(rows),4);self.assertEqual(len({r.health_result.batch_id for r in rows}),1)
  for row in rows:self.assertEqual((row.health_result.source_id,row.health_result.base_amount,row.health_result.spell_bonus,row.health_result.damage_kind),(source,5,0,DamageKind.MINION_ABILITY.value))
  self.portable(g)
 def test_b1_balloon_owner_start_health_buff_does_not_create_healing(self):
  g=self.game((BALLOON,),board=(WARDEN,));source=self.play(g,BALLOON);g.apply(EndTurn(1));self.assertEqual(g.state.entities[source].health,2);g.apply(EndTurn(2));self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(1,3));self.assertEqual(self.first(g,WARDEN,'board').attack,1);self.cycle(g);self.assertEqual(g.state.entities[source].health,4);self.portable(g)
 def test_c0_warden_actual_positive_healing_of_either_hero_or_minion_counts_once(self):
  for kind,pid in(('hero',1),('hero',2),('minion',1),('minion',2)):
   g=self.game((HIT,HEAL,HEAL),board=(WARDEN,FILLER),enemy=(FILLER,));target=g.state.players[pid].hero_id if kind=='hero'else self.first(g,FILLER,'board',pid).id;self.play(g,HIT,target);self.assertEqual(self.first(g,WARDEN,'board').attack,1);self.play(g,HEAL,target);self.assertEqual(self.first(g,WARDEN,'board').attack,3);self.play(g,HEAL,target);self.assertEqual(self.first(g,WARDEN,'board').attack,3)
  self.portable(g)
 def test_c1_warden_enemy_turn_healing_and_self_healing_are_actual_character_facts(self):
  g=self.game((HIT,),board=(WARDEN,),enemy_hand=(HEAL,));source=self.first(g,WARDEN,'board').id;self.play(g,HIT,source);g.apply(EndTurn(1));self.play(g,HEAL,source,pid=2);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(3,2));self.portable(g)
 def test_c2_two_actual_heal_packets_wait_restore_and_do_not_recount_first(self):
  g=self.game((WOUND2,HEAL2),board=(WARDEN,FILLER),enemy=(FILLER,),mode='heal');self.play(g,WOUND2);self.play(g,HEAL2);self.fail_wait(g);self.assertEqual(self.first(g,WARDEN,'board').attack,3);self.choose(g);self.assertEqual(self.first(g,WARDEN,'board').attack,5);self.portable(g)
 def test_d0_priestess_owner_end_excludes_self_and_enemy_and_empty_uses_no_rng(self):
  g=self.game((PRIESTESS,),board=(FILLER,),enemy=(FILLER,));source=self.play(g,PRIESTESS);g.apply(EndTurn(1));self.assertEqual((self.first(g,FILLER,'board').health,self.first(g,FILLER,'board',2).health,g.state.entities[source].health),(11,10,1));g.apply(EndTurn(2));self.assertEqual(self.first(g,FILLER,'board').health,11);self.portable(g)
  g=self.game(board=(PRIESTESS,));rng=g.snapshot()['rng_state'];g.apply(EndTurn(1));self.assertEqual(g.snapshot()['rng_state'],rng);self.assertEqual(self.first(g,PRIESTESS,'board').health,1)
 def test_d1_zealot_actual_death_random_friendly_buff_and_live_trigger_can_choose_self(self):
  g=self.game((KILL,),board=(ZEALOT,FILLER),enemy=(FILLER,));self.play(g,KILL,self.first(g,ZEALOT,'board').id);e=self.first(g,FILLER,'board');self.assertEqual((e.attack,e.health),(3,11));self.assertEqual(self.first(g,FILLER,'board',2).health,10);self.portable(g)
  g=self.game((TRIGGER,),board=(ZEALOT,));source=self.first(g,ZEALOT,'board').id;self.play(g,TRIGGER,source);self.assertEqual((g.state.entities[source].attack,g.state.entities[source].health),(2,2));self.assertFalse(g.state.death_history)
 def test_d2_random_buff_wait_keeps_original_selection_and_rng(self):
  g=self.game((KILL,),board=(ZEALOT,FILLER,FILLER),mode='buff');self.play(g,KILL,self.first(g,ZEALOT,'board').id);self.fail_wait(g);rng=g.snapshot()['rng_state'];stats=[(g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board];self.choose(g);self.assertEqual([(g.state.entities[i].attack,g.state.entities[i].health)for i in g.state.players[1].board],stats);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_e0_broom_real_rush_grants_other_friendly_minions_and_no_future_aura(self):
  g=self.game((FILLER,BROOM,FILLER),enemy=(FILLER,));ally=self.play(g,FILLER);source=self.play(g,BROOM);self.assertIn(Keyword.RUSH,g.state.entities[ally].keywords);self.assertIn(Keyword.RUSH,g.state.entities[source].keywords);self.assertNotIn(Keyword.RUSH,self.first(g,FILLER,'board',2).keywords);s=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,ally,g.state.players[2].hero_id))
  self.assertEqual(g.snapshot(),s);g.apply(Attack(1,ally,self.first(g,FILLER,'board',2).id));later=self.play(g,FILLER);self.assertNotIn(Keyword.RUSH,g.state.entities[later].keywords);self.portable(g)
 def test_e1_broom_grant_wait_keeps_remaining_original_references(self):
  g=self.game((BROOM,),board=(FILLER,FILLER),mode='grant');self.play(g,BROOM);self.fail_wait(g);first,second=g.state.players[1].board[:2];self.assertIn(Keyword.RUSH,g.state.entities[first].keywords);self.assertNotIn(Keyword.RUSH,g.state.entities[second].keywords);self.choose(g);self.assertIn(Keyword.RUSH,g.state.entities[second].keywords);self.portable(g)
 def test_f0_hatchling_discounts_only_actual_held_current_beast_then_real_payment(self):
  g=self.game((KILL,BEAST,OTHER),board=(HATCHLING,FILLER),enemy_hand=(BEAST,));self.play(g,KILL,self.first(g,HATCHLING,'board').id);self.assertEqual(self.cost(g,BEAST),1);self.assertEqual(self.cost(g,BEAST,2),2);self.assertEqual(self.cost(g,OTHER),1);source=self.play(g,BEAST);self.assertEqual(g.state.players[1].mana,59);self.assertEqual(g.state.entities[source].health,10);self.portable(g)
 def test_f1_hatchling_current_added_removed_all_and_zero_cost_candidates(self):
  g=self.game((BECOME,KILL,FILLER),board=(HATCHLING,));self.play(g,BECOME);self.play(g,KILL,self.first(g,HATCHLING,'board').id);self.assertEqual(self.cost(g,FILLER),1)
  g=self.game((REMOVE,KILL,BEAST),board=(HATCHLING,));self.play(g,REMOVE);rng=g.snapshot()['rng_state'];self.play(g,KILL,self.first(g,HATCHLING,'board').id);self.assertEqual(self.cost(g,BEAST),2);self.assertEqual(g.snapshot()['rng_state'],rng)
  for cid in(ALL,ZERO):
   g=self.game((KILL,cid),board=(HATCHLING,));rng=g.snapshot()['rng_state'];self.play(g,KILL,self.first(g,HATCHLING,'board').id);self.assertEqual(self.cost(g,cid),1 if cid==ALL else 0);self.assertNotEqual(g.snapshot()['rng_state'],rng)
 def test_f2_hatchling_cost_wait_restores_without_second_discount_or_draw(self):
  g=self.game((KILL,BEAST),board=(HATCHLING,),mode='stored');self.play(g,KILL,self.first(g,HATCHLING,'board').id);self.fail_wait(g);rng=g.snapshot()['rng_state'];self.assertEqual(self.cost(g,BEAST),1);self.choose(g);self.assertEqual(self.cost(g,BEAST),1);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_g0_bomber_one_simultaneous_hero_batch_has_no_spell_power(self):
  g=self.game((BOMBER,),board=(POWER,),mode='damage');source=self.play(g,BOMBER);self.fail_wait(g);self.assertEqual((self.hp(g),self.hp(g,2)),(97,97));rows=g.state.damage_history;self.assertEqual(len(rows),2);self.assertEqual(len({r.health_result.batch_id for r in rows}),1)
  for row in rows:self.assertEqual((row.health_result.source_id,row.health_result.base_amount,row.health_result.spell_bonus,row.health_result.damage_kind),(source,3,0,DamageKind.MINION_ABILITY.value))
  self.choose(g);self.portable(g)
 def test_g1_bomber_both_heroes_lethal_is_simultaneous_draw(self):
  g=self.game((BOMBER,),hero=LOW,enemy_hero=LOW);self.play(g,BOMBER);self.assertEqual((self.hp(g),self.hp(g,2)),(0,0));self.assertIsNone(g.state.winner);self.portable(g)
 def test_h0_villager_original_death_slot_fresh_shadowbeast_and_source(self):
  g=self.game((KILL,),board=(FILLER,VILLAGER,FILLER));source=self.first(g,VILLAGER,'board').id;self.play(g,KILL,source);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[FILLER,SHADOW,FILLER]);child=self.first(g,SHADOW,'board');self.assertEqual((child.attack,child.health),(1,1));cause=g.state.card_summon_history[-1].request.cause;self.assertEqual((cause.source.entity_id,cause.source.card_id,cause.player_id),(source,VILLAGER,1));self.portable(g)
 def test_h1_shadowbeast_entry_wait_and_live_full_board_capacity(self):
  g=self.game((KILL,),board=(VILLAGER,),mode='entry');self.play(g,KILL,self.first(g,VILLAGER,'board').id);self.fail_wait(g);child=self.first(g,SHADOW,'board').id;self.choose(g);self.assertEqual([e.id for e in g.state.entities.values()if e.card_id==SHADOW],[child]);self.portable(g)
  g=self.game((TRIGGER,),board=(VILLAGER,)+(FILLER,)*6);self.play(g,TRIGGER,self.first(g,VILLAGER,'board').id);self.assertEqual(len(g.state.players[1].board),7);self.assertFalse(any(e.card_id==SHADOW for e in g.state.entities.values()))
 def test_i0_tentacle_original_death_is_one_all_minion_batch_and_simultaneous_deaths(self):
  g=self.game((KILL,),board=(TENTACLE,ONE,POWER),enemy=(ONE,));source=self.first(g,TENTACLE,'board').id;self.play(g,KILL,source);self.assertEqual(len(g.state.damage_history),3);self.assertEqual(len({r.health_result.batch_id for r in g.state.damage_history}),1);self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].board],[POWER]);self.assertFalse(g.state.players[2].board)
  for row in g.state.damage_history:self.assertEqual((row.health_result.source_id,row.health_result.base_amount,row.health_result.spell_bonus,row.health_result.damage_kind),(source,1,0,DamageKind.MINION_ABILITY.value))
  self.assertEqual((self.hp(g),self.hp(g,2)),(100,100));self.portable(g)
 def test_j0_butterfly_full_host_query_fixed_hunter_excludes_neutral_other_and_noncollectible(self):
  seen=set()
  for seed in range(16):
   g=self.game((KILL,),board=(BUTTERFLY,),seed=seed);source=self.first(g,BUTTERFLY,'board').id;self.play(g,KILL,source);cid=g.state.entities[g.state.players[1].hand[0]].card_id;self.assertIn(cid,(HA,HB));seen.add(cid)
  self.assertEqual(seen,{HA,HB});self.assertEqual(g.registry.card(HERO).metadata.classes,(CardClass.MAGE,));self.assertEqual(cards.HUNTER_SPELLS.classes,(CardClass.HUNTER,));self.portable(g)
 def test_j1_butterfly_qualifying_unknown_and_uninstalled_pool_fail_before_rng(self):
  for members in((*MEMBERS,UNKNOWN),None):
   g=self.game((KILL,),board=(BUTTERFLY,),members=members);s=g.snapshot()
   with self.assertRaises((ResolutionError,ValueError)):self.play(g,KILL,self.first(g,BUTTERFLY,'board').id)
   self.assertEqual(g.snapshot(),s)
 def test_j2_butterfly_empty_complete_host_pool_preserves_rng(self):
  g=self.game((KILL,),board=(BUTTERFLY,),members=(OTHER,NEUTRAL));rng=g.snapshot()['rng_state'];self.play(g,KILL,self.first(g,BUTTERFLY,'board').id);self.assertFalse(g.state.players[1].hand);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_j3_butterfly_hand_wait_and_failure_rollback_keep_original_sample(self):
  g=self.game((KILL,),board=(BUTTERFLY,),mode='hand');self.play(g,KILL,self.first(g,BUTTERFLY,'board').id);self.fail_wait(g);rng=g.snapshot()['rng_state'];hand=list(g.state.players[1].hand);self.choose(g);self.assertEqual(g.state.players[1].hand,hand);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
  g=self.game((KILL,),board=(BUTTERFLY,),mode='reject');s=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,KILL,self.first(g,BUTTERFLY,'board').id)
  self.assertEqual(g.snapshot(),s)
 def test_j4_butterfly_full_hand_burn_and_stolen_death_use_original_current_controller(self):
  g=self.game((KILL,)+(FILLER,)*9,board=(BUTTERFLY,),mode='fill');self.play(g,KILL,self.first(g,BUTTERFLY,'board').id);generated=[e for e in g.state.entities.values()if e.card_id in(HA,HB)];self.assertEqual(len(generated),1);self.assertEqual(generated[0].zone,Zone.GRAVEYARD);self.assertEqual(len(g.state.players[1].hand),10);self.portable(g)
  g=self.game((TAKE,KILL),board=(BUTTERFLY,));source=self.first(g,BUTTERFLY,'board').id;self.play(g,TAKE,source);self.play(g,KILL,source);self.assertFalse(g.state.players[1].hand);self.assertIn(g.state.entities[g.state.players[2].hand[0]].card_id,(HA,HB));self.portable(g)
 def test_k0_silence_removes_native_future_trigger_and_death_rewards(self):
  for cid in(BUTTERFLY,ZEALOT,HATCHLING,VILLAGER,TENTACLE):
   g=self.game((SILENCE,KILL),board=(cid,));source=self.first(g,cid,'board').id;self.play(g,SILENCE,source);rng=g.snapshot()['rng_state'];self.play(g,KILL,source);self.assertFalse(g.state.players[1].hand);self.assertFalse(g.state.card_summon_history);self.assertFalse(g.state.damage_history);self.assertEqual(g.snapshot()['rng_state'],rng)
  g=self.game((SILENCE,),board=(BALLOON,));source=self.first(g,BALLOON,'board').id;self.play(g,SILENCE,source);self.cycle(g);self.assertEqual(g.state.entities[source].health,2)
 def test_z0_complete_twelve_rows24_faces_two_api_links_and_old_assembly_preservation(self):
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['official_observations']),len(d['exact_parent_child_links']),len(d['source_tag_links'])),(12,24,2,1));self.assertEqual(d['numeric_normalizations'],{DEPTH:{'attack':0}});self.assertFalse(d['new_standard_collectible_roots']);r0,r1=baseline_registry(),batch_registry();self.assertEqual(len(r1.cards)-len(r0.cards),12);self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
