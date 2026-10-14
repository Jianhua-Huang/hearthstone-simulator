"""First-play listener composition. Experimental R-122, not official timing proof."""
import json
import unittest
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, CardDefinition, CardType, Scenario, PlayerSetup, PlayCard,
    TriggerSpec, EndTurn, BattlecryRepeatSpec, AddBattlecryRepeatModifier, RewindSpec,
    Keyword, TargetSpec, ResolutionError, GenerationContext, LaunchStarship)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Silence, ChangeControl,
    Transform, ReturnToHand, Summon, InvokeBehavior, DamageBatch)
from hs_sim.engine.representative import _bolner_repeat, build_registry
from hs_sim.engine.replay import build_replay, replay


class TriggeredBattlecryTests(unittest.TestCase):
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

    def setUp(self):
        foundation.BattlecryTests.setUp(self)
        self.watch('bolner','card_played',_bolner_repeat)

    def children(self,g):
        return [b for b in g.state.battlecry_history if b.origin=='played_history']

    def test_first_and_later_plays_repeat_first_once(self):
        self.card('five',lambda c:[GainArmor(c.player_id,5)])
        g=self.game(hand=('cry','five','body'),board=('bolner',))
        for cid in ('cry','five','body'):self.play(g,cid)
        self.assertEqual(self.armor(g),11)
        self.assertEqual([b.history_play_id for b in self.children(g)],[1,1])
        self.assertEqual((len(g.state.play_history),len(g.state.battlecry_history)),(3,4));self.check(g)

    def test_bolner_play_and_normal_summon_do_not_trigger(self):
        self.script('summon',lambda c:[Summon(1,'cry')])
        g=self.game(hand=('bolner','summon'));self.play(g,'bolner');self.play(g,'summon')
        self.assertEqual(g.state.battlecry_history,[]);self.assertEqual(self.armor(g),0);self.check(g)

    def test_first_play_can_precede_listener_entry(self):
        self.card('five',lambda c:[GainArmor(c.player_id,5)])
        g=self.game(hand=('cry','bolner','five'))
        for cid in ('cry','bolner','five'):self.play(g,cid)
        self.assertEqual(self.armor(g),9);self.assertEqual(self.children(g)[0].history_play_id,1);self.check(g)

    def test_first_weapon_and_hero_are_not_filtered_as_minions(self):
        self.card('weapon',lambda c:[GainArmor(c.player_id,5)],kind=CardType.WEAPON)
        self.card('hero_card',lambda c:[GainArmor(c.player_id,5)],kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        for cid in ('weapon','hero_card'):
            with self.subTest(cid=cid):
                g=self.game(hand=(cid,'cry'),board=('bolner',));self.play(g,cid)
                self.assertEqual(self.children(g),[]);self.play(g)
                self.assertEqual(self.armor(g),12);self.assertEqual(self.children(g)[0].payload.card_id,cid);self.check(g)

    def test_new_turn_resets_first_play(self):
        self.card('five',lambda c:[GainArmor(c.player_id,5)])
        g=self.game(hand=('cry','five'),board=('bolner',));self.play(g)
        g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g,'five')
        self.assertEqual(self.armor(g),14);self.assertEqual([b.history_play_id for b in self.children(g)],[1,2]);self.check(g)

    def test_enemy_play_triggers_only_enemy_listener(self):
        g=self.game(board=('bolner',),enemy=('bolner',));g.apply(EndTurn(1))
        g.apply(PlayCard(2,g.state.players[2].hand[0]))
        self.assertEqual((self.armor(g),self.armor(g,2)),(0,4))
        self.assertEqual(self.children(g)[0].player_id,2);self.check(g)

    def test_source_removed_before_completion_is_ineligible(self):
        operations=(Destroy,Silence,lambda i:ChangeControl(i,2),lambda i:Transform(i,'body'),ReturnToHand)
        for n,operation in enumerate(operations):
            self.card('remove'+str(n),lambda c,op=operation:[op(c.state.players[1].board[0]),GainArmor(1,2)])
        for n in range(len(operations)):
            with self.subTest(operation=n):
                g=self.game(hand=('remove'+str(n),),board=('bolner',));self.play(g,'remove'+str(n))
                self.assertEqual(self.armor(g),2);self.assertEqual(self.children(g),[]);self.check(g)

    def test_listener_arriving_during_original_payload_sees_completion(self):
        self.card('arrival',lambda c:[Summon(1,'bolner'),GainArmor(1,2)])
        g=self.game(hand=('arrival',));self.play(g,'arrival')
        self.assertEqual((self.armor(g),len(self.children(g))),(4,1))
        self.assertEqual(sum(g.state.entities[i].card_id=='bolner' for i in g.state.players[1].board),2);self.check(g)

    def test_captured_listener_survives_later_death_silence_transfer_morph_or_bounce(self):
        operations=(Destroy,Silence,lambda i:ChangeControl(i,2),lambda i:Transform(i,'body'),ReturnToHand)
        for n,operation in enumerate(operations):
            self.watch('remove'+str(n),'card_played',lambda c,op=operation:[op(c.state.players[1].board[1])])
        for n in range(len(operations)):
            with self.subTest(operation=n):
                g=self.game(board=('remove'+str(n),'bolner'));source=g.state.players[1].board[1];self.play(g)
                self.assertEqual((self.armor(g),self.armor(g,2)),(4,0))
                child=self.children(g)[0];self.assertEqual((child.source_id,child.player_id,child.history_play_id),(source,1,1))
                self.assertEqual(child.card_id,'body' if n==3 else 'bolner');self.check(g)

    def test_two_sources_preserve_order_without_recursive_card_played_events(self):
        g=self.game(board=('bolner','bolner'));sources=g.state.players[1].board;self.play(g)
        self.assertEqual(self.armor(g),6);self.assertEqual([b.source_id for b in self.children(g)],sources)
        self.assertEqual(sum(e.kind=='card_played' for e in g.events),1);self.check(g)

    def test_brann_multiplies_original_but_not_completion_or_history_child(self):
        self.r.register_card(CardDefinition('brann','brann',CardType.MINION,health=4,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.game(board=('brann','bolner','bolner'));self.play(g)
        self.assertEqual(self.armor(g),8);self.assertEqual([b.origin for b in g.state.battlecry_history],['hand','hand','played_history','played_history']);self.check(g)

    def test_finite_policy_consumed_once_and_not_applied_to_child(self):
        self.script('grant',lambda c:[AddBattlecryRepeatModifier(1,BattlecryRepeatSpec(3),uses=1)])
        g=self.game(hand=('grant','cry'),board=('bolner',));self.play(g,'grant');self.play(g)
        self.assertEqual(self.armor(g),8);self.assertEqual(len(self.children(g)),1)
        self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_countered_commit_is_provisionally_eligible_for_trigger_and_first_source(self):
        import test_m5_minion_counters as counters
        self.secret=counters.MinionCounterTests.secret.__get__(self);counters.MinionCounterTests.setUp(self)
        self.watch('bolner','card_played',_bolner_repeat)
        self.card('five',lambda c:[GainArmor(1,5)])
        g=self.game(hand=('arm','cry','five'),board=('bolner',));self.play(g,'arm');self.play(g)
        self.assertTrue(g.state.play_history[1].countered);self.assertEqual(self.armor(g),2)
        self.play(g,'five');self.assertEqual(self.armor(g),9)
        self.assertEqual([b.history_play_id for b in self.children(g)],[2,2]);self.check(g)

    def test_full_board_failed_entry_still_uses_committed_declaration(self):
        self.watch('fill','minion_counter_check',lambda c:[Summon(1,'body') for _ in range(5)])
        g=self.game(board=('fill','bolner'));self.play(g)
        self.assertEqual(g.state.play_history[0].minion_result,'board_full')
        self.assertEqual((self.armor(g),len(g.state.battlecry_history)),(2,1));self.check(g)

    def test_magnetic_commit_without_original_activation_can_trigger(self):
        from hs_sim.engine.model import CardMetadata, CardClass
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,health=4,metadata=meta))
        self.card('magnet',keywords=(Keyword.MAGNETIC,),metadata=meta,magnetic_tribes=('mech',))
        g=self.game(hand=('magnet',),board=('mech','bolner'));g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
        self.assertEqual(g.state.play_history[0].minion_result,'magnetized')
        self.assertEqual((self.armor(g),len(self.children(g))),(2,1));self.check(g)

    def test_indirect_physical_battlecry_does_not_trigger_listener(self):
        from hs_sim.engine import TriggerBattlecry
        from hs_sim.engine.sacrifice import MinionReference
        self.script('activate',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[c.state.players[1].board[1]]),c.source_id)])
        g=self.game(hand=('activate',),board=('bolner','cry'));self.play(g,'activate')
        self.assertEqual(self.armor(g),2);self.assertEqual(self.children(g),[]);self.check(g)

    def test_target_is_selected_again_from_current_board(self):
        self.card('hit',lambda c:[Damage(c.target_id,1,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('hit',),board=('bolner',),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'hit',target);self.assertEqual(g.state.entities[target].health,3)
        self.assertEqual(self.children(g)[0].target_id,target);self.check(g)

    def test_target_removed_by_original_marks_child_failed(self):
        self.card('hit',lambda c:[Damage(c.target_id,10,c.source_id)],targeting=TargetSpec(kinds=(CardType.MINION,),relation='enemy'))
        g=self.game(hand=('hit',),board=('bolner',),enemy=('body',));self.play(g,'hit',g.state.players[2].board[0])
        child=self.children(g)[0];self.assertEqual((child.failure,child.completed,child.payload_started),('no_target',True,False));self.check(g)

    def test_original_choice_restores_before_automatic_child_choice(self):
        self.card('choice',lambda c:[self.pause(c),GainArmor(1,3)])
        g=self.game(hand=('choice',),board=('bolner',));self.play(g,'choice');self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(saved)
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertIsNone(g.state.pending_choice)
        self.assertEqual(self.armor(g),6);self.assertEqual(sum(e.kind=='battlecry_choice_randomized' for e in g.events),1);self.check(g)

    def pending_child_start(self):
        self.watch('wait','battlecry_started',lambda c:[self.pause(c)] if c.battlecry.origin=='played_history' else [])
        g=self.game(board=('bolner','wait'));self.play(g);return g

    def test_pause_at_child_start_restores_and_player_port_resumes(self):
        g=self.pending_child_start();self.check(g);saved=Game.from_snapshot(g.snapshot(),self.r)
        for match in (g,saved):
            port=match.for_player(1);listing=port.legal_actions();action=next(a for a in listing['actions'] if a['type']=='select_choice')
            self.assertTrue(port.submit({'revision':listing['revision'],'action':action})['accepted'])
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),4);self.check(g)

    def test_child_start_observation_hides_historical_payload(self):
        g=self.pending_child_start()
        for p in (1,2):
            text=json.dumps((g.observe(p),g.player_events(p)))
            for field in ('history_play_id','play_history','behavior_id','battlecry_id'):self.assertNotIn(field,text)
        self.assertEqual(g.for_player(2).observe()['observation']['pending_choice'],{'player_id':1})

    def test_restore_rejects_wrong_history_owner_or_missing_source(self):
        g=self.pending_child_start()
        for key,value in (('history_play_id',99),('player_id',2)):
            with self.subTest(field=key):
                s=g.snapshot();s['state']['battlecry_history'][-1][key]=value;self.reject(s)

    def test_captured_listener_context_restores_before_execution(self):
        self.watch('wait','card_played',lambda c:[self.pause(c)])
        g=self.game(board=('wait','bolner'));self.play(g);self.assertEqual(self.children(g),[]);self.check(g)
        saved=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(saved)
        self.assertEqual(g.snapshot(),saved.snapshot());self.assertEqual(self.armor(g),4);self.check(g)

    def test_rewind_retries_do_not_duplicate_completion_trigger(self):
        self.card('rewind',keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('bolner',));self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual(self.armor(g),4);self.assertEqual((len(g.state.play_history),len(self.children(g))),(1,1));self.check(g)

    def test_retained_rewind_records_two_activations_but_one_completion(self):
        self.card('rewind',keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.game(hand=('rewind',),board=('retainer','bolner'));self.play(g,'rewind')
        self.assertEqual(self.armor(g),6);self.assertEqual((len(g.state.play_history),len(self.children(g))),(1,1));self.check(g)

    def test_child_failure_rolls_back_entire_unpaused_action(self):
        self.card('bad',lambda c:[Summon(1,'missing')] if c.battlecry.origin=='played_history' else [GainArmor(1,2)])
        g=self.game(hand=('bad',),board=('bolner',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_child_error_after_pause_preserves_pending_choice(self):
        self.r.register_behavior('fail',lambda c:[Summon(1,'missing')])
        self.watch('wait','battlecry_started',lambda c:[self.pause(c),InvokeBehavior('fail',c.source_id,1)] if c.battlecry.origin=='played_history' else [])
        g=self.game(board=('bolner','wait'));self.play(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_lethal_child_interrupts_later_captured_listener(self):
        self.card('hurt',lambda c:[Damage(c.state.players[2].hero_id,20,c.source_id)])
        g=self.game(hand=('hurt',),board=('bolner','bolner'));self.play(g,'hurt')
        self.assertEqual(g.state.status,'finished');self.assertEqual(len(self.children(g)),1)
        self.assertTrue(self.children(g)[0].interrupted);self.assertTrue(g.state.play_history[0].completed);self.check(g)


class BolnerRepresentativeTests(unittest.TestCase):
    def test_bolner_is_trigger_only_and_has_pinned_source(self):
        r=build_registry();card=r.card('SW_115')
        self.assertIsNone(card.battlecry);self.assertEqual((card.cost,card.attack,card.health),(2,1,4))
        self.assertEqual(card.triggers,(TriggerSpec('card_played','m5.bolner'),))

    def test_brann_scarab_macaw_and_two_bolners_restore_and_replay(self):
        from examples.bolner_history import run
        game,snapshot=run();self.assertIsNotNone(snapshot['state']['pending_choice'])
        self.assertEqual((len(game.state.play_history),len(game.state.battlecry_history)),(2,10))

    def test_two_component_starship_repeats_each_captured_payload(self):
        from hs_sim.engine.starships import construction
        r=build_registry()
        r.register_behavior('scrap',lambda c:[DamageBatch(tuple(Damage(i,100) for i in c.state.players[1].board))])
        r.register_behavior('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        r.register_behavior('bolner',lambda c:[Summon(1,'SW_115')])
        for cid in ('scrap','bounce','bolner'):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
        g=Game.from_scenario(Scenario((PlayerSetup('HERO_01',board=('SC_405','SC_405'),hand=('scrap','bounce','bolner'),
            deck=('CS2_182',)*6,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=('CS2_182',)*6)),seed=81),r)
        for cid in ('scrap',):g.apply(PlayCard(1,g.state.players[1].hand[0]))
        ship=construction(g.state,1);g.apply(LaunchStarship(1,ship.id));g.apply(PlayCard(1,g.state.players[1].hand[0]))
        g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(PlayCard(1,ship.id));original=g.state.play_history[-1]
        children=[b for b in g.state.battlecry_history if b.origin=='played_history']
        self.assertEqual(len(original.battlecries),2);self.assertEqual([b.payload for b in children],list(original.battlecries))
        self.assertEqual(Game.from_snapshot(g.snapshot(),r).snapshot(),g.snapshot());self.assertEqual(replay(build_replay(g),r).snapshot(),g.snapshot())


if __name__=='__main__':unittest.main()
