"""Whole hand-minion counter boundaries, not destruction or skipped Battlecry."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, Registry, CardDefinition, CardType, CounterCard, CounterMinion,
    CounterSpell, SecretSpec, Keyword, SetSecret, PlayCard, EndTurn, Scenario, PlayerSetup,
    SelectChoice, SnapshotError, IllegalAction, ResolutionError, Ruleset, TriggerSpec,
    Zone, RewindSpec, AppendageSpec, AddBattlecryRepeatModifier, HandDerivativeSpec, HandRepeatSpec)
from hs_sim.engine.effects import (GainArmor, Damage, Destroy, Silence, Summon, RequestChoice,
    ChoiceOption, InvokeBehavior, ReturnToHand, ForceAttack)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.model import Resource, CardMetadata, CardClass


class MinionCounterTests(unittest.TestCase):
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
        self.r.register_secret_condition('minion',lambda c:c.window is not None and
            c.window.kind=='minion' and not c.window.countered and c.window.player_id!=c.player_id)
        self.r.register_behavior('counter',lambda c:[CounterMinion(c.window.id)])
        self.secret('counter')
        self.script('arm',lambda c:[SetSecret(2,'counter')])
        self.script('grant',lambda c:[AddBattlecryRepeatModifier(1,uses=1,source_id=c.source_id)])

    def secret(self,cid,behavior='counter',event='minion_counter_check'):
        self.r.register_card(CardDefinition(cid,cid,CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec(cid,(event,),'minion',behavior)))

    def armed(self,hand=('cry',),**kw):
        g=self.game(hand=('arm',*hand),**kw);self.play(g,'arm');return g

    def pause_at(self,event='minion_counter_check',options=None):
        self.watch('wait',event,lambda c:[RequestChoice(1,options or (ChoiceOption('ok','OK',()),),source_id=c.source_id)]
            if c.play is not None and c.play.kind==CardType.MINION else [])

    def test_ordinary_entry_at_each_position_preserves_original_physical_identity(self):
        for position in (0, 1, 2):
            with self.subTest(position=position):
                g = self.game(hand=('body',), board=('body', 'body'))
                source = g.state.players[1].hand[0]
                original_board = list(g.state.players[1].board)
                next_entity = g.state.next_entity_id
                g.apply(PlayCard(1, source, position=position))
                expected = original_board.copy()
                expected.insert(position, source)
                self.assertEqual(g.state.players[1].board, expected)
                self.assertEqual((g.state.entities[source].owner,
                    g.state.entities[source].controller, g.state.entities[source].zone),
                    (1, 1, Zone.BOARD))
                self.assertEqual(g.state.next_entity_id, next_entity)
                play = g.state.play_history[-1]
                self.assertEqual((play.source_id, play.position, play.minion_result),
                    (source, position, 'summoned'))
                self.assertTrue(play.completed)
                self.assertFalse(g.state.players[1].pending_plays)
                self.assertFalse(g.state.action_windows)
                self.assertFalse(g.state.death_history)
                self.assertFalse(g.state.battlecry_history)
                self.check(g)

    def test_paid_counter_creates_no_entry_battlecry_or_death(self):
        g=self.armed();i=self.play(g);p=g.state.play_history[-1]
        self.assertEqual((p.countered,p.completed,p.minion_result),(True,True,'countered'))
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.players[1].board);self.assertFalse(g.state.death_history)
        self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.cast_history[-1].card_id=='cry')
        self.assertFalse(g.state.players[1].pending_plays);self.assertFalse(g.state.action_windows);self.check(g)

    def test_countered_minion_still_counts_as_committed_play(self):
        self.watch('before','card_committed',lambda c:[GainArmor(1,1)] if c.play.kind==CardType.MINION else [])
        self.watch('after','card_played',lambda c:[GainArmor(1,10)] if c.play.countered else [])
        g=self.armed(board=('before','after'));self.play(g);self.assertEqual(self.armor(g),11)
        self.assertEqual(g.observe(1)['players'][0]['cards_played_total'],2);self.check(g)

    def test_reborn_deathrattle_and_corpses_never_activate(self):
        self.r.register_card(CardDefinition('reborn','reborn',CardType.MINION,health=3,
            keywords=(Keyword.REBORN,),deathrattle='armor'))
        g=self.armed(hand=('reborn',));self.play(g,'reborn');self.assertEqual(self.armor(g),0)
        self.assertEqual(g.state.players[1].resources[Resource.CORPSES],0);self.assertFalse(g.state.death_history);self.check(g)

    def test_colossal_limbs_never_created(self):
        self.card('giant',lambda c:[GainArmor(1,9)],keywords=(Keyword.COLOSSAL,),colossal=(AppendageSpec('body'),))
        g=self.armed(hand=('giant',));n=g.state.next_entity_id;self.play(g,'giant')
        self.assertEqual(g.state.next_entity_id,n);self.assertFalse(g.state.colossal_history);self.check(g)

    def test_counter_preserves_finite_battlecry_policy(self):
        g=self.armed(hand=('grant','cry','cry'));self.play(g,'grant');self.play(g)
        self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining,1)
        self.play(g);self.assertEqual(self.armor(g),4);self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_echo_copy_survives_counter_without_entry(self):
        self.card('echo',keywords=(Keyword.ECHO,),hand_repeat=HandRepeatSpec());g=self.armed(hand=('echo',));i=self.play(g,'echo')
        hand=g.state.players[1].hand;self.assertEqual(len(hand),1);self.assertNotEqual(hand[0],i)
        self.assertEqual(g.state.entities[hand[0]].hand_lifetime.expires_turn,g.state.turn);self.check(g)

    def test_miniature_is_not_generated_after_counter(self):
        self.r.register_card(CardDefinition('mini','mini',CardType.MINION,cost=1,attack=1,health=1,keywords=(Keyword.MINI,)))
        self.card('big',keywords=(Keyword.MINIATURIZE,),hand_derivatives=(HandDerivativeSpec(Keyword.MINIATURIZE,'mini'),))
        g=self.armed(hand=('big',));n=g.state.next_entity_id;self.play(g,'big')
        self.assertEqual(g.state.next_entity_id,n);self.assertFalse(g.state.players[1].hand);self.check(g)

    def test_summon_bypasses_counter_and_does_not_spend_secret(self):
        self.script('summon',lambda c:[Summon(1,'cry')]);g=self.armed(hand=('summon',));self.play(g,'summon')
        self.assertEqual(len(g.state.players[2].secrets),1);self.assertEqual(len(g.state.players[1].board),1);self.check(g)

    def test_generic_on_play_is_also_cancelled(self):
        self.r.register_card(CardDefinition('generic','generic',CardType.MINION,health=2,on_play='armor'))
        g=self.armed(hand=('generic',));self.play(g,'generic');self.assertEqual(self.armor(g),0);self.check(g)

    def test_already_countered_window_does_not_spend_second_secret(self):
        self.secret('other');self.script('two',lambda c:[SetSecret(2,'counter'),SetSecret(2,'other')])
        g=self.game(hand=('two','cry','cry'));self.play(g,'two');self.play(g)
        self.assertEqual([g.state.entities[i].card_id for i in g.state.players[2].secrets],['other'])
        self.play(g);self.assertFalse(g.state.players[2].secrets);self.assertFalse(g.state.players[1].board);self.check(g)

    def test_commit_reactions_complete_before_counter_phase(self):
        self.watch('spend','card_committed',lambda c:[GainArmor(1,7)] if c.play.kind==CardType.MINION else [])
        self.r.register_behavior('observe',lambda c:[GainArmor(1,11 if c.state.entities[c.state.players[1].hero_id].armor==7 else 99),CounterMinion(c.window.id)])
        self.secret('observe','observe');self.script('set',lambda c:[SetSecret(2,'observe')])
        g=self.game(hand=('set','cry'),board=('spend',));self.play(g,'set');self.play(g)
        self.assertEqual(self.armor(g),18);self.check(g)

    def test_pending_source_not_in_hand_board_or_graveyard(self):
        self.pause_at('card_committed');g=self.armed(board=('wait',));i=self.play(g)
        p=g.state.players[1];self.assertEqual(p.pending_plays,[i]);self.assertNotIn(i,(*p.hand,*p.board,*p.graveyard))
        self.assertEqual(g.state.entities[i].entered_order,0);self.assertFalse(g.state.battlecry_batches);self.check(g)
        self.choose(g);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.check(g)

    def test_both_players_see_pending_card_but_no_internal_window(self):
        self.pause_at();g=self.armed(board=('wait',));self.play(g)
        for viewer in (1,2):
            v=g.observe(viewer);pending=v['players'][0]['pending_plays'];self.assertEqual(pending[0]['card_id'],'cry')
            self.assertNotIn('window_id',json.dumps(v));self.assertNotIn('minion_result',json.dumps(v))
            self.assertEqual(v['players'][1]['secrets'][0]['card_id'],'counter' if viewer==2 else None)
        self.check(g)

    def test_restore_in_counter_phase_and_finish_same_replay(self):
        self.pause_at();g=self.armed(board=('wait',));self.play(g)
        self.assertTrue(g.state.action_windows[-1].counter_phase);restored=Game.from_snapshot(g.snapshot(),self.r)
        self.choose(g);self.choose(restored);self.assertEqual(g.snapshot(),restored.snapshot());self.check(g)

    def test_pause_after_counter_keeps_window_and_flag_consistent(self):
        self.watch('wait','minion_countered',lambda c:[self.pause(c)])
        g=self.armed(board=('wait',));self.play(g)
        self.assertTrue(g.state.action_windows[-1].countered);self.assertTrue(g.state.play_history[-1].countered)
        self.check(g);self.choose(g);self.assertEqual(g.state.play_history[-1].minion_result,'countered');self.check(g)

    def test_pending_card_cannot_be_destroyed_as_board_minion(self):
        self.watch('destroy','card_committed',lambda c:[Destroy(c.event.source_id),Silence(c.event.source_id)] if c.play.kind==CardType.MINION else [])
        g=self.game(board=('destroy',));i=self.play(g);self.assertEqual(g.state.entities[i].zone,Zone.BOARD)
        self.assertFalse(g.state.entities[i].silenced);self.assertEqual(self.armor(g),2);self.check(g)

    def test_source_does_not_listen_to_own_commit_before_entry(self):
        self.r.register_card(CardDefinition('watch','watch',CardType.MINION,health=2,triggers=(TriggerSpec('card_committed','armor'),)))
        g=self.game(hand=('watch',));self.play(g,'watch');self.assertEqual(self.armor(g),0);self.check(g)

    def test_full_board_created_during_commit_fails_without_death(self):
        self.watch('fill','card_committed',lambda c:[Summon(1,'body') for _ in range(6)] if c.play.kind==CardType.MINION else [])
        g=self.game(board=('fill',));i=self.play(g);self.assertEqual(len(g.state.players[1].board),7)
        self.assertEqual(g.state.play_history[-1].minion_result,'board_full');self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD)
        self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.death_history);self.check(g)

    def test_original_full_board_is_illegal_without_spending_secret(self):
        g=self.armed(board=('body',)*7);s=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_rewind_countered_minion_has_no_retry_or_retained_result(self):
        self.card('rewind',keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        for board in ((),('retainer',)):
            g=self.armed(hand=('rewind',),board=board);self.play(g,'rewind');self.assertIsNone(g.state.pending_choice)
            self.assertFalse(g.state.rewind_outcomes);self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_commit_death_ends_game_without_entry_or_counter_consumption(self):
        self.watch('kill','card_committed',lambda c:[Damage(c.state.players[2].hero_id,100)] if c.play.kind==CardType.MINION else [])
        g=self.armed(board=('kill',));i=self.play(g);self.assertEqual(g.state.status,'finished')
        self.assertTrue(g.state.play_history[-1].interrupted);self.assertFalse(g.state.play_history[-1].countered)
        self.assertEqual(len(g.state.players[2].secrets),1);self.assertEqual(g.state.entities[i].zone,Zone.GRAVEYARD);self.check(g)

    def test_counter_exception_rolls_back_payment_reveal_and_entry(self):
        self.r.register_behavior('bad',lambda c:[CounterMinion(c.window.id),Summon(1,'missing')]);self.secret('bad','bad')
        self.script('set',lambda c:[SetSecret(2,'bad')]);g=self.game(hand=('set','cry'));self.play(g,'set');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g)
        self.assertEqual(g.snapshot(),s)

    def test_failure_after_pause_restores_pending_paid_state(self):
        self.r.register_behavior('bad',lambda c:[Summon(1,'missing')])
        self.watch('wait','minion_counter_check',lambda c:[self.pause(c),InvokeBehavior('bad',c.source_id,1)])
        g=self.armed(board=('wait',));self.play(g);s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s)

    def test_spell_only_effect_does_not_counter_minion(self):
        self.r.register_behavior('wrong',lambda c:[CounterSpell(c.window.id)]);self.secret('wrong','wrong')
        self.script('set',lambda c:[SetSecret(2,'wrong')]);g=self.game(hand=('set','cry'));self.play(g,'set');self.play(g)
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.play_history[-1].countered);self.check(g)

    def test_generic_counter_and_duplicate_counter_are_idempotent(self):
        self.r.register_behavior('generic',lambda c:[CounterCard(c.window.id),CounterMinion(c.window.id),CounterCard(c.window.id)])
        self.secret('generic','generic');self.script('set',lambda c:[SetSecret(2,'generic')]);g=self.game(hand=('set','cry'));self.play(g,'set');self.play(g)
        self.assertEqual(sum(e.kind=='minion_countered' for e in g.events),1);self.check(g)

    def test_stale_counter_does_not_change_completed_play(self):
        self.script('stale',lambda c:[CounterCard(999),CounterMinion(999)])
        g=self.game(hand=('cry','stale'));self.play(g);self.play(g,'stale');self.assertFalse(g.state.play_history[0].countered);self.check(g)

    def test_entry_listeners_only_run_after_success(self):
        self.watch('entry','minion_play_accepted',lambda c:[GainArmor(1,5)])
        g=self.armed(hand=('cry','cry'),board=('entry',));self.play(g);self.assertEqual(self.armor(g),0)
        self.play(g);self.assertEqual(self.armor(g),7)
        events=[e.kind for e in g.events if e.action==g.state.action_number]
        self.assertLess(events.index('minion_counter_check'),events.index('minion_play_accepted'))
        self.assertLess(events.index('minion_play_accepted'),events.index('battlecry_started'));self.check(g)

    def test_generic_counter_supports_spell_window(self):
        self.r.register_secret_condition('spell',lambda c:c.window is not None and c.window.kind=='spell' and not c.window.countered and c.window.player_id!=c.player_id)
        self.r.register_behavior('any',lambda c:[CounterMinion(c.window.id),CounterCard(c.window.id)])
        self.r.register_card(CardDefinition('spellcounter','spellcounter',CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec('spellcounter',('card_committed',),'spell','any')))
        self.script('set',lambda c:[SetSecret(2,'spellcounter')]);self.script('spell',lambda c:[GainArmor(1,99)])
        g=self.game(hand=('set','spell'));self.play(g,'set');self.play(g,'spell')
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[-1].countered)
        self.assertEqual(sum(e.kind=='spell_countered' for e in g.events),1);self.check(g)

    def magnetic(self):
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,attack=2,health=3,
            metadata=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))))
        self.card('magnetic',keywords=(Keyword.MAGNETIC,),magnetic_tribes=('mech',))

    def test_magnetic_target_lost_during_commit_falls_back_to_entry(self):
        self.magnetic();self.watch('kill','card_committed',lambda c:[Destroy(c.play.magnetic_target_id)] if c.play.magnetic_target_id else [])
        g=self.game(hand=('magnetic',),board=('mech','kill'));i=g.state.players[1].hand[0]
        g.apply(PlayCard(1,i,position=0));self.assertEqual(g.state.play_history[-1].minion_result,'summoned')
        self.assertFalse(g.state.magnetic_history);self.assertEqual(g.state.players[1].board[0],i)
        self.assertEqual(self.armor(g),2);self.check(g)

    def test_magnetic_merge_has_one_accepted_event_and_no_battlecry(self):
        self.magnetic();self.watch('entry','minion_play_accepted',lambda c:[GainArmor(1,5)])
        g=self.game(hand=('magnetic',),board=('mech','entry'));g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
        self.assertEqual(self.armor(g),5);self.assertEqual(g.state.play_history[-1].minion_result,'magnetized')
        self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_magnetic_material_does_not_grant_entry_battlecry_to_host(self):
        self.magnetic();self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.game(hand=('magnetic','bounce'),board=('mech',));host=g.state.players[1].board[0]
        g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
        self.assertFalse(any(a.kind=='battlecry' for a in g.state.entities[host].abilities))
        self.play(g,'bounce');self.play(g,'mech');self.assertEqual(self.armor(g),0)
        self.assertFalse(g.state.battlecry_history);self.check(g)

    def test_nested_attack_pauses_inside_pending_minion_window(self):
        self.watch('fight','card_committed',lambda c:[ForceAttack(c.state.players[1].board[0],c.state.players[2].board[0])]
            if c.play.kind==CardType.MINION else [])
        self.watch('wait','attack_declared',lambda c:[self.pause(c)])
        g=self.armed(board=('body','fight','wait'),enemy=('body',));self.play(g)
        self.assertEqual([w.kind for w in g.state.action_windows],['minion','attack']);self.check(g)
        self.choose(g);self.assertTrue(g.state.play_history[-1].countered);self.check(g)

    def test_post_entry_removal_does_not_rewrite_captured_policy(self):
        from hs_sim.engine import RemoveBattlecryRepeatModifier
        self.watch('remove','minion_play_accepted',lambda c:[RemoveBattlecryRepeatModifier(1,m.id) for m in c.state.players[1].battlecry_modifiers])
        self.script('permanent',lambda c:[AddBattlecryRepeatModifier(1,source_id=c.source_id)])
        g=self.game(hand=('permanent','cry'),board=('remove',));self.play(g,'permanent');self.play(g)
        self.assertEqual(self.armor(g),4);self.assertFalse(g.state.players[1].battlecry_modifiers);self.check(g)

    def test_board_full_failure_retains_policy_and_skips_rewind_offer(self):
        self.card('rewind',keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        self.watch('fill','card_committed',lambda c:[Summon(1,'body') for _ in range(6)] if c.play.kind==CardType.MINION else [])
        g=self.game(hand=('grant','rewind'),board=('fill',));self.play(g,'grant');self.play(g,'rewind')
        self.assertIsNone(g.state.pending_choice);self.assertEqual(g.state.play_history[-1].minion_result,'board_full')
        self.assertEqual(g.state.players[1].battlecry_modifiers[0].uses_remaining,1);self.check(g)

    def test_pending_zone_corruption_rejected(self):
        self.pause_at();g=self.armed(board=('wait',));self.play(g)
        for mutation in ('missing','duplicate','graveyard'):
            s=g.snapshot();p=s['state']['players']['1'];i=p['pending_plays'][0]
            if mutation=='missing':p['pending_plays']=[]
            elif mutation=='duplicate':p['hand'].append(i)
            else:s['state']['entities'][str(i)]['zone']='graveyard';p['graveyard'].append(i);p['pending_plays']=[]
            self.reject(s)

    def test_window_provenance_and_flags_rejected(self):
        self.pause_at();g=self.armed(board=('wait',));self.play(g)
        for changes in ({'play_id':1},{'kind':'spell'},{'countered':True},{'target_phase':True},{'forced':True},{'counter_phase':False}):
            s=g.snapshot();s['state']['action_windows'][-1].update(changes);self.reject(s)

    def test_missing_duplicate_and_wrong_phase_marker_rejected(self):
        self.pause_at();g=self.armed(board=('wait',));self.play(g)
        for mutation in ('missing','duplicate','phase','id'):
            s=g.snapshot();marker=self.nested(s['resolution_frame'],'ResolveMinionPlay');self.assertIsNotNone(marker)
            if mutation=='id':marker['fields']['window_id']=999
            elif mutation=='phase':marker['type']=marker['type'].replace('ResolveMinionPlay','MinionCounterPhase')
            else:
                queue=s['resolution_frame']['fields']['continuation']['tuple']
                if mutation=='missing':queue.remove(marker)
                else:queue.append(deepcopy(marker))
            self.reject(s)

    def test_settled_minion_result_corruption_rejected(self):
        g=self.armed();self.play(g)
        for changes in ({'minion_result':None},{'minion_result':'summoned'},{'countered':False},{'minion_result':'invalid'}):
            s=g.snapshot();s['state']['play_history'][-1].update(changes);self.reject(s)

    def test_old_snapshot_and_view_versions_rejected(self):
        g=self.game();s=g.snapshot();s['schema_version']=74
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        self.assertEqual(g.observe(1)['version'],'player-view-v85')


class RepresentativeMinionCounterTests(unittest.TestCase):
    def setUp(self):self.r=build_registry()
    def game(self,hand,board=()):
        return Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('MAW_006',),max_mana=10,mana=10),
            PlayerSetup('HERO_02',hand=hand,board=board,deck=('CS2_182',)*3,max_mana=10,mana=10))),self.r)
    def arm(self,g):g.apply(PlayCard(1,g.state.players[1].hand[0]));g.apply(EndTurn(1))
    def check(self,g):
        self.assertEqual(Game.from_snapshot(g.snapshot(),self.r).snapshot(),g.snapshot())
        self.assertEqual(replay(build_replay(g),self.r).snapshot(),g.snapshot())
    def test_real_objection_cancels_scarab_without_discovery(self):
        g=self.game(('LOE_029',));self.arm(g);g.apply(PlayCard(2,g.state.players[2].hand[0]))
        self.assertIsNone(g.state.pending_choice);self.assertFalse(g.state.battlecry_history)
        self.assertEqual(g.state.play_history[-1].minion_result,'countered');self.check(g)
    def test_real_objection_cancels_magnetic_before_host_changes(self):
        g=self.game(('BOT_563',),('BOT_548',));self.arm(g);host=g.state.players[2].board[0];before=g.state.entities[host]
        g.apply(PlayCard(2,g.state.players[2].hand[0],position=0));after=g.state.entities[host]
        self.assertEqual((before.attack,before.health),(after.attack,after.health));self.assertFalse(g.state.magnetic_history);self.check(g)
    def test_real_objection_does_not_counter_spell(self):
        g=self.game(('CS2_029',));self.arm(g);g.apply(PlayCard(2,g.state.players[2].hand[0],g.state.players[1].hero_id))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].health,24);self.assertEqual(len(g.state.players[1].secrets),1);self.check(g)
    def test_player_interface_counter_and_double_discovery_example(self):
        from examples.minion_counter_windows import run
        g,s=run();self.assertEqual(len(g.history),8);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertIsNotNone(s['state']['pending_choice']);self.check(g)


if __name__=='__main__':unittest.main()
