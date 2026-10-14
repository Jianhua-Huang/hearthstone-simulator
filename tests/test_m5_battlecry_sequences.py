"""Direct payload caps, independent selection/order, and saved progress."""
import json
import random
import unittest
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, Scenario, PlayerSetup, PlayCard,
    PlayedBattlecryQuery, PlayedBattlecryFilter, PlayedBattlecryCandidate,
    played_battlecry_payloads, RepeatPlayedBattlecrySequence, BattlecryRepeatSpec,
    AddBattlecryRepeatModifier, RewindSpec, Keyword, EndTurn, Ruleset, TargetSpec,
    ResolutionError, LaunchStarship, TriggerBattlecry, RepeatPlayedBattlecries)
from hs_sim.engine.effects import (GainArmor, Damage, DamageBatch, Destroy, Transform,
    ChangeControl, ReturnToHand, Silence, Summon, InvokeBehavior)
from hs_sim.engine.battlecry_sequences import ContinueBattlecrySequence
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.replay import build_replay, replay


class BattlecrySequenceTests(unittest.TestCase):
    setUp=foundation.BattlecryTests.setUp
    card=foundation.BattlecryTests.card
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    game=foundation.BattlecryTests.game
    play=foundation.BattlecryTests.play
    choose=foundation.BattlecryTests.choose
    pause=foundation.BattlecryTests.pause
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def sequence(self,name='sequence',limit=2,*,card_options=None,**kw):
        self.card(name,lambda c:[RepeatPlayedBattlecrySequence(c.player_id,c.source_id,limit,**kw)],**(card_options or {}))

    def children(self,g): return [b for b in g.state.battlecry_history if b.origin=='played_history']

    def pending(self,**kw):
        self.card('wait',lambda c:[self.pause(c),GainArmor(1,3)])
        self.sequence(choices='player',**kw)
        g=self.game(hand=('wait','cry','sequence'));self.play(g,'wait');self.choose(g);self.play(g);self.play(g,'sequence')
        self.assertIsNotNone(g.state.pending_choice);return g

    def fields(self,s):return self.nested(s['resolution_frame'],'ContinueBattlecrySequence')['fields']

    def test_one_attempt_per_payload_has_no_extra_payment_or_play(self):
        self.sequence(limit=1);g=self.game(hand=('cry','sequence'));self.play(g);source=self.play(g,'sequence')
        b=self.children(g)[0]
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(4,6,2))
        self.assertEqual((b.source_id,b.card_id,b.payload.card_id,b.history_play_id,b.parent_id),(source,'sequence','cry',1,2));self.check(g)

    def test_cap_truncates_direct_payloads(self):
        self.sequence(limit=1);g=self.game(hand=('cry','cry','sequence'));self.play(g);self.play(g);self.play(g,'sequence')
        self.assertEqual([b.history_play_id for b in self.children(g)],[1]);self.assertEqual(self.armor(g),6);self.check(g)

    def test_limit_zero_and_empty_history_do_not_consume_rng(self):
        self.sequence('zero',limit=0);self.sequence('empty',limit=20)
        for hand in (('cry','zero'),('empty',)):
            g=self.game(hand=hand)
            if hand[0]=='cry':self.play(g)
            before=g._rng.getstate();self.play(g,hand[-1]);self.assertEqual(before,g._rng.getstate());self.assertFalse(self.children(g));self.check(g)

    def test_large_rule_cap_does_not_fail_when_actual_candidates_are_few(self):
        self.sequence(limit=10**6);g=self.game(hand=('cry','sequence'));self.play(g);self.play(g,'sequence')
        self.assertEqual(len(self.children(g)),1);self.check(g)

    def test_newest_selection_preserves_chronological_order_within_suffix(self):
        self.sequence(selection='newest');g=self.game(hand=('cry','cry','cry','sequence'))
        for _ in range(3):self.play(g)
        self.play(g,'sequence');self.assertEqual([b.history_play_id for b in self.children(g)],[2,3]);self.check(g)

    def test_prefix_random_order_and_full_random_subset_are_distinct(self):
        self.sequence('prefix',selection='oldest',order='random');self.sequence('sample',selection='random',order='random')
        for name in ('prefix','sample'):
            g=self.game(hand=('cry','cry','cry',name))
            for _ in range(3):self.play(g)
            rng=random.Random();rng.setstate(g._rng.getstate())
            expected=[0,1] if name=='prefix' else sorted(rng.sample(tuple(range(3)),2))
            expected=rng.sample(tuple(expected),2)
            self.play(g,name);self.assertEqual([b.history_play_id for b in self.children(g)],[i+1 for i in expected])
            self.assertEqual(g._rng.getstate(),rng.getstate());self.check(g)

    def test_random_subset_can_execute_chronologically(self):
        self.sequence(selection='random');g=self.game(hand=('cry','cry','cry','sequence'))
        for _ in range(3):self.play(g)
        rng=random.Random();rng.setstate(g._rng.getstate());expected=sorted(rng.sample((0,1,2),2))
        self.play(g,'sequence');self.assertEqual([b.history_play_id for b in self.children(g)],[i+1 for i in expected]);self.check(g)

    def test_repeated_same_card_is_not_deduplicated(self):
        self.sequence();g=self.game(hand=('cry','cry','sequence'));self.play(g);self.play(g)
        candidates=played_battlecry_payloads(g.state,1);self.assertEqual([c.play_id for c in candidates],[1,2])
        self.play(g,'sequence');self.assertEqual(len(self.children(g)),2);self.assertEqual(self.armor(g),8);self.check(g)

    def test_filters_distinguish_played_declaring_and_behavior_identity(self):
        self.card('alias');g=self.game(hand=('cry','alias'));self.play(g);self.play(g,'alias')
        for filters,expected in ((PlayedBattlecryFilter(exclude_played_cards=('cry',)),[2]),
            (PlayedBattlecryFilter(exclude_declaring_cards=('alias',)),[1]),
            (PlayedBattlecryFilter(exclude_behaviors=('armor',)),[])):
            self.assertEqual([c.play_id for c in played_battlecry_payloads(g.state,1,filters=filters)],expected)

    def test_explicit_self_behavior_exclusion_prevents_prior_sequence_recursion(self):
        self.sequence(filters=PlayedBattlecryFilter(exclude_behaviors=('sequence',)))
        g=self.game(hand=('cry','sequence','sequence'));self.play(g);self.play(g,'sequence');self.play(g,'sequence')
        self.assertEqual([b.history_play_id for b in self.children(g)],[1,1]);self.assertEqual(self.armor(g),6);self.check(g)

    def test_query_owner_turn_kind_and_exclusions_apply_before_cap(self):
        self.card('weapon',kind=CardType.WEAPON);self.sequence(query=PlayedBattlecryQuery(kinds=(CardType.WEAPON,)))
        g=self.game(hand=('cry','weapon','sequence'));self.play(g);self.play(g,'weapon');self.play(g,'sequence')
        self.assertEqual([b.history_play_id for b in self.children(g)],[2]);self.assertEqual(played_battlecry_payloads(g.state,2),())
        self.assertEqual(played_battlecry_payloads(g.state,1,PlayedBattlecryQuery(turn=99)),())
        self.assertEqual(played_battlecry_payloads(g.state,1,PlayedBattlecryQuery(before_id=2,exclude_ids=(1,))),());self.check(g)

    def test_generic_on_play_is_not_a_battlecry_candidate(self):
        self.r.register_card(CardDefinition('generic','generic',CardType.MINION,health=4,on_play='armor'))
        self.sequence();g=self.game(hand=('generic','sequence'));self.play(g,'generic');self.play(g,'sequence')
        self.assertFalse(self.children(g));self.assertEqual(self.armor(g),2);self.check(g)

    def test_no_target_attempt_consumes_cap_and_does_not_refill(self):
        self.card('hurt',lambda c:[Damage(c.target_id,10,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.sequence(limit=1);g=self.game(hand=('hurt','cry','sequence'),enemy=('body',))
        self.play(g,'hurt',g.state.players[2].board[0]);self.play(g);self.play(g,'sequence')
        children=self.children(g);self.assertEqual(len(children),1);self.assertEqual(children[0].failure,'no_target')
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_targets_reselected_against_current_board(self):
        self.card('hurt',lambda c:[Damage(c.target_id,3,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        self.sequence();g=self.game(hand=('hurt','hurt','sequence'),enemy=('body','body'))
        a,b=g.state.players[2].board;self.play(g,'hurt',a);self.play(g,'hurt',b);self.play(g,'sequence')
        self.assertFalse(g.state.players[2].board);self.assertEqual({x.target_id for x in self.children(g)},{a,b});self.check(g)

    def test_pause_restore_keeps_schedule_and_attempt_progress(self):
        g=self.pending();self.check(g);s=g.snapshot();saved=Game.from_snapshot(json.loads(json.dumps(s)),self.r)
        self.choose(g);self.choose(saved);self.assertEqual(saved.snapshot(),g.snapshot())
        self.assertEqual((self.armor(g),[b.history_play_id for b in self.children(g)]),(10,[1,2]));self.check(g)

    def test_random_choice_inside_payload_uses_existing_automatic_policy(self):
        self.card('wait',lambda c:[self.pause(c),GainArmor(1,3)]);self.sequence()
        g=self.game(hand=('wait','sequence'));self.play(g,'wait');self.choose(g);self.play(g,'sequence')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(self.armor(g),6);self.check(g)

    def test_brann_repeats_sequence_but_does_not_double_each_child(self):
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        self.sequence(limit=1);g=self.game(hand=('cry','sequence'),board=('brann',));self.play(g);self.play(g,'sequence')
        self.assertEqual((self.armor(g),len(self.children(g)),len(g.state.play_history)),(8,2,2));self.check(g)

    def test_finite_player_policy_consumed_once_by_outer_hand_play(self):
        self.script('grant',lambda c:[AddBattlecryRepeatModifier(1,BattlecryRepeatSpec(3),uses=1)])
        self.sequence(limit=1);g=self.game(hand=('cry','grant','sequence'));self.play(g);self.play(g,'grant');self.play(g,'sequence')
        self.assertEqual(len(self.children(g)),3);self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_terminal_stops_remaining_schedule(self):
        self.card('hurt',lambda c:[Damage(c.state.players[2].hero_id,20,c.source_id)]);self.sequence()
        g=self.game(hand=('hurt','cry','sequence'));self.play(g,'hurt');self.play(g);self.play(g,'sequence')
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(self.children(g)),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_postpause_error_rolls_back_choice_and_sequence_progress(self):
        self.r.register_behavior('later',lambda c:[Summon(1,'missing')] if c.battlecry.origin!='hand' else [])
        self.card('bad',lambda c:[self.pause(c),InvokeBehavior('later',c.source_id,1)]);self.sequence(choices='player')
        g=self.game(hand=('bad','cry','sequence'));self.play(g,'bad');self.choose(g);self.play(g);self.play(g,'sequence');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_player_port_resumes_without_exposing_private_plan(self):
        g=self.pending()
        for player in (1,2):
            text=json.dumps((g.observe(player),g.player_events(player)))
            for private in ('ContinueBattlecrySequence','before_play_id','started_ids','candidates','history_play_id','behavior_id'):
                self.assertNotIn(private,text)
        port=g.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
        self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted']);self.check(g)

    def test_invalid_spec_rejects_bool_negative_and_ambiguous_policies(self):
        for kw in ({'limit':True},{'limit':-1},{'selection':'all'},{'order':'newest'},{'choices':'guess'},{'query':None},{'filters':None}):
            args=dict(player_id=1,source_id=1,limit=20);args.update(kw)
            with self.subTest(kw=kw),self.assertRaises(ValueError):RepeatPlayedBattlecrySequence(**args)

    def test_invalid_filters_and_candidates_are_rejected(self):
        for make in (lambda:PlayedBattlecryFilter(exclude_behaviors=['armor']),lambda:PlayedBattlecryFilter(exclude_played_cards=('cry','cry')),
            lambda:PlayedBattlecryFilter(exclude_declaring_cards=('',)),lambda:PlayedBattlecryCandidate(True,None)):
            with self.assertRaises(ValueError):make()

    def test_restore_rejects_cap_shortening_or_expansion(self):
        g=self.pending()
        for cap in (0,1,True):
            s=g.snapshot();self.fields(s)['spec']['fields']['limit']=cap;self.reject(s)

    def test_restore_rejects_duplicate_or_unknown_schedule_positions(self):
        g=self.pending()
        for order in ([0,0],[0,99],[0],[-1,1]):
            s=g.snapshot();self.fields(s)['order']['tuple']=order;self.reject(s)

    def test_restore_rejects_changed_chronological_order(self):
        g=self.pending();s=g.snapshot();self.fields(s)['order']['tuple']=[1,0];self.reject(s)

    def test_restore_rejects_wrong_owner(self):
        g=self.pending();s=g.snapshot();self.fields(s)['spec']['fields']['player_id']=2;self.reject(s)

    def test_restore_rejects_forged_candidate_payload(self):
        g=self.pending();s=g.snapshot();self.fields(s)['candidates']['tuple'][0]['fields']['payload']['fields']['ability_id']=99999;self.reject(s)

    def test_restore_rejects_removed_candidate_even_when_schedule_is_shortened(self):
        g=self.pending();s=g.snapshot();f=self.fields(s);f['candidates']['tuple'].pop();f['order']['tuple']=[0];self.reject(s)

    def test_restore_rejects_future_frontiers_and_parent(self):
        g=self.pending()
        for name in ('before_play_id','before_battlecry_id','parent_id'):
            s=g.snapshot();self.fields(s)[name]=99999;self.reject(s)

    def test_restore_rejects_unrelated_or_duplicated_progress(self):
        g=self.pending()
        for ids in ([1],[99999],[4,4],[4,1]):
            s=g.snapshot();self.fields(s)['started_ids']['tuple']=ids;self.reject(s)

    def test_restore_rejects_changed_carrier_identity(self):
        g=self.pending();s=g.snapshot();self.fields(s)['card_id']='body';self.reject(s)

    def test_lifecycle_changes_do_not_replace_accepted_carrier_or_player(self):
        operations={'silence':lambda c:Silence(c.source_id),'death':lambda c:Destroy(c.source_id),
            'morph':lambda c:Transform(c.source_id,'body'),'bounce':lambda c:ReturnToHand(c.source_id),
            'transfer':lambda c:ChangeControl(c.source_id,2)}
        for name,operation in operations.items():
            self.card(name,lambda c,operation=operation:[operation(c)] if c.battlecry.origin!='hand' else [])
        self.sequence()
        for name in operations:
            with self.subTest(name=name):
                g=self.game(hand=(name,'cry','sequence'));self.play(g,name);self.play(g);source=self.play(g,'sequence')
                self.assertEqual(self.armor(g),4);self.assertEqual(len(self.children(g)),2)
                self.assertTrue(all(b.source_id==source and b.card_id=='sequence' and b.player_id==1 for b in self.children(g)));self.check(g)

    def test_original_history_source_death_does_not_remove_candidate(self):
        self.script('kill',lambda c:[Destroy(c.state.players[1].board[0])]);self.sequence(limit=1)
        g=self.game(hand=('cry','kill','sequence'));self.play(g);self.play(g,'kill');self.play(g,'sequence')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_nested_replays_have_independent_caps_and_do_not_expand_parent(self):
        from hs_sim.engine import battlecry_play_window
        self.card('macaw',lambda c:[RepeatPlayedBattlecries(1,c.source_id,
            PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry)))])
        self.sequence(limit=1,selection='newest');g=self.game(hand=('cry','macaw','sequence'))
        self.play(g);self.play(g,'macaw');self.play(g,'sequence')
        direct=[b for b in self.children(g) if b.parent_id==4]
        self.assertEqual(len(direct),1);self.assertEqual(direct[0].payload.card_id,'macaw')
        self.assertEqual([b.history_play_id for b in self.children(g)],[1,2,1]);self.assertEqual(self.armor(g),6);self.check(g)

    def test_countered_declarations_require_explicit_include(self):
        import test_m5_minion_counters as counters
        self.secret=counters.MinionCounterTests.secret.__get__(self);counters.MinionCounterTests.setUp(self)
        self.sequence('include',query=PlayedBattlecryQuery(countered='include'));self.sequence('exclude')
        for name,expected in (('include',2),('exclude',0)):
            g=self.game(hand=('arm','cry',name));self.play(g,'arm');self.play(g);self.play(g,name)
            self.assertEqual(self.armor(g),expected);self.check(g)

    def test_physical_trigger_has_no_hand_payment_and_uses_existing_history(self):
        self.sequence(limit=1)
        self.script('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[0]]),c.source_id)])
        g=self.game(hand=('cry','trigger'),board=('sequence',));self.play(g);self.play(g,'trigger')
        self.assertEqual((self.armor(g),len(g.state.play_history),g.state.players[1].mana),(4,2,8));self.check(g)

    def test_manual_and_retained_rewind_preserve_per_activation_caps(self):
        self.sequence(limit=1,card_options={'keywords':(Keyword.REWIND,),'rewind':RewindSpec(1)})
        for board in ((),('retainer',)):
            g=self.game(hand=('cry','sequence'),board=board);self.play(g);self.play(g,'sequence')
            if not board:self.check(g);self.choose(g,'retry')
            self.assertEqual(len(self.children(g)),2 if board else 1)
            self.assertEqual(len(g.state.play_history),2);self.check(g)

    def test_recursive_descendants_still_hit_engine_budget_and_rollback(self):
        self.sequence(limit=1,selection='newest')
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('sequence','sequence','sequence'),mana=10,max_mana=10),
            PlayerSetup('hero')),seed=73),self.r,ruleset=Ruleset(max_resolution_steps=100))
        self.play(g,'sequence');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'sequence')
        self.assertEqual(g.snapshot(),s);self.assertEqual(g.state.status,'playing');self.check(g)

    def test_composite_play_is_capped_by_payload_and_filters_preserve_other_components(self):
        from hs_sim.engine.representative import build_registry
        from hs_sim.engine.starships import construction
        r=build_registry()
        r.register_behavior('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        r.register_behavior('sequence',lambda c:[RepeatPlayedBattlecrySequence(1,c.source_id,1)])
        for cid in ('scrap','bounce'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        r.register_card(CardDefinition('sequence','sequence',CardType.MINION,health=4,battlecry='sequence'))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('SC_405','SC_405'),hand=('scrap','bounce','sequence'),
            deck=('CS2_182',)*6,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=('CS2_182',)*6)),seed=81),r)
        self.play(g,'scrap');ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));self.play(g,'bounce')
        g.apply(PlayCard(1,ship.id));original=g.state.play_history[-1]
        self.assertEqual(len(played_battlecry_payloads(g.state,1)),2)
        self.assertEqual(played_battlecry_payloads(g.state,1,filters=PlayedBattlecryFilter(exclude_declaring_cards=('SC_405',))),())
        self.assertEqual(len(played_battlecry_payloads(g.state,1,filters=PlayedBattlecryFilter(exclude_played_cards=('SC_405',)))),2)
        self.play(g,'sequence');children=self.children(g);self.assertEqual(len(children),1)
        self.assertEqual(children[0].payload,original.battlecries[0])
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())

    def test_restore_rejects_truncated_progress_at_second_paused_attempt(self):
        self.card('wait',lambda c:[self.pause(c)])
        self.sequence(choices='player');g=self.game(hand=('wait','wait','sequence'))
        self.play(g,'wait');self.choose(g);self.play(g,'wait');self.choose(g);self.play(g,'sequence');self.choose(g)
        self.check(g);s=g.snapshot();self.fields(s)['started_ids']['tuple']=[];self.reject(s)

    def test_restore_rejects_forged_current_attempt_marker(self):
        g=self.pending();s=g.snapshot();self.nested(s['resolution_frame'],'FinishSequenceAttempt')['fields']['record_id']=1;self.reject(s)

    def test_actual_twenty_cap_from_twenty_one_replayed_physical_entries(self):
        from examples.bounded_battlecries import run
        g,snapshot=run()
        self.assertEqual(len(self.children(g)),20);self.assertEqual(len(g.history),42)
        self.assertEqual(snapshot['schema_version'],265)

    def test_pause_after_child_completion_keeps_valid_completion_marker(self):
        self.watch('wait','battlecry_finished',lambda c:[self.pause(c)] if dict(c.event.data).get('battlecry_id')==4 else [])
        self.sequence();g=self.game(hand=('cry','cry','sequence'),board=('wait',))
        self.play(g);self.play(g);self.play(g,'sequence');self.assertIsNotNone(g.state.pending_choice)
        self.assertTrue(self.children(g)[0].completed);self.check(g);self.choose(g)
        self.assertEqual(self.armor(g),8);self.check(g)

    def test_sequence_outside_battlecry_has_no_parent_and_freezes_carrier(self):
        self.card('wait',lambda c:[self.pause(c)])
        self.script('trigger',lambda c:[RepeatPlayedBattlecrySequence(1,c.state.players[1].board[0],1,choices='player')])
        g=self.game(hand=('wait','trigger'));self.play(g,'wait');self.choose(g);self.play(g,'trigger')
        self.assertIsNone(self.children(g)[0].parent_id);self.check(g);self.choose(g);self.check(g)

    def test_nested_bounded_sequence_saves_both_independent_attempt_markers(self):
        self.card('wait',lambda c:[self.pause(c)])
        self.sequence('inner',limit=1,choices='player',query=PlayedBattlecryQuery(before_id=2))
        self.sequence('outer',limit=1,choices='player',selection='newest')
        g=self.game(hand=('wait','inner','outer'));self.play(g,'wait');self.choose(g);self.play(g,'inner');self.choose(g)
        self.play(g,'outer');self.check(g);s=g.snapshot();saved=Game.from_snapshot(s,self.r)
        self.choose(g);self.choose(saved);self.assertEqual(g.snapshot(),saved.snapshot())
        self.assertEqual([b.history_play_id for b in self.children(g)],[1,2,1]);self.check(g)

    def test_random_schedule_is_frozen_before_any_player_choice(self):
        self.card('wait',lambda c:[self.pause(c)]);self.sequence(choices='player',selection='random',order='random')
        g=self.game(hand=('wait','wait','wait','sequence'))
        for _ in range(3):self.play(g,'wait');self.choose(g)
        self.play(g,'sequence');saved=Game.from_snapshot(g.snapshot(),self.r);self.check(g)
        for match in (g,saved):
            while match.state.pending_choice:self.choose(match)
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(len(self.children(g)),2);self.check(g)

    def test_restore_rejects_reordered_completion_marker(self):
        g=self.pending();s=g.snapshot();queue=s['resolution_frame']['fields']['continuation']['tuple']
        marker=self.nested(s['resolution_frame'],'FinishSequenceAttempt')
        queue.remove(marker);queue.insert(0,marker);self.reject(s)


if __name__=='__main__':unittest.main()
