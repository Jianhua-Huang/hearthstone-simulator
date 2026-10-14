"""Original versus remaining deck facts, resumable branches and lasting rules."""
from dataclasses import replace
import json
import unittest
import opening_fixtures as opening
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, Scenario, PlayerSetup, CardDefinition, CardType, CardClass,
    PlayCard, EndTurn, SelectChoice, OpeningHook, TriggerSpec, Keyword, RewindSpec,
    BattlecryRepeatSpec, AddBattlecryRepeatModifier, DeckCondition, CheckDeckCondition,
    UnknownDeckFacts, matches_deck_condition, ResolutionError, SnapshotError,
    PlayedBattlecryQuery, RepeatPlayedBattlecries, battlecry_play_window, TriggerBattlecry)
from hs_sim.engine.effects import (GainArmor, AddToHand, ChangeManaCrystals, Summon, Destroy, Damage,
    Silence, Transform, ChangeControl, ReturnToHand, RequestChoice, ChoiceOption, InvokeBehavior)
from hs_sim.engine.zones import AddToDeck, DestroyDeckMatching, DrawMatching, CardReference
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.cross_zone import TransformCapturedMinion
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.representative import build_registry, _bolner_repeat
from hs_sim.engine.replay import build_replay, replay


class DeckConditionTests(unittest.TestCase):
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested
    choose=foundation.BattlecryTests.choose
    armor=foundation.BattlecryTests.armor

    def setUp(self):
        self.r=opening.registry()
        self.card('permanent',lambda c:[CheckDeckCondition(c.player_id,DeckCondition('starting'),
            (AddBattlecryRepeatModifier(c.player_id,source_id=c.source_id),))])
        self.card('cry',lambda c:[GainArmor(c.player_id,2)])
        self.r.register_card(CardDefinition('brann','Brann',CardType.MINION,health=4,
            battlecry_repeats=(BattlecryRepeatSpec(),),metadata=opening.metadata()))
        self.r.register_behavior('bolner',_bolner_repeat)
        self.r.register_card(CardDefinition('bolner','Bolner',CardType.MINION,health=4,
            triggers=(TriggerSpec('card_played','bolner'),),metadata=opening.metadata()))
        self.r.register_card(CardDefinition('retainer','Retainer',CardType.MINION,health=4,
            retain_rewind_outcomes=True,metadata=opening.metadata()))
        for cid in ('brann','bolner','retainer'):
            self.r.register_card(CardDefinition('board.'+cid,cid,CardType.MINION,health=4,metadata=opening.metadata()))
        def prepare(c):
            original=c.state.players[c.player_id].original_deck
            return [ChangeManaCrystals(c.player_id,9),
                *(AddToHand(c.player_id,cid) for cid in original if cid.startswith('tool.')),
                *(Summon(c.player_id,cid[6:]) for cid in original if cid.startswith('board.'))]
        self.r.register_behavior('prepare',prepare)
        self.r.register_card(CardDefinition('fixture','Fixture',CardType.MINION,health=4,
            opening_hooks=(OpeningHook('before_deal','prepare'),),metadata=opening.metadata()))

    def card(self,name,fn,**kw):
        cid='tool.'+name;self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=4,battlecry=cid,
            metadata=opening.metadata(),**kw));return cid

    def spell(self,name,fn):
        cid='tool.'+name;self.r.register_behavior(cid,fn)
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid,metadata=opening.metadata()));return cid

    def scenario(self,hand=(),deck=(),other_deck=(),board=()):
        return Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=tuple('tool.'+c for c in hand),deck=deck,board=board,mana=10,max_mana=10),
            PlayerSetup('warrior.hero',deck=other_deck))),self.r)

    def match(self,hand=('permanent','cry'),duplicate=False,board=(),extra=(),finish=True):
        cards=['fixture',*('tool.'+c for c in hand),*('board.'+c for c in board),*extra]
        cards.extend(f'card.{i}' for i in range(1,13-len(cards)))
        if duplicate:cards[-1]=cards[-2]
        g=Game.from_decks(opening.setup(self.r,decks=(opening.deck(cards=tuple(cards)),
            opening.deck(CardClass.WARRIOR,tuple(f'card.{i}' for i in range(21,33)))),deck_size=12),self.r)
        if finish:
            while g.state.pending_choice:self.choose(g,())
        return g

    def choose(self,g,options=()):
        pending=g.state.pending_choice
        g.apply(SelectChoice(pending.player_id,pending.id,options))

    def play(self,g,name):
        cid='tool.'+name;i=next(i for i in g.state.players[1].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(1,i));return i

    def query(self,g,scope='current',player=1):
        return matches_deck_condition(g.state,self.r,player,DeckCondition(scope))

    def branch(self,scope='current',yes=3,no=1):
        return CheckDeckCondition(1,DeckCondition(scope),(GainArmor(1,yes),),(GainArmor(1,no),))

    def pause(self):return RequestChoice(1,(ChoiceOption('ok','OK',()),))

    def test_current_empty_singleton_distinct_and_duplicate(self):
        for deck,want in (((),True),(('card.1',),True),(('card.1','card.2'),True),(('card.1','card.1'),False)):
            with self.subTest(deck=deck):
                g=self.scenario(deck=deck);self.assertEqual(self.query(g),want);self.check(g)

    def test_query_uses_requested_player(self):
        g=self.scenario(deck=('card.1','card.1'),other_deck=('card.2','card.3'))
        self.assertFalse(self.query(g));self.assertTrue(self.query(g,player=2));self.check(g)

    def test_current_identity_aliases_are_duplicates(self):
        for cid in ('alias.a','alias.b'):
            self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=2,metadata=opening.metadata(deck_identity='shared')))
        g=self.scenario(deck=('alias.a','alias.b'));self.assertFalse(self.query(g));self.check(g)

    def test_starting_identity_aliases_use_same_reviewed_group(self):
        for cid in ('alias.a','alias.b'):
            self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=2,metadata=opening.metadata(deck_identity='shared')))
        g=self.match(hand=(),extra=('alias.a','alias.b'));self.assertFalse(self.query(g,'starting'));self.check(g)

    def test_missing_metadata_is_unknown_even_if_other_cards_repeat(self):
        self.r.register_card(CardDefinition('unknown','Unknown',CardType.MINION,health=2))
        g=self.scenario(deck=('card.1','card.1','unknown'))
        with self.assertRaises(UnknownDeckFacts) as error:self.query(g)
        self.assertNotIn('unknown',str(error.exception).lower());self.check(g)

    def test_scenario_starting_facts_are_not_inferred_from_remaining_cards(self):
        for deck in ((),('card.1',),('card.1','card.1')):
            with self.subTest(deck=deck):
                g=self.scenario(deck=deck)
                with self.assertRaises(UnknownDeckFacts):self.query(g,'starting')

    def test_forged_scenario_original_tuple_does_not_make_origin_known(self):
        g=self.scenario();s=g.snapshot();s['state']['players']['1']['original_deck']=['card.1']
        from hs_sim.engine.serialization import canonical_hash
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        restored=Game.from_snapshot(s,self.r)
        with self.assertRaises(UnknownDeckFacts):self.query(restored,'starting')

    def test_constructed_starting_fact_survives_mulligan_and_restore(self):
        g=self.match(finish=False);self.assertTrue(self.query(g,'starting'));self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,saved):
            pending=match.state.pending_choice;self.choose(match,tuple(o.id for o in pending.options))
            self.choose(match);self.assertTrue(self.query(match,'starting'))
        self.assertEqual(g.snapshot(),saved.snapshot());self.check(g)

    def test_draw_and_deck_destruction_do_not_rewrite_starting_duplicates(self):
        self.spell('empty',lambda c:[DestroyDeckMatching(1,count=30,reveal=False)])
        g=self.match(hand=('empty',),duplicate=True);original=g.state.players[1].original_deck
        self.play(g,'empty');self.assertTrue(self.query(g));self.assertFalse(self.query(g,'starting'))
        self.assertEqual(g.state.players[1].original_deck,original);self.check(g)

    def test_new_duplicates_change_current_but_not_starting_condition(self):
        self.spell('shuffle',lambda c:[AddToDeck(1,'card.40'),AddToDeck(1,'card.40')])
        g=self.match(hand=('shuffle',));self.play(g,'shuffle')
        self.assertFalse(self.query(g));self.assertTrue(self.query(g,'starting'));self.check(g)

    def test_transform_in_deck_changes_current_identity(self):
        self.spell('morph',lambda c:[TransformCapturedMinion(CardReference.capture(c.state.entities[c.state.players[1].deck[1]]),'card.1')])
        g=self.scenario(hand=('morph',),deck=('card.1','card.2'));self.assertTrue(self.query(g))
        self.play(g,'morph');self.assertFalse(self.query(g));self.check(g)

    def test_draw_one_duplicate_changes_current_predicate(self):
        self.spell('draw',lambda c:[DrawMatching(1,PoolQuery(),'skip',selection='first')])
        g=self.scenario(hand=('draw',),deck=('card.1','card.1','card.2'));self.play(g,'draw')
        self.assertTrue(self.query(g));self.check(g)

    def test_explicit_false_branch_has_ordinary_effects(self):
        self.spell('check',lambda c:[self.branch()]);g=self.scenario(hand=('check',),deck=('card.1','card.1'))
        self.play(g,'check');self.assertEqual(self.armor(g),1);self.check(g)

    def test_empty_false_branch_does_not_apply_true_effects(self):
        self.spell('check',lambda c:[CheckDeckCondition(1,DeckCondition(),(GainArmor(1,3),))])
        g=self.scenario(hand=('check',),deck=('card.1','card.1'));self.play(g,'check')
        self.assertEqual(self.armor(g),0);self.check(g)

    def test_condition_evaluates_after_preceding_effects(self):
        self.spell('check',lambda c:[AddToDeck(1,'card.1'),self.branch()])
        g=self.scenario(hand=('check',),deck=('card.1',));self.play(g,'check');self.assertEqual(self.armor(g),1);self.check(g)

    def test_selected_branch_does_not_recheck_after_it_changes_deck(self):
        self.spell('check',lambda c:[CheckDeckCondition(1,DeckCondition(),
            (AddToDeck(1,'card.1'),self.pause(),GainArmor(1,3)),(GainArmor(1,99),))])
        g=self.scenario(hand=('check',),deck=('card.1',));self.play(g,'check');self.assertFalse(self.query(g));self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,saved):self.choose(match,('ok',))
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def pending_condition(self):
        self.spell('wait',lambda c:[self.pause(),self.branch()])
        g=self.scenario(hand=('wait',),deck=('card.1',));self.play(g,'wait');return g

    def test_pending_condition_round_trips_and_uses_player_port(self):
        g=self.pending_condition();self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,saved):
            port=match.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def test_nested_conditions_resume_without_closure_state(self):
        self.spell('nested',lambda c:[CheckDeckCondition(1,DeckCondition('starting'),(self.pause(),self.branch()),(GainArmor(1,99),))])
        g=self.match(hand=('nested',));self.play(g,'nested');self.check(g);self.choose(g,('ok',))
        self.assertEqual(self.armor(g),3);self.check(g)

    def test_unknown_starting_condition_rolls_back_preceding_effects(self):
        self.spell('unknown',lambda c:[GainArmor(1,7),self.branch('starting')])
        g=self.scenario(hand=('unknown',));before=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.play(g,'unknown')
        self.assertEqual(g.snapshot(),before)

    def test_error_after_choice_rolls_back_to_same_pending_frame(self):
        self.spell('wait',lambda c:[self.pause(),self.branch('starting')])
        g=self.scenario(hand=('wait',));self.play(g,'wait');before=g.snapshot();self.check(g)
        with self.assertRaises(UnknownDeckFacts):self.choose(g,('ok',))
        self.assertEqual(g.snapshot(),before)

    def test_unknown_metadata_rolls_back_selected_action(self):
        self.r.register_card(CardDefinition('hidden','Hidden',CardType.MINION,health=2))
        self.spell('check',lambda c:[GainArmor(1,7),self.branch()]);g=self.scenario(hand=('check',),deck=('hidden',));before=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):self.play(g,'check')
        self.assertEqual(g.snapshot(),before)

    def test_restore_rejects_invalid_condition_scope_predicate_or_branch(self):
        g=self.pending_condition()
        for field,value in (('scope','inferred'),('predicate','always')):
            with self.subTest(field=field):
                s=g.snapshot();self.nested(s['resolution_frame'],'DeckCondition')['fields'][field]=value;self.reject(s)
        s=g.snapshot();self.nested(s['resolution_frame'],'CheckDeckCondition')['fields']['player_id']=3;self.reject(s)

    def test_restore_rejects_original_deck_mismatch_with_constructed_setup(self):
        g=self.match();s=g.snapshot();s['state']['players']['1']['original_deck']=[];self.reject(s)

    def test_predicate_does_not_publish_deck_or_original_card_list(self):
        g=self.pending_condition()
        for player in (1,2):
            text=json.dumps((g.observe(player),g.player_events(player)))
            for key in ('original_deck','DeckCondition','on_match','on_miss'):self.assertNotIn(key,text)
        self.assertEqual(g.for_player(2).observe()['observation']['pending_choice'],{'player_id':1})

    def test_permanent_policy_requires_known_unique_origin(self):
        g=self.match();self.play(g,'permanent');self.play(g,'cry')
        self.assertEqual(self.armor(g),4);mod=g.state.players[1].battlecry_modifiers[0]
        self.assertEqual((mod.uses_remaining,mod.expires_turn),(None,None));self.check(g)

    def test_duplicate_origin_does_not_grant_even_after_deck_emptied(self):
        self.spell('empty',lambda c:[DestroyDeckMatching(1,count=30,reveal=False)])
        g=self.match(hand=('empty','permanent','cry'),duplicate=True)
        self.play(g,'empty');self.play(g,'permanent');self.play(g,'cry')
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_source_death_silence_transform_transfer_and_bounce_preserve_policy(self):
        operations=(Destroy,Silence,lambda i:Transform(i,'card.40'),lambda i:ChangeControl(i,2),ReturnToHand)
        for n,op in enumerate(operations):self.spell('remove'+str(n),lambda c,op=op:[op(c.state.players[1].board[0])])
        for n in range(len(operations)):
            with self.subTest(operation=n):
                g=self.match(hand=('permanent','remove'+str(n),'cry'))
                self.play(g,'permanent');self.play(g,'remove'+str(n));self.play(g,'cry')
                self.assertEqual((self.armor(g),self.armor(g,2)),(4,0));self.assertEqual(len(g.state.players[1].battlecry_modifiers),1);self.check(g)

    def test_permanent_policy_survives_multiple_turns(self):
        g=self.match();self.play(g,'permanent');g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'cry')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.players[1].battlecry_modifiers),1);self.check(g)

    def test_own_new_policy_does_not_retroactively_repeat_its_grant(self):
        g=self.match();self.play(g,'permanent')
        self.assertEqual(len(g.state.battlecry_history),1);self.assertEqual(len(g.state.players[1].battlecry_modifiers),1);self.check(g)

    def test_existing_brann_repeats_grant_but_policies_combine_by_max(self):
        g=self.match(board=('brann',));self.play(g,'permanent');self.play(g,'cry')
        self.assertEqual(len(g.state.players[1].battlecry_modifiers),2);self.assertEqual(self.armor(g),4);self.check(g)

    def test_finite_and_permanent_policies_have_independent_consumption(self):
        self.spell('finite',lambda c:[AddBattlecryRepeatModifier(1,BattlecryRepeatSpec(3),uses=1)])
        g=self.match(hand=('permanent','finite','cry'));self.play(g,'permanent');self.play(g,'finite');self.play(g,'cry')
        self.assertEqual(self.armor(g),6);self.assertEqual(len(g.state.players[1].battlecry_modifiers),1);self.check(g)

    def test_bolner_replays_conditional_grant_without_new_hand_multiplier(self):
        g=self.match(board=('bolner',));self.play(g,'permanent');self.play(g,'cry')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.players[1].battlecry_modifiers),3)
        self.assertEqual([b.origin for b in g.state.battlecry_history],['hand','played_history','hand','hand','played_history']);self.check(g)

    def test_macaw_replays_condition_using_execution_players_origin(self):
        self.card('macaw',lambda c:[RepeatPlayedBattlecries(c.player_id,c.source_id,
            PlayedBattlecryQuery(before_id=battlecry_play_window(c.state,c.battlecry),countered='include'))])
        g=self.match(hand=('permanent','macaw','cry'));self.play(g,'permanent');self.play(g,'macaw');self.play(g,'cry')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.players[1].battlecry_modifiers),3);self.check(g)

    def test_transfer_then_physical_activation_checks_new_owners_starting_deck(self):
        self.r.register_behavior('activate',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[2].board[0]]),c.source_id)])
        self.spell('transfer',lambda c:[ChangeControl(c.state.players[1].board[0],2),InvokeBehavior('activate',c.source_id,1)])
        g=self.match(hand=('permanent','transfer'),duplicate=True);self.play(g,'permanent');self.assertFalse(g.state.players[1].battlecry_modifiers)
        self.play(g,'transfer');self.assertFalse(g.state.players[1].battlecry_modifiers)
        self.assertEqual(len(g.state.players[2].battlecry_modifiers),1);self.check(g)

    def test_retry_restores_one_grant_and_retained_rewind_keeps_two(self):
        self.card('rewind',lambda c:[CheckDeckCondition(c.player_id,DeckCondition('starting'),(AddBattlecryRepeatModifier(c.player_id),))],
            keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        for board in ((),('retainer',)):
            with self.subTest(board=board):
                g=self.match(hand=('rewind',),board=board);self.play(g,'rewind');self.check(g)
                if not board:self.choose(g,('retry',))
                self.assertEqual(len(g.state.players[1].battlecry_modifiers),2 if board else 1);self.check(g)

    def test_invalid_predicate_and_branch_inputs_are_rejected(self):
        for make in (lambda:DeckCondition('hand'),lambda:DeckCondition(True),lambda:DeckCondition(predicate='always'),
            lambda:CheckDeckCondition(True,DeckCondition(),()),lambda:CheckDeckCondition(1,None,()),
            lambda:CheckDeckCondition(1,DeckCondition(),[]),lambda:CheckDeckCondition(1,DeckCondition(),('bad',))):
            with self.subTest(make=make),self.assertRaises(ValueError):make()

    def test_each_repeated_activation_evaluates_current_deck_again(self):
        self.card('conditional',lambda c:[CheckDeckCondition(1,DeckCondition(),
            (AddToDeck(1,'card.1'),GainArmor(1,3)),(GainArmor(1,1),))])
        g=self.scenario(hand=('conditional',),deck=('card.1',),board=('brann',));self.play(g,'conditional')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(g.state.battlecry_history),2);self.check(g)

    def test_countered_grant_never_evaluates_or_installs_policy(self):
        from hs_sim.engine import CounterMinion
        self.r.register_behavior('counter',lambda c:[CounterMinion(dict(c.event.data)['window_id'])])
        self.r.register_card(CardDefinition('counter','Counter',CardType.MINION,health=3,
            triggers=(TriggerSpec('minion_counter_check','counter'),),metadata=opening.metadata()))
        self.r.register_card(CardDefinition('board.counter','Counter setup',CardType.MINION,health=3,metadata=opening.metadata()))
        g=self.match(hand=('permanent',),board=('counter',));self.play(g,'permanent')
        self.assertTrue(g.state.play_history[0].countered);self.assertEqual(g.state.battlecry_history,[])
        self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_terminal_branch_cancels_following_grant(self):
        self.spell('lethal',lambda c:[CheckDeckCondition(1,DeckCondition(),
            (Damage(c.state.players[2].hero_id,40,c.source_id),AddBattlecryRepeatModifier(1)))])
        g=self.scenario(hand=('lethal',));self.play(g,'lethal')
        self.assertEqual(g.state.status,'finished');self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_restore_rejects_branch_without_typed_effect_tuple(self):
        g=self.pending_condition();s=g.snapshot()
        self.nested(s['resolution_frame'],'CheckDeckCondition')['fields']['on_match']=[];self.reject(s)

    def captured_origin(self):
        self.spell('noop',lambda c:[])
        self.r.register_behavior('wait',lambda c:[self.pause()])
        self.r.register_behavior('query',lambda c:[GainArmor(1,3 if matches_deck_condition(c.state,self.r,1,DeckCondition('starting')) else 1)])
        for cid in ('wait','query'):
            self.r.register_card(CardDefinition(cid,cid,CardType.MINION,health=3,
                triggers=(TriggerSpec('card_played',cid),),metadata=opening.metadata()))
            self.r.register_card(CardDefinition('board.'+cid,cid,CardType.MINION,health=3,metadata=opening.metadata()))
        g=self.match(hand=('noop',),board=('wait','query'));self.play(g,'noop');return g

    def test_captured_starting_query_restores_with_same_origin(self):
        g=self.captured_origin();self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        self.choose(g,('ok',));self.choose(saved,('ok',))
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def test_restore_rejects_changed_origin_in_captured_rule_context(self):
        g=self.captured_origin();s=g.snapshot()
        context=self.nested(s['resolution_frame'],'RuleContext')
        cards=context['fields']['state']['state']['players']['1']['original_deck']
        cards[-1]=cards[-2];self.reject(s)

    def test_restore_rejects_changed_origin_knowledge_in_captured_context(self):
        g=self.captured_origin();s=g.snapshot()
        self.nested(s['resolution_frame'],'RuleContext')['fields']['state']['state']['opening']=None
        self.reject(s)


class DeckRepresentativeTests(unittest.TestCase):
    def test_deepminer_in_arbitrary_scenario_fails_instead_of_guessing(self):
        r=build_registry();g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('DEEP_020',),mana=10,max_mana=10),PlayerSetup('HERO_08'))),r)
        before=g.snapshot()
        with self.assertRaises(UnknownDeckFacts):g.apply(PlayCard(1,g.state.players[1].hand[0]))
        self.assertEqual(g.snapshot(),before)

    def test_real_constructed_condition_and_discovery_restore(self):
        from examples.starting_deck_conditions import run
        game,snapshot=run();self.assertIsNotNone(snapshot['state']['pending_choice'])
        self.assertEqual(len(game.state.players[1].battlecry_modifiers),1)


if __name__=='__main__':unittest.main()
