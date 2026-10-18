"""Complete reviewed alias declarations and real conditional/Combo/death windows."""
from dataclasses import asdict,replace
from functools import lru_cache
import hashlib,json
from pathlib import Path
import unittest
from unittest.mock import patch
from hs_sim.cards import build_registry
from hs_sim.cards import simple_followup_p83_cards as cards
from hs_sim.cards.simple_followup_p83_cards import (FIEND,VALIANT,EMPEROR,HAN,ALCHEMIST,RIDER,CHAMPION,ARMOR,BLACKWING,SCRAP,VILE,CHEMIST,ROOTS,PREFIX,load_batch,register_simple_followup_p83_cards)
from hs_sim.cards.candidate_generation_catalog import register_candidate_pool_metadata
from hs_sim.cards.simple_followup_p79_cards import register_simple_followup_p79_cards
from hs_sim.cards.simple_followup_p81_cards import register_simple_followup_p81_cards
from hs_sim.cards.conditional_cards import SCRIPTS
from hs_sim.cards.metadata import metadata_from_record
from hs_sim.engine import (Attack,CardClass,CardDefinition,CardMetadata,CardType,EndTurn,Game,IllegalAction,Keyword,PlayCard,PlayerSetup,Registry,Scenario,SelectChoice,TargetSpec,UseHeroPower,Zone)
from hs_sim.engine.effects import (AddToHand,Buff,ChangeControl,ChoiceOption,Damage,Destroy,Heal,InvokeBehavior,RequestChoice,Silence,Summon)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.health_outcomes import health_result
from hs_sim.engine.model import DamageKind,EndTurnSpec,HealingKind,LimitedTriggerSpec,Runes,TribeChangeSpec
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.tribes import ChangeMinionTribes
from hs_sim.engine.zones import CardReference,DiscardCard

TEST='p83.test.'
HERO,HP,FILLER,DRAGON,ALL,TOTEM,UNKNOWN=(TEST+i for i in('hero','power','filler','dragon','all','totem','unknown'))
NOP,PING,BLAST,KILL,SILENCE,TAKE,BUFF,HEAL,TO_DRAGON,TO_BEAST=(TEST+i for i in('nop','ping','blast','kill','silence','take','buff','heal','to-dragon','to-beast'))
SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes()+Path(cards.__file__).read_bytes()+cards.BATCH_PATH.read_bytes()).hexdigest()
def meta(tribes=()):return CardMetadata(False,(CardClass.MAGE,),None,runes=Runes(),tribes=tribes)
def batch_registry():
 with patch('hs_sim.cards.candidate_generation_catalog.register_candidate_pool_metadata',lambda r:None):r=build_registry()
 present=tuple(cid in r.cards for cid in ROOTS)
 if not any(present):register_simple_followup_p83_cards(r)
 elif not all(present):raise AssertionError('P83 complete assigned assembly required')
 register_candidate_pool_metadata(r);r.validate();return r
@lru_cache(maxsize=1)
def original_fixture_sources():
 r=build_registry();definitions=tuple(r.card(i)for i in('CS2_152','AT_028','OG_234','CFM_756','CORE_BOT_576'))
 keys=('cards.simple_followup_p78.rider','cards.simple_followup_p78.alchemist','cards.simple_followup_p82.armor')
 return definitions,tuple((k,r.behavior(k))for k in keys)
