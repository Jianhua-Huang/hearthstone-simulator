"""Excavation progress is player state, independent of rewards and source bodies."""
from dataclasses import replace
import json
import unittest
from hs_sim.engine import (CardDefinition, CardClass, CardMetadata, CardType, Excavate, ExcavationClass,
    ExcavationProfile, Game, GenerationContext, PlayCard, PlayerSetup, Registry, ResolutionError,
    ResolutionLimitExceeded, Ruleset, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone,
    CastSpell, RewindSpec, Keyword, SpellRepeatSpec, excavation_count)
from hs_sim.engine.model import Rarity
from hs_sim.engine.effects import (AddToHand, ChoiceOption, Damage, Destroy, GainArmor, RequestChoice,
    ReplaceHero, ReturnToHand, Silence, Transform)
from hs_sim.engine.pools import PoolCard, PoolDefinition, PoolMember
from hs_sim.engine.excavate import PLAYABLE_CLASSES
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class ExcavateTests(unittest.TestCase):
    def setUp(self):
        self.r=Registry('excavate-tests-v1')
        for cls in PLAYABLE_CLASSES:
            self.r.register_card(CardDefinition(cls.value,cls.value,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))
        self.r.register_card(CardDefinition('unknown','unknown',CardType.HERO,health=30))
        for cid,rarity in (('common',Rarity.COMMON),('common2',Rarity.COMMON),('rare',Rarity.RARE),
                           ('epic',Rarity.EPIC),('legend',Rarity.LEGENDARY),('legend2',Rarity.LEGENDARY)):
            card=CardDefinition(cid,cid,CardType.MINION,cost=2,attack=2,health=3,
                metadata=CardMetadata(False,(CardClass.NEUTRAL,),rarity,tribes=()))
            self.r.register_card(card);self.r.register_pool_card(PoolCard.from_definition(card))
        for pool,members in (('one',('common','common2')),('two',('rare',)),('three',('epic',)),
                             ('four',('legend',)),('rogue-four',('legend2',))):
            self.r.register_pool(PoolDefinition(pool,'v1','t','experimental',tuple(PoolMember(x) for x in members)))
        self.profile=ExcavationProfile('excavate','v1','t','experimental',('one','two','three'),tuple(
            ExcavationClass(cls,'four' if cls==CardClass.MAGE else 'rogue-four' if cls==CardClass.ROGUE else None)
            for cls in sorted(PLAYABLE_CLASSES)))
        self.r.register_excavation_profile(self.profile)

    def script(self,fn=None,name='script',kind=CardType.SPELL,**fields):
        self.r.register_behavior(name,fn or (lambda c:[Excavate(c.player_id,c.source_id)]))
        if kind==CardType.MINION:fields.setdefault('health',3)
        self.r.register_card(CardDefinition(name,name,kind,on_play=name,**fields))

    def game(self,hand=('script',),hero='mage',enemy='druid',board=(),enemy_board=(),context=True,rules=None):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,mana=10,max_mana=10),
            PlayerSetup(enemy,board=enemy_board)),seed=55,generation_context=GenerationContext('t','experimental') if context else None),self.r,rules)

    def play(self,g,name='script'):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==name)
        g.apply(PlayCard(1,source));return source

    def choose(self,g,index=0):
        ch=g.state.pending_choice;g.apply(SelectChoice(ch.player_id,ch.id,(ch.options[index].id,)))

    def check(self,g):
        s=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(s,self.r).snapshot(),s)
        self.assertEqual(g.clone().snapshot(),s);self.assertEqual(replay(build_replay(g),self.r).snapshot(),s)

    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(e.exception))

    def watcher(self,name,fn,event='excavated'):
        self.r.register_behavior(name,fn)
        self.r.register_card(CardDefinition(name,name,CardType.MINION,health=8,triggers=(TriggerSpec(event,name),)))

    def test_four_tier_cycle_and_lifetime_count_are_separate(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=9)]);g=self.game();self.play(g)
        self.assertEqual([x.tier for x in g.state.excavation_history],[1,2,3,4,1,2,3,4,1])
        self.assertEqual([x.cycle for x in g.state.excavation_history],[1]*4+[2]*4+[3])
        self.assertEqual(excavation_count(g.state,1),9);self.check(g)

    def test_three_tier_classes_restart_without_a_fake_legendary(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=7)]);g=self.game(hero='druid');self.play(g)
        self.assertEqual([x.tier for x in g.state.excavation_history],[1,2,3,1,2,3,1]);self.check(g)

    def test_both_players_have_independent_progress(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=2),Excavate(2,c.source_id,count=4)])
        g=self.game();self.play(g);self.assertEqual((excavation_count(g.state,1),excavation_count(g.state,2)),(2,4))
        self.assertEqual(g.observe(2)['players'][1]['excavation'],{'count':4,'cycle':2,'depth':1});self.check(g)

    def test_full_hand_burns_rewards_but_still_advances_each_tier(self):
        self.script(lambda c:[AddToHand(1,'common'),Excavate(1,c.source_id,count=5)])
        g=self.game(hand=('script',)+('common',)*9);self.play(g)
        self.assertTrue(all(x.burned for x in g.state.excavation_history));self.assertEqual(len(g.state.players[1].hand),10)
        self.assertEqual(g.state.excavation_history[-1].tier,1);self.check(g)

    def test_successful_rewards_have_distinct_entities_and_hand_acquisition(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=5)]);g=self.game();self.play(g)
        ids=[x.reward_id for x in g.state.excavation_history];self.assertEqual(len(set(ids)),5)
        self.assertTrue(all(g.state.entities[i].hand_entry_id for i in ids));self.assertFalse(g.state.draw_history);self.check(g)

    def test_source_destruction_between_iterations_does_not_cancel_batch(self):
        self.watcher('kill',lambda c:[Destroy(c.event.source_id)])
        self.script(lambda c:[Excavate(1,c.source_id,count=3)],kind=CardType.MINION)
        g=self.game(board=('kill',));source=self.play(g)
        self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD);self.assertEqual(excavation_count(g.state,1),3);self.check(g)

    def test_source_silence_or_bounce_does_not_reset_player_progress(self):
        for fn in (lambda c:[Silence(c.source_id)],lambda c:[ReturnToHand(c.source_id)]):
            self.setUp();self.script(lambda c:[Excavate(1,c.source_id),*fn(c),Excavate(1,c.source_id)],kind=CardType.MINION)
            g=self.game();self.play(g);self.assertEqual([x.tier for x in g.state.excavation_history],[1,2]);self.check(g)

    def test_hero_class_changes_choose_current_legendary_without_resetting_count(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=3),ReplaceHero(1,'rogue'),Excavate(1,c.source_id)])
        g=self.game();self.play(g);record=g.state.excavation_history[-1]
        self.assertEqual((record.tier,record.card_id,record.hero_class),(4,'legend2',CardClass.ROGUE));self.check(g)

    def test_class_without_fourth_tier_restarts_after_pending_fourth(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=3),ReplaceHero(1,'druid'),Excavate(1,c.source_id)])
        g=self.game();self.play(g);record=g.state.excavation_history[-1]
        self.assertEqual((record.tier,record.cycle,record.count_before),(1,2,3));self.check(g)

    def test_completed_three_tier_cycle_is_not_reopened_by_class_change(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=3),ReplaceHero(1,'mage'),Excavate(1,c.source_id)])
        g=self.game(hero='druid');self.play(g);self.assertEqual((g.state.excavation_history[-1].tier,g.state.excavation_history[-1].cycle),(1,2));self.check(g)

    def test_class_change_mid_batch_uses_new_class_after_each_reaction(self):
        self.watcher('change',lambda c:[ReplaceHero(1,'rogue')] if c.event.amount==3 else [])
        self.script(lambda c:[Excavate(1,c.source_id,count=4)]);g=self.game(board=('change',));self.play(g)
        self.assertEqual(g.state.excavation_history[-1].card_id,'legend2');self.check(g)

    def test_nested_excavation_reaction_uses_committed_progress(self):
        self.watcher('extra',lambda c:[Excavate(1,c.source_id)] if c.event.amount==1 else [])
        self.script(lambda c:[Excavate(1,c.source_id,count=2)]);g=self.game(board=('extra',));self.play(g)
        self.assertEqual([x.tier for x in g.state.excavation_history],[1,2,3]);self.check(g)

    def test_hand_entry_reaction_changes_capacity_before_next_reward(self):
        self.watcher('bounce',lambda c:[ReturnToHand(c.source_id)],'card_added_to_hand')
        self.script(lambda c:[Excavate(1,c.source_id,count=2)]);g=self.game(hand=('script',)+('common',)*8,board=('bounce',));self.play(g)
        self.assertEqual([x.burned for x in g.state.excavation_history],[False,True]);self.check(g)

    def test_source_free_effect_uses_player_progress_without_inventing_source(self):
        self.script(lambda c:[Excavate(2,count=2)]);g=self.game();self.play(g)
        self.assertTrue(all(x.source_id is None for x in g.state.excavation_history));self.check(g)

    def test_unknown_class_errors_without_reward_count_or_rng_changes(self):
        self.script();g=self.game(hero='unknown');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_generation_context_errors_instead_of_guessing_pool(self):
        self.script();g=self.game(context=False);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_zero_count_does_not_consume_rng_or_require_context(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=0)]);g=self.game(context=False);rng=g.snapshot()['rng_state'];self.play(g)
        self.assertFalse(g.state.excavation_history);self.assertEqual(g.snapshot()['rng_state'],rng);self.check(g)

    def test_invalid_effect_fields_rejected(self):
        for fn in (lambda:Excavate(True),lambda:Excavate(1,count=-1),lambda:Excavate(1,count=True),
                   lambda:Excavate(1,source_id=0),lambda:Excavate(1,profile_id='')):
            with self.subTest(fn=fn),self.assertRaises(ValueError):fn()

    def test_unknown_profile_rolls_back(self):
        self.script(lambda c:[Excavate(1,profile_id='missing')]);g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_missing_candidate_implementation_is_never_filtered_before_random(self):
        meta=CardMetadata(False,(CardClass.NEUTRAL,),Rarity.COMMON)
        self.r.register_pool_card(PoolCard('missing',CardType.SPELL,1,meta))
        self.r.register_pool(PoolDefinition('bad','v1','t','experimental',(PoolMember('common',1000),PoolMember('missing'))))
        self.r.register_excavation_profile(replace(self.profile,id='bad',shared_pools=('bad','two','three')))
        self.script(lambda c:[Excavate(1,profile_id='bad')]);g=self.game();before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition'):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_empty_pool_does_not_advance(self):
        self.r.register_pool(PoolDefinition('empty','v1','t','experimental',()))
        self.r.register_excavation_profile(replace(self.profile,id='bad',shared_pools=('empty','two','three')))
        self.script(lambda c:[Excavate(1,profile_id='bad')]);g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_explicit_exclusion_is_respected(self):
        self.r.register_pool(PoolDefinition('excluded','v1','t','experimental',(PoolMember('common'),PoolMember('common2')),('common',)))
        self.r.register_excavation_profile(replace(self.profile,id='x',shared_pools=('excluded','two','three')))
        self.script(lambda c:[Excavate(1,profile_id='x')]);g=self.game();self.play(g)
        self.assertEqual(g.state.excavation_history[0].card_id,'common2');self.check(g)

    def test_cannot_change_progress_profile_mid_match(self):
        self.r.register_excavation_profile(replace(self.profile,id='other'))
        self.script(lambda c:[Excavate(1),Excavate(1,profile_id='other')]);g=self.game();before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_profile_requires_all_classes_without_implicit_missing_class_fallback(self):
        with self.assertRaises(ValueError):replace(self.profile,classes=self.profile.classes[:-1])
        with self.assertRaises(ValueError):replace(self.profile,classes=self.profile.classes[:-1]+(self.profile.classes[0],))

    def test_profile_requires_three_distinct_shared_pools(self):
        with self.assertRaises(ValueError):replace(self.profile,shared_pools=('one','two'))
        with self.assertRaises(ValueError):replace(self.profile,shared_pools=('one','one','three'))

    def test_profile_rarity_mismatch_is_rejected_during_freeze(self):
        self.r.register_excavation_profile(replace(self.profile,id='bad',shared_pools=('two','one','three')))
        with self.assertRaisesRegex(ValueError,'rarity'):self.r.freeze()

    def test_profile_wrong_target_pool_is_rejected(self):
        self.r.register_excavation_profile(replace(self.profile,target_id='other'))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_formal_profile_requires_completeness_and_complete_pools(self):
        with self.assertRaises(ValueError):replace(self.profile,mode='standard')
        self.r.register_excavation_profile(replace(self.profile,id='complete',complete=True))
        with self.assertRaises(ValueError):self.r.freeze()

    def test_profile_is_immutable_and_part_of_registry_fingerprint(self):
        before=self.r.fingerprint();self.r.register_excavation_profile(replace(self.profile,id='second'))
        self.assertNotEqual(self.r.fingerprint(),before);self.r.freeze()
        with self.assertRaises(ValueError):self.r.register_excavation_profile(replace(self.profile,id='third'))
        with self.assertRaises(TypeError):self.r.excavation_profiles[self.profile.key]=self.profile

    def test_duplicate_profile_rejected(self):
        with self.assertRaises(ValueError):self.r.register_excavation_profile(self.profile)

    def test_suspension_after_reward_preserves_progress_and_remaining_batch(self):
        self.watcher('choose',lambda c:[RequestChoice(1,(ChoiceOption('x','x',(GainArmor(1,1),)),),source_id=c.source_id)])
        self.script(lambda c:[Excavate(1,c.source_id,count=2)]);g=self.game(board=('choose',));self.play(g)
        self.assertEqual(excavation_count(g.state,1),1);self.check(g);self.choose(g)
        self.assertEqual(excavation_count(g.state,1),2);self.check(g);self.choose(g);self.check(g)

    def test_lethal_reaction_stops_remaining_batch(self):
        self.watcher('lethal',lambda c:[Damage(c.state.players[2].hero_id,50)])
        self.script(lambda c:[Excavate(1,c.source_id,count=4)]);g=self.game(board=('lethal',));self.play(g)
        self.assertEqual(excavation_count(g.state,1),1);self.assertEqual(g.state.status,'finished');self.check(g)

    def test_late_callback_error_rolls_back_all_rewards(self):
        def error(c):raise ValueError('later failure')
        self.watcher('error',error);self.script();g=self.game(board=('error',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_budget_exhaustion_restores_rewards_progress_and_rng(self):
        self.script(lambda c:[Excavate(1,count=20)]);g=self.game(rules=Ruleset(max_resolution_steps=25));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_oversized_batch_rejected_before_random(self):
        self.script(lambda c:[Excavate(1,count=1000)]);g=self.game(rules=Ruleset(max_resolution_steps=80));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g)
        self.assertEqual(g.snapshot(),before)

    def test_automatic_cast_and_repeat_each_excavate(self):
        self.script();self.script(lambda c:[CastSpell(1,'script',c.source_id)],'auto')
        g=self.game(hand=('auto',));self.play(g,'auto');self.assertEqual(excavation_count(g.state,1),1);self.check(g)
        self.setUp();self.script();self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=4,
            spell_repeats=(SpellRepeatSpec(class_mode='any'),)))
        g=self.game(board=('aura',));self.play(g);self.assertEqual(excavation_count(g.state,1),2);self.check(g)

    def test_rewind_replaces_reward_without_double_counting_progress(self):
        self.script(keywords=(Keyword.REWIND,),rewind=RewindSpec());g=self.game();self.play(g)
        self.assertEqual(excavation_count(g.state,1),1)
        ch=g.state.pending_choice;retry=next(o.id for o in ch.options if 'retry' in o.id)
        g.apply(SelectChoice(1,ch.id,(retry,)));self.assertEqual(excavation_count(g.state,1),1);self.check(g)

    def test_retained_rewind_advances_twice_instead_of_overwriting_progress(self):
        self.script(keywords=(Keyword.REWIND,),rewind=RewindSpec())
        self.r.register_card(CardDefinition('aura','aura',CardType.MINION,health=4,retain_rewind_outcomes=True))
        g=self.game(board=('aura',));self.play(g);self.assertEqual([x.tier for x in g.state.excavation_history],[1,2]);self.check(g)

    def test_private_reward_identity_is_not_in_public_progress(self):
        self.script();g=self.game();self.play(g)
        event=next(e for e in g.player_events(2) if e['kind']=='excavated')
        self.assertEqual(event['excavation'],{'cycle':1,'tier':1,'maximum':4});self.assertIsNone(event['target'])
        self.assertNotIn('card_id',event['excavation'])
        self.assertTrue(all(x['card_id'] is None for x in g.observe(2)['players'][0]['hand']))
        self.assertNotIn('excavation_history',json.dumps(g.observe(2)));self.check(g)

    def test_deathrattle_can_excavate_after_source_death(self):
        self.r.register_behavior('dig',lambda c:[Excavate(c.player_id,c.source_id)])
        self.r.register_card(CardDefinition('miner','miner',CardType.MINION,health=2,deathrattle='dig'))
        self.script(lambda c:[Destroy(c.state.players[1].board[0])]);g=self.game(board=('miner',));self.play(g)
        self.assertEqual(excavation_count(g.state,1),1);self.check(g)

    def test_unknown_fourth_reward_preserves_previously_accepted_progress(self):
        self.r.register_pool_card(PoolCard('missing',CardType.MINION,4,CardMetadata(False,(CardClass.MAGE,),Rarity.LEGENDARY)))
        self.r.register_pool(PoolDefinition('missing-four','v1','t','experimental',(PoolMember('missing'),)))
        self.r.register_excavation_profile(replace(self.profile,id='missing',classes=tuple(
            replace(c,legendary_pool_id='missing-four') if c.hero_class==CardClass.MAGE else c for c in self.profile.classes)))
        self.script(lambda c:[Excavate(1,c.source_id,count=3,profile_id='missing')],'three')
        self.script(lambda c:[Excavate(1,c.source_id,profile_id='missing')]);g=self.game(hand=('three','script'));self.play(g,'three');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'unsupported card definition'):self.play(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(excavation_count(g.state,1),3)

    def test_failure_after_suspension_keeps_previously_committed_reward(self):
        self.watcher('choose',lambda c:[RequestChoice(1,(ChoiceOption('x','x',(Excavate(1,profile_id='missing'),)),),source_id=c.source_id)])
        self.script();g=self.game(board=('choose',));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.assertEqual(excavation_count(g.state,1),1)

    def test_batch_clone_random_choices_and_progress_replay_exactly(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=9)]);g=self.game();clone=g.clone();self.play(g);self.play(clone)
        self.assertEqual(g.snapshot(),clone.snapshot());self.check(g)

    def test_treasure_draw_and_play_are_not_additional_excavations(self):
        from hs_sim.engine.effects import Draw
        self.script(lambda c:[Excavate(1,c.source_id),Draw(1)]);g=self.game();self.play(g)
        reward=g.state.players[1].hand[0];g.apply(PlayCard(1,reward));self.assertEqual(excavation_count(g.state,1),1);self.check(g)

    def test_progress_history_survives_generated_minion_play_and_transform(self):
        self.script();self.script(lambda c:[Transform(c.state.players[1].board[0],'epic')],'transform')
        g=self.game(hand=('script','transform'));self.play(g);reward=g.state.players[1].hand[-1]
        g.apply(PlayCard(1,reward));self.play(g,'transform');self.assertEqual(excavation_count(g.state,1),1);self.check(g)

    def test_snapshot_rejects_false_counts_tiers_pools_sources_and_reward_ids(self):
        self.script(lambda c:[Excavate(1,c.source_id,count=2)]);g=self.game();self.play(g)
        for field,value in (('count_before',9),('tier',3),('maximum',3),('cycle',4),('pool_id','three'),
                ('profile_version','wrong'),('source_id',999999),('reward_id',g.state.players[1].hero_id),('burned',True)):
            with self.subTest(field=field):s=g.snapshot();s['state']['excavation_history'][0][field]=value;self.reject(s)

    def test_snapshot_rejects_context_mismatch_and_missing_history(self):
        self.script();g=self.game();self.play(g);s=g.snapshot();s['generation_context']=None;self.reject(s)
        s=g.snapshot();del s['state']['excavation_history'];self.reject(s)

    def test_progress_on_opponent_turn_and_player_command_replay(self):
        self.script(lambda c:[Excavate(2,c.source_id)])
        g=self.game();port=g.for_player(1);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(excavation_count(g.state,2),1);self.check(g)


