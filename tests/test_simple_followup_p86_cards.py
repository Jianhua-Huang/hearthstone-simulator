"""Actual native sources, frozen conditions, original budgets and physical copies."""
from dataclasses import asdict
from functools import lru_cache
import hashlib,json,unittest
from pathlib import Path
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p86_cards as cards
from hs_sim.cards.simple_followup_p86_cards import (SARAAD,KNIGHT,HIPPO,RUMBLER,AZERITE,VILLAIN,BLASTFISHER,MANTLE,PRIESTESS,ANTAEN,SHREDDER,AZALINA,ROOTS,DEFERRED,POOL_ID,PREFIX,load_batch,register_simple_followup_p86_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,CostSpec,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Rarity,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,GrantKeyword,InvokeBehavior,RequestChoice,ReturnToHand,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import DamageKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.pools import GenerationContext,PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.random_split_damage import NON_SPELL_PROFILE
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.cross_zone import BuffStoredCard
from hs_sim.engine.zones import CardReference,CopyCard,DiscardCard,ModifyStoredCost

TEST='p86.test.'
HERO,HP,FILLER,TINY,BEAST,ALL,UNKNOWN,DORMANT,TWO_A,TWO_B,POWER=(TEST+i for i in('hero','hp','filler','tiny','beast','all','unknown','dormant','two-a','two-b','provider'))
AUTOMINION=TEST+'automatic-minion'
NOP,HIT,KILL,SILENCE,BUFF,TAKE,BOUNCE,AUTO,GAIN,COPY,ENEMY_BUFF,TO_BEAST=(TEST+i for i in('nop','hit','kill','silence','buff','take','bounce','auto','gain','copy','enemy-buff','to-beast'))
CONTEXT=GenerationContext('p86-explicit-native-tests','experimental')
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=(),collectible=False):return CardMetadata(collectible,(CardClass.MAGE,),Rarity.COMMON,runes=Runes(),tribes=tribes)
def baseline_registry():
 with patch('hs_sim.cards.simple_followup_p86_cards.register_simple_followup_p86_cards',lambda r:None):return build_registry()
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(i in r.cards for i in ROOTS)
 if not any(present):register_simple_followup_p86_cards(r)
 elif not all(present):raise AssertionError('Complete P86 assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
def registry(mode):
 r=Registry('p86-small-native-fixtures');register_simple_followup_p86_cards(r)
 for cid,atk,hp,tribes in((FILLER,1,20,()),(TINY,1,3,()),(BEAST,1,10,('beast',)),(ALL,1,10,('all',)),(UNKNOWN,1,10,None),(DORMANT,1,10,('beast',)),(TWO_A,2,8,()),(TWO_B,3,9,())):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=2 if cid in(TWO_A,TWO_B)else 1,attack=atk,health=hp,dormant_turns=2 if cid==DORMANT else 0,metadata=meta(tribes,collectible=cid in(TWO_A,TWO_B))))
 r.register_card(CardDefinition(POWER,POWER,CardType.MINION,health=8,spell_damage=5,metadata=meta()))
 def fail(c):raise ResolutionError('P86 deliberate pending continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def wait(c):
  change=()
  if mode in('split','blast'):
   change=(Destroy(c.event.source_id,c.source_id),Summon(2,TINY))
   if mode=='blast':
    beast=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==BEAST);change=(Destroy(beast,c.source_id),*change)
  elif mode=='copy':
   last=c.state.entities[c.state.players[2].hand[-1]];change=(DiscardCard(CardReference.capture(last),c.source_id),)
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change original source or later card',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 def enemy_buff(c):
  ref=CardReference.capture(c.state.entities[c.state.players[2].hand[0]])
  return(BuffStoredCard(ref,2,3,c.source_id),ModifyStoredCost(ref,CostSpec(delta=-1),c.source_id))
 scripts={NOP:lambda c:(),HIT:lambda c:(Damage(c.target_id,2,c.source_id,DamageKind.SPELL),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),BUFF:lambda c:(Buff(c.target_id,1,1,c.source_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),BOUNCE:lambda c:(ReturnToHand(c.target_id),),AUTO:lambda c:(CastSpell(c.player_id,NOP,c.source_id),),GAIN:lambda c:(AddToHand(c.player_id,MANTLE,c.source_id),),COPY:lambda c:(CopyCard(CardReference.capture(c.state.entities[c.target_id]),c.player_id,source_id=c.source_id),),ENEMY_BUFF:enemy_buff,TO_BEAST:lambda c:(ChangeMinionTribes(MinionReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',('beast',)),c.source_id),)}
 for cid,body in scripts.items():
  r.register_behavior(cid,body);target=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid==COPY else TargetSpec()if cid in(HIT,KILL,SILENCE,BUFF,TAKE,BOUNCE,TO_BEAST)else None
  r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=target,metadata=meta(collectible=cid==NOP)))
 r.register_card(CardDefinition(AUTOMINION,AUTOMINION,CardType.MINION,health=2,battlecry=AUTO,metadata=meta()))
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=NOP,metadata=meta()))
 extra={}
 if mode:
  def eligible(c):
   if mode=='summon':return c.player_id==1 and any(root.request.cause.source.card_id==SHREDDER and any(x.outcome=='delivered'and x.entity.entity_id==c.event.target_id for x in root.deliveries)for root in c.state.card_summon_history)
   if c.player_id!=1 or c.event.source_id is None:return False
   cid=c.state.entities[c.event.source_id].card_id
   return cid in((PRIESTESS,ANTAEN)if mode=='split'else(BLASTFISHER,)if mode=='blast'else(AZALINA,)if mode=='copy'else(SARAAD,)if mode=='generate'else(SHREDDER,))and(c.event.player_id==1 if mode in('copy','generate')else True)
  event='damage_dealt'if mode in('split','blast')else'card_added_to_hand'if mode in('copy','generate')else'minion_summoned'
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible'),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra))
 for cid in(TWO_A,TWO_B,NOP):r.register_pool_card(PoolCard.from_definition(r.card(cid)))
 r.register_pool(PoolDefinition(POOL_ID,'p86-complete-fixture-v1',CONTEXT.target_id,CONTEXT.mode,tuple(PoolMember(i)for i in(TWO_A,TWO_B,NOP)),complete=True));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP86Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),deck=(FILLER,)*10,mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=deck,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*10,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8686,generation_context=CONTEXT),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def choose(self,g,key='ok'):
  q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
 def portable(self,g):
  reader=fixture_registry(self.mode,'reader',SOURCE_PIN);self.assertIsNot(reader,g.registry);self.assertEqual(reader.fingerprint(),g.registry.fingerprint());snap=json.loads(json.dumps(g.snapshot()))
  self.assertEqual(Game.from_snapshot(snap,reader).snapshot(),snap);self.assertEqual(g.clone().snapshot(),snap);self.assertEqual(replay(build_replay(g),reader).snapshot(),snap)
  for pid in(1,2):
   public=json.dumps(g.for_player(pid).observe())+json.dumps(g.for_player(pid).legal_actions())+json.dumps(g.player_events(pid))
   for key in('rng_state','resolution_frame','source_allocation','cast_ids','behavior_id','original_entities'):self.assertNotIn('"'+key+'"',public)
 def fail_wait(self,g):
  self.assertIsNotNone(g.state.pending_choice);self.portable(g);snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.choose(g,'fail')
  self.assertEqual(g.snapshot(),snap)
 def next_own(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))
 def hp(self,g,pid=2):return g.state.entities[g.state.players[pid].hero_id].health

 def test_a0_all_twelve_actual_paid_entries_printed_stats_metadata_and_cost(self):
  for cid in ROOTS:
   g=self.game((cid,));before=g.state.players[1].mana;eid=self.play(g,cid,g.state.players[2].hero_id if cid==KNIGHT else None);raw=next(x['record']for x in load_batch()['dependencies']if x['record']['id']==cid);e=g.state.entities[eid]
   self.assertEqual((e.card_id,e.attack,e.health),(cid,raw['attack'],raw['health']));self.assertEqual(before-g.state.players[1].mana,raw['cost']);self.assertEqual(g.state.play_history[-1].card_id,cid)
 def test_b0_saraad_only_actual_successful_own_manual_power_and_silence(self):
  g=self.game(board=(SARAAD,));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[NOP]);g.apply(EndTurn(1));g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual(len(g.state.players[1].hand),1)
  g=self.game((SILENCE,),board=(SARAAD,));self.play(g,SILENCE,self.first(g,SARAAD,'board').id);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertFalse(g.state.players[1].hand)
 def test_b1_saraad_actual_random_hand_delivery_wait_restores_rng_and_payment(self):
  g=self.game(board=(SARAAD,),mode='generate');g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.fail_wait(g);self.choose(g);self.assertEqual(g.state.players[1].mana,58);self.assertEqual(len(g.state.players[1].hand),1);self.portable(g)
 def test_c0_knight_original_exact_kill_buffs_but_overkill_does_not(self):
  for prior in(False,True):
   g=self.game((KNIGHT,HIT),enemy=(TINY,));target=self.first(g,TINY,'board',2).id
   if prior:self.play(g,HIT,target)
   eid=self.play(g,KNIGHT,target);self.assertEqual((g.state.entities[eid].attack,g.state.entities[eid].health),(3,3)if prior else(6,6))
 def test_c1_hippogryph_real_rush_honorable_kill_unlocks_second_attack_only(self):
  g=self.game((HIPPO,),enemy=(TINY,TINY,TINY));eid=self.play(g,HIPPO);targets=list(g.state.players[2].board);g.apply(Attack(1,eid,targets[0]));self.assertIn(Keyword.WINDFURY,g.state.entities[eid].keywords);g.apply(Attack(1,eid,targets[1]));snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(Attack(1,eid,targets[2]))
  self.assertEqual(g.snapshot(),snap);self.portable(g)
 def test_d0_rumbler_previous_actual_own_spell_interval_not_current_or_opponent(self):
  for qualifying in(True,False):
   g=self.game((NOP,RUMBLER),board=(FILLER,),enemy=(FILLER,));other=self.first(g,FILLER,'board').id
   if qualifying:self.play(g,NOP)
   self.next_own(g)
   if not qualifying:self.play(g,NOP)
   self.play(g,RUMBLER);self.assertEqual(g.state.entities[other].damage,2 if qualifying else 0)
 def test_d1_rumbler_counts_real_automatic_payload_in_previous_own_interval(self):
  g=self.game((AUTOMINION,RUMBLER),board=(FILLER,));self.play(g,AUTOMINION);self.assertEqual(len(g.state.cast_history),1);self.assertTrue(all(x.kind==CardType.MINION for x in g.state.play_history));self.next_own(g);self.play(g,RUMBLER);self.assertEqual(self.first(g,FILLER,'board').damage,2)
 def test_e0_azerite_stacks_native_spell_damage_each_owner_start_then_silence(self):
  g=self.game((HIT,SILENCE,HIT),board=(AZERITE,));self.next_own(g);self.next_own(g);self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(self.hp(g),24);self.play(g,SILENCE,self.first(g,AZERITE,'board').id);self.next_own(g);self.play(g,HIT,g.state.players[2].hero_id);self.assertEqual(self.hp(g),22);self.portable(g)
 def test_f0_villain_natural_original_attack_condition_and_fresh_named_body(self):
  for buff in(False,True):
   g=self.game((BUFF,KILL),board=(FILLER,VILLAIN,FILLER));old=self.first(g,VILLAIN,'board').id
   if buff:self.play(g,BUFF,old)
   self.play(g,KILL,old);new=[i for i in g.state.players[1].board if g.state.entities[i].card_id==VILLAIN];self.assertEqual(len(new),int(buff))
   if buff:self.assertNotEqual(new[0],old);self.assertEqual(g.state.players[1].board.index(new[0]),1);self.assertEqual((g.state.entities[new[0]].attack,g.state.entities[new[0]].health),(3,6))
 def test_f1_villain_silence_and_current_death_controller(self):
  g=self.game((BUFF,SILENCE,KILL),board=(VILLAIN,));eid=self.first(g,VILLAIN,'board').id;self.play(g,BUFF,eid);self.play(g,SILENCE,eid);self.play(g,KILL,eid);self.assertFalse(g.state.players[1].board)
  g=self.game((BUFF,TAKE,KILL),board=(VILLAIN,));eid=self.first(g,VILLAIN,'board').id;self.play(g,BUFF,eid);self.play(g,TAKE,eid);self.play(g,KILL,eid);self.assertEqual(self.first(g,VILLAIN,'board',2).health,6)
 def test_g0_blastfisher_current_beast_all_dormant_and_ordinary_fixed_repetitions(self):
  g=self.game((BLASTFISHER,BEAST),board=(BEAST,ALL,DORMANT));self.play(g,BLASTFISHER);self.assertEqual(self.hp(g),24)
  g=self.game((TO_BEAST,BLASTFISHER),board=(FILLER,));self.play(g,TO_BEAST,self.first(g,FILLER,'board').id);self.play(g,BLASTFISHER);self.assertEqual(self.hp(g),26)
 def test_g1_blastfisher_unknown_current_tribe_rolls_back_original_play(self):
  g=self.game((BLASTFISHER,),board=(UNKNOWN,));snap=g.snapshot()
  with self.assertRaises(ResolutionError):self.play(g,BLASTFISHER)
  self.assertEqual(g.snapshot(),snap)
 def test_g2_blastfisher_accepted_count_survives_first_hit_wait_and_source_death(self):
  g=self.game((BLASTFISHER,),board=(BEAST,),mode='blast');self.play(g,BLASTFISHER);self.fail_wait(g);self.choose(g,'change');self.assertEqual(sum(x.health_result.damage_dealt for x in g.state.damage_history if x.health_result.damage_kind=='minion_ability'),4);self.portable(g)
 def test_h0_mantle_only_real_own_casts_while_this_card_is_in_hand(self):
  g=self.game((NOP,GAIN,NOP));self.play(g,NOP);self.play(g,GAIN);eid=self.first(g,MANTLE).id;self.assertEqual(g.quote_cost(eid).amount,5);self.play(g,NOP);self.assertEqual(g.quote_cost(eid).amount,4);self.play(g,MANTLE);self.assertEqual(g.state.play_history[-1].cost,4);self.portable(g)
 def test_h1_mantle_current_copy_keeps_local_price_and_native_bounce_resets(self):
  g=self.game((MANTLE,NOP,COPY,BOUNCE));eid=self.first(g,MANTLE).id;self.play(g,NOP);self.play(g,COPY,eid);held=[i for i in g.state.players[1].hand if g.state.entities[i].card_id==MANTLE];self.assertEqual([g.quote_cost(i).amount for i in held],[3,3]);old=self.play(g,MANTLE);self.play(g,BOUNCE,old);self.assertEqual(g.quote_cost(old).amount,5);self.portable(g)
 def test_h2_mantle_opponent_cast_excluded_and_hand_auto_casts_count(self):
  g=self.game((MANTLE,AUTO),enemy_hand=(NOP,));eid=self.first(g,MANTLE).id;g.apply(EndTurn(1));self.play(g,NOP,pid=2);g.apply(EndTurn(2));self.assertEqual(g.quote_cost(eid).amount,5);self.play(g,AUTO);self.assertEqual(g.quote_cost(eid).amount,3)
 def test_i0_priestess_whole_nonspell_budget_ignores_spell_damage_bonus(self):
  g=self.game(board=(PRIESTESS,POWER));g.apply(EndTurn(1));self.assertEqual(self.hp(g),24);root=g.state.split_damage_history[-1];self.assertEqual((root.request.profile,root.request.kind,root.quote.budget),(NON_SPELL_PROFILE,DamageKind.MINION_ABILITY,6));self.assertEqual(len(root.packets),6);self.assertTrue(root.completed);self.portable(g)
 def test_i1_priestess_real_packet_wait_preserves_budget_after_source_death_and_new_target(self):
  g=self.game(board=(PRIESTESS,),mode='split');g.apply(EndTurn(1));self.fail_wait(g);self.choose(g,'change');root=g.state.split_damage_history[-1];self.assertTrue(root.completed);self.assertEqual(len(root.packets),6);self.assertTrue(any(len(x.selection.candidates)>1 for x in root.packets[1:]));self.portable(g)
 def test_j0_antaen_actual_two_owner_starts_and_one_whole_awakening_budget(self):
  g=self.game((ANTAEN,),board=(POWER,));eid=self.play(g,ANTAEN);self.next_own(g);self.assertEqual(self.hp(g),30);self.next_own(g);self.assertEqual(self.hp(g),20);self.assertEqual(g.state.entities[eid].zone,Zone.BOARD);self.assertEqual(len(g.state.split_damage_history),1);self.next_own(g);self.assertEqual(len(g.state.split_damage_history),1);self.portable(g)
 def test_j1_antaen_real_awake_packet_wait_has_original_ten_budget_and_rollback(self):
  g=self.game((ANTAEN,),mode='split');self.play(g,ANTAEN);self.next_own(g);g.apply(EndTurn(1));g.apply(EndTurn(2));self.fail_wait(g);self.choose(g,'change');self.assertEqual(len(g.state.split_damage_history[-1].packets),10);self.assertTrue(g.state.split_damage_history[-1].completed);self.portable(g)
 def test_k0_shredder_actual_death_random_two_cost_summon_original_position(self):
  g=self.game((KILL,),board=(FILLER,SHREDDER,FILLER));old=self.first(g,SHREDDER,'board').id;self.play(g,KILL,old);new=g.state.entities[g.state.players[1].board[1]];self.assertIn(new.card_id,(TWO_A,TWO_B));self.assertEqual(g.registry.card(new.card_id).cost,2);self.assertNotEqual(new.id,old);self.portable(g)
 def test_k1_shredder_real_dead_source_random_delivery_wait_restores(self):
  g=self.game((KILL,),board=(SHREDDER,),mode='summon');self.play(g,KILL,self.first(g,SHREDDER,'board').id);self.fail_wait(g);self.choose(g);self.assertEqual(len(g.state.players[1].board),1);self.portable(g)
 def test_l0_azalina_permanent_current_copy_replaces_without_discard_or_enemy_move(self):
  g=self.game((ENEMY_BUFF,AZALINA,FILLER),enemy_hand=(BEAST,FILLER));self.play(g,ENEMY_BUFF);own=tuple(g.state.players[1].hand[1:]);other=tuple(g.state.players[2].hand);rng=g.snapshot()['rng_state'];self.play(g,AZALINA);self.assertEqual(tuple(g.state.players[2].hand),other);self.assertEqual(tuple(g.state.entities[i].origin_entity_id for i in g.state.players[1].hand),other);self.assertTrue(all(g.state.entities[i].zone==Zone.SETASIDE for i in own));copied=self.first(g,BEAST);self.assertEqual((copied.attack,copied.health,g.quote_cost(copied.id).amount),(3,13,0));self.assertFalse(g.state.discard_history);self.assertFalse(g.state.temporary_hands);self.assertEqual(g.snapshot()['rng_state'],rng);self.portable(g)
 def test_l1_azalina_copy_wait_keeps_original_references_and_skips_later_departed_card(self):
  g=self.game((AZALINA,FILLER),enemy_hand=(BEAST,FILLER),mode='copy');self.play(g,AZALINA);self.fail_wait(g);self.choose(g,'change');self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],[BEAST]);self.portable(g)
 def test_z0_complete_raw_and_before_after_central_assembly_preservation(self):
  d=load_batch();self.assertEqual(len(d['dependencies']),12);self.assertEqual(len(d['official_observations']),30);self.assertEqual([x['card_id']for x in d['skipped']],['BT_495']);self.assertFalse(d['cards']);r0=baseline_registry();r1=batch_registry()
  self.assertTrue(set(DEFERRED).isdisjoint(set(r1.cards)-set(r0.cards)));self.assertEqual(len(r1.cards)-len(r0.cards),12);self.assertEqual({i:r1.card(i)for i in r0.cards},r0.cards);self.assertEqual({i:r1.pool_cards[i]for i in r0.pool_cards},r0.pool_cards)
  for key in('player_effects','fabled','generation_families','pools','jade_families'):self.assertEqual(getattr(r0,key),getattr(r1,key))
  for x in d['dependencies']:
   raw=x['record'];self.assertEqual(r1.card(raw['id']).metadata,metadata_from_record(raw));self.assertEqual((r1.card(raw['id']).cost,r1.card(raw['id']).attack,r1.card(raw['id']).health),(raw['cost'],raw['attack'],raw['health']))