def registry(mode):
 r=Registry('p83-small-native-fixtures');definitions,bodies=original_fixture_sources()
 for d in definitions:r.register_card(d)
 for k,body in bodies:r.register_behavior(k,body)
 r.register_behavior('cards.conditions.combo_buff',lambda c:SCRIPTS['combo_buff'](c,r))
 register_simple_followup_p79_cards(r);register_simple_followup_p81_cards(r);register_simple_followup_p83_cards(r)
 for cid,tribes in((FILLER,()),(DRAGON,('dragon',)),(ALL,('all',)),(TOTEM,('totem',)),(UNKNOWN,None)):
  r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=4,attack=1,health=12,metadata=meta(tribes)))
 r.register_behavior(NOP,lambda c:())
 def fail(c):raise ResolutionError('P83 deliberate continuation failure')
 r.register_behavior(TEST+'fail',fail)
 def wait(c):
  change=()
  if mode=='end':
   source=next(i for i in c.state.players[1].board if c.state.entities[i].card_id==EMPEROR);change=(Destroy(source,c.source_id),AddToHand(1,FILLER,c.source_id))
  elif mode=='death':change=(Summon(1,SCRAP),)
  elif mode=='combo':change=(Destroy(c.event.target_id,c.source_id),)
  elif mode=='dragon':
   target=next(c.state.entities[i]for i in c.state.players[1].hand if c.state.entities[i].card_id==DRAGON);change=(DiscardCard(CardReference.capture(target),c.source_id),)
  return(RequestChoice(1,(ChoiceOption('ok','Continue'),ChoiceOption('change','Change earlier state',change),ChoiceOption('fail','Fail',(InvokeBehavior(TEST+'fail',c.source_id,1),))),c.source_id),)
 r.register_behavior(TEST+'wait',wait)
 r.register_card(CardDefinition(HP,HP,CardType.HERO_POWER,cost=2,on_use=TEST+'wait'if mode=='power'else NOP,metadata=meta()))
 scripts={PING:lambda c:(Damage(c.target_id,1,c.source_id,DamageKind.EFFECT),),BLAST:lambda c:(Damage(c.target_id,12,c.source_id,DamageKind.EFFECT),),KILL:lambda c:(Destroy(c.target_id,c.source_id),),SILENCE:lambda c:(Silence(c.target_id),),TAKE:lambda c:(ChangeControl(c.target_id,2),),BUFF:lambda c:(Buff(c.target_id,3,2,c.source_id),),HEAL:lambda c:(Heal(c.target_id,5,c.source_id,HealingKind.EFFECT),)}
 for cid,tribe in((TO_DRAGON,'dragon'),(TO_BEAST,'beast')):scripts[cid]=lambda c,tribe=tribe:(ChangeMinionTribes(CardReference.capture(c.state.entities[c.target_id]),TribeChangeSpec('set',(tribe,)),c.source_id),)
 for cid,body in scripts.items():
  r.register_behavior(cid,body);r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,targeting=TargetSpec(zones=(Zone.HAND,),kinds=(CardType.MINION,),relation='friendly')if cid in(TO_DRAGON,TO_BEAST)else TargetSpec(),metadata=meta()))
 r.register_card(CardDefinition(NOP,NOP,CardType.SPELL,on_play=NOP,metadata=meta()))
 extra={}
 if mode in('end','death','combo','dragon'):
  def eligible(c):
   if c.player_id!=1:return False
   if mode=='end':return c.event.player_id==1
   if c.event.source_id is None:return False
   return c.state.entities[c.event.source_id].card_id in((SCRAP,)if mode=='death'else(VILE,CHEMIST)if mode=='combo'else(BLACKWING,))
  event='turn_ended'if mode=='end'else'minion_died'if mode=='death'else'card_committed'
  r.register_trigger_condition(TEST+'eligible',eligible);extra['limited_triggers']=(LimitedTriggerSpec(event,TEST+'wait',condition_id=TEST+'eligible',end_turn=EndTurnSpec()if mode=='end'else None),)
 r.register_card(CardDefinition(HERO,HERO,CardType.HERO,health=30,initial_hero_power=HP,metadata=meta(),**extra));r.validate();return r
@lru_cache(maxsize=None)
def fixture_registry(mode,role,pin):
 if role not in('writer','reader')or pin!=SOURCE_PIN:raise AssertionError('Immutable fixture key required')
 r=registry(mode);r.freeze();return r