class ExcavateRepresentativeTests(unittest.TestCase):
    def setUp(self):
        from hs_sim.engine.representative import build_registry
        self.r=build_registry()
        for cls in PLAYABLE_CLASSES:
            self.r.register_card(CardDefinition('test-'+cls.value,cls.value,CardType.HERO,health=30,
                metadata=CardMetadata(False,(cls,),None)))

    def game(self,hand=('WW_001',)*5,hero='test-rogue',board=(),enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup(hero,hand=hand,board=board,mana=10,max_mana=10,
            hero_power_card_id=self.r.card(hero).initial_hero_power),
            PlayerSetup('HERO_01',board=enemy)),seed=55,generation_context=GenerationContext('local-2026-09-23','experimental')),self.r)

    def play(self,g,cid='WW_001',target=None):
        source=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,source,target));return source

    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())

    def test_rogue_progress_grants_named_tiers_and_cycles(self):
        g=self.game()
        for _ in range(5):self.play(g)
        self.assertEqual([x.card_id for x in g.state.excavation_history],['WW_001t18','WW_001t5','WW_001t17','WW_001t23','WW_001t18'])
        self.assertEqual(g.state.players[1].mana,0);self.check(g)

    def test_hunter_explicitly_has_three_tier_cycle(self):
        g=self.game(hero='test-hunter')
        for _ in range(4):self.play(g)
        self.assertEqual([x.tier for x in g.state.excavation_history],[1,2,3,1]);self.check(g)

    def test_all_seven_class_rewards_delivered_at_fourth_without_fallback(self):
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS
        for cls,cid in EXCAVATE_CLASS_REWARDS.items():
            with self.subTest(cls=cls):
                g=self.game(hero='test-'+cls.value)
                for _ in range(4):self.play(g)
                self.assertEqual(g.state.excavation_history[-1].card_id,cid)
                self.assertIn(cid,[g.state.entities[i].card_id for i in g.state.players[1].hand])
                self.assertEqual(excavation_count(g.state,1),4);self.check(g)

    def test_pouch_grants_two_coins_without_excavating(self):
        g=self.game(hand=('WW_001t18',));self.play(g,'WW_001t18')
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[1].hand],['GAME_005','GAME_005'])
        self.assertEqual(excavation_count(g.state,1),0);self.check(g)

    def test_stalactite_uses_spell_damage_for_minion_and_opponent_hero(self):
        g=self.game(hand=('WW_001t5',),board=('EX1_012',),enemy=('CS2_182',))
        target=g.state.players[2].board[0];self.play(g,'WW_001t5',target)
        self.assertEqual(g.state.entities[target].health,1)
        self.assertEqual(g.state.entities[g.state.players[2].hero_id].health,26);self.check(g)

    def test_drake_keywords_are_live_after_treasure_play(self):
        g=self.game(hand=('WW_001t17',));entity=self.play(g,'WW_001t17')
        self.assertTrue({Keyword.RUSH,Keyword.DIVINE_SHIELD,Keyword.LIFESTEAL} <= g.state.entities[entity].keywords);self.check(g)

    def test_scorpion_uses_lifetime_count_after_cycle_restarts(self):
        from hs_sim.engine.effects import RefreshMana
        self.r.register_behavior('dig5',lambda c:[Excavate(1,c.source_id,count=5)])
        self.r.register_card(CardDefinition('dig5','dig5',CardType.SPELL,on_play='dig5'))
        g=self.game(hand=('dig5','WW_001t23'));self.play(g,'dig5');self.play(g,'WW_001t23')
        generated=[g.state.entities[e.target_id] for e in g.events if e.kind=='card_added_to_hand'][-4:]
        self.assertEqual(len(generated),4)
        for card in generated:self.assertEqual(card.cost,max(1,self.r.card(card.card_id).cost-5))
        self.assertEqual(excavation_count(g.state,1),5);self.check(g)

    def test_declared_class_rewards_now_have_explicit_adapters(self):
        from hs_sim.engine.representative import EXCAVATE_CLASS_REWARDS
        missing=set(EXCAVATE_CLASS_REWARDS.values())-set(self.r.cards)
        self.assertEqual(missing,set())
        self.assertTrue(set(EXCAVATE_CLASS_REWARDS.values()) <= set(self.r.pool_cards))

    def test_basic_rogue_hero_uses_rogue_progress_and_initial_dagger_power(self):
        g=self.game(hero='HERO_03');self.play(g)
        self.assertEqual(g.state.excavation_history[0].hero_class,CardClass.ROGUE)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id,'HERO_03bp');self.check(g)


if __name__=='__main__':unittest.main()