class SimpleFollowupP83Tests(unittest.TestCase):
 def game(self,hand=(),board=(),enemy=(),enemy_hand=(),mode=None):
  self.mode=mode
  return Game.from_scenario(Scenario((PlayerSetup(HERO,hand=hand,board=board,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP),PlayerSetup(HERO,hand=enemy_hand,board=enemy,deck=(FILLER,)*12,mana=60,max_mana=60,mana_cap=60,hero_power_card_id=HP)),seed=8383),fixture_registry(mode,'writer',SOURCE_PIN))
 def first(self,g,cid,zone='hand',pid=1):return next(g.state.entities[i]for i in getattr(g.state.players[pid],zone)if g.state.entities[i].card_id==cid)
 def play(self,g,cid,target=None,pid=1):
  e=self.first(g,cid,pid=pid);g.apply(PlayCard(pid,e.id,target_id=target,position=len(g.state.players[pid].board)if e.kind==CardType.MINION else None));return e.id
 def stats(self,g,eid):return(g.state.entities[eid].attack,g.state.entities[eid].health)
 def hp(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].health
 def armor(self,g,pid=1):return g.state.entities[g.state.players[pid].hero_id].armor
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
 def denied(self,g,action):
  snap=g.snapshot()
  with self.assertRaises(IllegalAction):g.apply(action)
  self.assertEqual(g.snapshot(),snap)

 def test_a0_all_twelve_paid_entries_printed_stats_and_original_entry_families(self):
  rows={x['record']['id']:x['record']for x in load_batch()['dependencies']}
  for cid in ROOTS:
   g=self.game((cid,),enemy=(FILLER,));target=g.state.players[2].hero_id if cid==ALCHEMIST else None;source=self.play(g,cid,target);raw=rows[cid]
   self.assertEqual(self.stats(g,source),(raw['attack'],raw['health']));self.assertEqual(g.state.players[1].mana,55)
   if cid in(RIDER,VILE,CHEMIST):self.assertEqual(len(g.state.combo_history),0);self.assertIsNone(g.registry.card(cid).battlecry)
   if cid in(ARMOR,SCRAP):self.assertIn(Keyword.TAUNT,g.state.entities[source].keywords)

 def test_a1_all_nine_full_reused_declarations_match_except_explicit_raw_identity_fields(self):
  r=fixture_registry(None,'writer',SOURCE_PIN);d=load_batch();sources={**d['reviewed_declaration_aliases'],**d['additional_reused_combo_source']};rows={x['record']['id']:x['record']for x in d['dependencies']}
  for cid,old in sources.items():
   raw=rows[cid];expected=replace(r.card(old),id=cid,name=raw['name'],cost=raw['cost'],attack=raw['attack'],health=raw['health'],metadata=metadata_from_record(raw));self.assertEqual(r.card(cid),expected)

 def test_b0_fiend_battlecry_and_completed_inspire_both_hero_four(self):
  g=self.game((FIEND,));source=self.play(g,FIEND);self.assertEqual((self.hp(g),self.hp(g,2)),(26,26));g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual((self.hp(g),self.hp(g,2)),(22,22));g.apply(EndTurn(1));g.apply(UseHeroPower(2,g.state.players[2].hero_power_id));self.assertEqual(self.hp(g),22);self.portable(g)

 def test_b1_valiant_two_entries_current_totems_all_not_other_or_enemy(self):
  g=self.game((VALIANT,),board=(TOTEM,ALL,FILLER),enemy=(TOTEM,));self.play(g,VALIANT);self.assertEqual(self.first(g,TOTEM,'board').attack,3);self.assertEqual(self.first(g,ALL,'board').attack,3);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.assertEqual(self.first(g,TOTEM,'board').attack,5);self.assertEqual(self.first(g,FILLER,'board').attack,1);self.assertEqual(self.first(g,TOTEM,'board',2).attack,1)

 def test_b2_champion_only_own_inspire_buffs_other_friends_and_real_power_wait_recovers(self):
  g=self.game((CHAMPION,),board=(FILLER,),mode='power');source=self.play(g,CHAMPION);self.assertEqual(self.first(g,FILLER,'board').attack,1);g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.fail_wait(g);self.choose(g);self.assertEqual(self.first(g,FILLER,'board').attack,2);self.assertEqual(self.stats(g,source),(5,3));self.portable(g)

 def test_b3_emperor_uses_classified_owner_end_local_cost_and_fresh_hand_after_source_death(self):
  g=self.game((EMPEROR,FILLER),mode='end');source=self.play(g,EMPEROR);g.apply(EndTurn(1));self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);g.apply(EndTurn(2));self.play(g,FILLER);self.play(g,FILLER);self.assertEqual(g.state.players[1].mana,54);self.portable(g)

 def test_b4_han_random_hand_minion_five_five_and_empty_or_spell_hand_no_rng(self):
  g=self.game((HAN,FILLER,NOP));self.play(g,HAN);e=self.first(g,FILLER);self.assertEqual((e.attack,e.health),(6,17));self.portable(g)
  for hand in((HAN,),(HAN,NOP)):
   g=self.game(hand);rng=g.snapshot()['rng_state'];self.play(g,HAN);self.assertEqual(g.snapshot()['rng_state'],rng)

 def test_b5_alchemist_actual_five_effect_healing_targets_either_hero_or_minion(self):
  for pid in(1,2):
   g=self.game((BLAST,ALCHEMIST));hero=g.state.players[pid].hero_id;self.play(g,BLAST,hero);source=self.play(g,ALCHEMIST,hero);self.assertEqual(self.hp(g,pid),23);h=[health_result(e)for e in g.events if e.kind=='health_resolved'and health_result(e).source_id==source];self.assertEqual((h[0].healed,h[0].healing_kind),(5,HealingKind.EFFECT.value))

 def test_b6_armorsmith_alias_keeps_exact_actual_dealt_damage_reward(self):
  g=self.game(board=(ARMOR,),enemy=(FILLER,));source=self.first(g,ARMOR,'board').id;g.apply(Attack(1,source,self.first(g,FILLER,'board',2).id));self.assertEqual(self.armor(g),3);self.portable(g)

 def test_c0_blackwing_no_dragon_has_no_target_and_with_dragon_requires_exact_character(self):
  g=self.game((BLACKWING,));source=self.first(g,BLACKWING).id;self.denied(g,PlayCard(1,source,target_id=g.state.players[2].hero_id,position=0));self.play(g,BLACKWING);self.assertEqual(self.hp(g,2),30)
  g=self.game((BLACKWING,DRAGON));source=self.first(g,BLACKWING).id;self.denied(g,PlayCard(1,source,position=0));self.play(g,BLACKWING,g.state.players[2].hero_id);self.assertEqual(self.hp(g,2),25);self.assertEqual(g.state.players[1].mana,55);self.portable(g)

 def test_c1_blackwing_current_hand_all_and_changed_tribes_not_board_or_opponent(self):
  for cid in(DRAGON,ALL):
   g=self.game((BLACKWING,cid),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.play(g,BLACKWING,target);self.assertEqual(g.state.entities[target].health,7)
  g=self.game((BLACKWING,FILLER,TO_DRAGON));target=self.first(g,FILLER).id;self.play(g,TO_DRAGON,target);self.play(g,BLACKWING,g.state.players[2].hero_id);self.assertEqual(self.hp(g,2),25)
  g=self.game((BLACKWING,DRAGON,TO_BEAST),board=(DRAGON,),enemy_hand=(DRAGON,));self.play(g,TO_BEAST,self.first(g,DRAGON).id);self.play(g,BLACKWING);self.assertEqual(self.hp(g,2),30)

 def test_c2_blackwing_unknown_own_hand_tribe_fails_without_payment_or_private_leak(self):
  g=self.game((BLACKWING,UNKNOWN));source=self.first(g,BLACKWING).id;snap=g.snapshot()
  with self.assertRaises(ResolutionError):g.apply(PlayCard(1,source,target_id=g.state.players[2].hero_id,position=0))
  self.assertEqual(g.snapshot(),snap)

 def test_c3_blackwing_rechecks_actual_hand_condition_after_native_committed_wait(self):
  g=self.game((BLACKWING,DRAGON),mode='dragon');self.play(g,BLACKWING,g.state.players[2].hero_id);self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.hp(g,2),30);self.portable(g)

 def test_d0_scrap_death_uses_buffed_original_attack_and_silence_removes_text(self):
  g=self.game((SCRAP,BUFF,KILL));source=self.play(g,SCRAP);self.play(g,BUFF,source);self.play(g,KILL,source);self.assertEqual(self.armor(g),7);self.assertEqual(g.state.death_history[-1].attack,7)
  g=self.game((SCRAP,SILENCE,KILL));source=self.play(g,SCRAP);self.play(g,SILENCE,source);self.play(g,KILL,source);self.assertEqual(self.armor(g),0)

 def test_d1_scrap_original_death_attack_survives_wait_and_new_same_face_body(self):
  g=self.game((SCRAP,BUFF,KILL),mode='death');source=self.play(g,SCRAP);self.play(g,BUFF,source);self.play(g,KILL,source);self.fail_wait(g);self.choose(g,'change');self.assertEqual(self.armor(g),7);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(self.first(g,SCRAP,'board').attack,4);self.portable(g)

 def test_d2_scrap_death_controller_not_original_owner_receives_armor(self):
  g=self.game((SCRAP,BUFF,TAKE),enemy_hand=(KILL,));source=self.play(g,SCRAP);self.play(g,BUFF,source);self.play(g,TAKE,source);g.apply(EndTurn(1));self.play(g,KILL,source,pid=2);self.assertEqual((self.armor(g),self.armor(g,2)),(0,7));self.portable(g)

 def test_e0_native_combo_rider_and_chemist_use_correct_original_body_and_one_payment(self):
  g=self.game((NOP,RIDER));self.play(g,NOP);source=self.play(g,RIDER);self.assertEqual(self.stats(g,source),(7,7));self.assertEqual(g.state.combo_history[-1].card_id,RIDER);self.assertEqual(g.state.players[1].mana,55)
  g=self.game((NOP,CHEMIST),board=(FILLER,),enemy=(FILLER,));self.play(g,NOP);target=self.first(g,FILLER,'board').id;source=self.play(g,CHEMIST,target);self.assertEqual(g.state.entities[target].attack,5);self.assertEqual(self.first(g,FILLER,'board',2).attack,1);self.assertEqual(self.stats(g,source),(4,4));self.assertEqual(g.state.combo_history[-1].target_id,target)

 def test_e1_vile_combo_destroys_any_selected_minion_never_hero_and_inactive_target_rejected(self):
  g=self.game((VILE,),enemy=(FILLER,));target=self.first(g,FILLER,'board',2).id;self.denied(g,PlayCard(1,self.first(g,VILE).id,target_id=target,position=0));self.play(g,VILE);self.assertEqual(g.state.entities[target].zone,Zone.BOARD)
  for pid in(1,2):
   g=self.game((NOP,VILE),board=(FILLER,),enemy=(FILLER,));self.play(g,NOP);source=self.first(g,VILE).id;self.denied(g,PlayCard(1,source,target_id=g.state.players[2].hero_id,position=1));target=self.first(g,FILLER,'board',pid).id;self.play(g,VILE,target);self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.combo_history[-1].target_id,target)

 def test_e2_chemist_combo_rejects_enemy_target_and_lost_target_wait_keeps_original_payment(self):
  g=self.game((NOP,CHEMIST),board=(FILLER,),enemy=(FILLER,));self.play(g,NOP);self.denied(g,PlayCard(1,self.first(g,CHEMIST).id,target_id=self.first(g,FILLER,'board',2).id,position=1))
  for cid,pid in((VILE,2),(CHEMIST,1)):
   g=self.game((NOP,cid),board=(FILLER,),enemy=(FILLER,),mode='combo');self.play(g,NOP);target=self.first(g,FILLER,'board',pid).id;self.play(g,cid,target);self.fail_wait(g);self.choose(g,'change');self.assertEqual(g.state.entities[target].zone,Zone.GRAVEYARD);self.assertEqual(g.state.players[1].mana,55);self.portable(g)

 def test_z0_complete_sources_alias_raw_checks_and_old_content_before_after_assembly(self):
  from tools.card_batch import check_face
  d=load_batch();self.assertEqual((len(d['dependencies']),len(d['existing_dependencies']),len(d['official_observations'])),(12,9,44));self.assertEqual(len(d['alias_face_checks']),9);self.assertEqual((d['exact_parent_child_links'],d['source_tag_links']),([],[]))
  rows={x['record']['id']:x['record']for k in('dependencies','existing_dependencies','evidence_only')for x in d[k]}
  for o in d['official_observations']:check_face(rows[o['card_id']],o['face'],o['locale'])
  before,after=build_registry(),batch_registry()
  for cid,c in before.cards.items():self.assertEqual(after.card(cid),c)
  for cid,c in before.pool_cards.items():self.assertEqual(after.pool_card(cid),c)
  self.assertEqual(set(after.cards)-set(before.cards),set(ROOTS)-set(before.cards))
  for key in('player_effects','fabled','jade_families','generation_families','pools'):self.assertEqual(getattr(before,key),getattr(after,key))
  self.assertEqual('TIME_040'in before.cards,'TIME_040'in after.cards)
  with patch(__name__+'.build_registry',lambda:after):self.assertIs(batch_registry(),after)

if __name__=='__main__':unittest.main()
