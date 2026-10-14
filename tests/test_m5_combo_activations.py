"""Independent Combo identity, accepted payloads and resumable progress (R-127)."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
import test_m5_battlecries as foundation
from hs_sim.engine import (Game, Registry, CardDefinition, CardType, PlayCard, Keyword,
    TargetSpec, TargetMode, RewindSpec, AppendageSpec, BattlecryRepeatSpec,
    ChooseOneSpec, ChooseBranch, ComboPayload, ComboRecord, activated_combos,
    IllegalAction, ResolutionError, SnapshotError, EndTurn)
from hs_sim.engine.effects import (GainArmor, Damage, Summon, Silence, Destroy,
    Transform, ChangeControl, ReturnToHand, CopyMinion, InvokeBehavior, RandomDamage)
from hs_sim.engine.combos import BeginCombo, FinishCombo
from hs_sim.engine.replay import build_replay, replay


class ComboActivationTests(unittest.TestCase):
    script=foundation.BattlecryTests.script
    watch=foundation.BattlecryTests.watch
    game=foundation.BattlecryTests.game
    choose=foundation.BattlecryTests.choose
    pause=foundation.BattlecryTests.pause
    armor=foundation.BattlecryTests.armor
    check=foundation.BattlecryTests.check
    reject=foundation.BattlecryTests.reject
    nested=foundation.BattlecryTests.nested

    def setUp(self):
        foundation.BattlecryTests.setUp(self)
        self.script('prime',lambda c:[])
        self.card('combo')

    def card(self,cid,fn=None,kind=CardType.MINION,**kw):
        if fn is not None:self.r.register_behavior(cid,fn)
        if kind in (CardType.MINION,CardType.HERO):kw.setdefault('health',4 if kind==CardType.MINION else 30)
        if kind==CardType.WEAPON:kw.setdefault('attack',2);kw.setdefault('durability',2)
        kw['keywords']=tuple(dict.fromkeys((*kw.get('keywords',()),Keyword.COMBO)))
        self.r.register_card(CardDefinition(cid,cid,kind,cost=2,combo=cid if fn else 'armor',**kw))

    def play(self,g,cid='combo',target=None):
        return foundation.BattlecryTests.play(self,g,cid,target)

    def ready(self,cid='combo',*,board=(),enemy=(),tail=()):
        g=self.game(hand=('prime',cid,*tail),board=board,enemy=enemy)
        self.play(g,'prime');return g

    def records(self,g):return g.state.combo_history

    def test_false_condition_keeps_declaration_without_activation(self):
        g=self.game(hand=('combo',));self.play(g)
        self.assertEqual(self.records(g),[]);self.assertEqual(self.armor(g),0)
        self.assertEqual(len(g.state.play_history[0].combos),1);self.check(g)

    def test_enabled_combo_has_one_payment_and_independent_identity(self):
        g=self.ready();i=self.play(g);b=self.records(g)[0]
        self.assertEqual((b.source_id,b.player_id,b.card_id,b.play_id,b.iteration),(i,1,'combo',2,1))
        self.assertTrue(b.completed);self.assertFalse(b.interrupted)
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(2,8,2))
        self.assertEqual(g.state.battlecry_history,[]);self.assertEqual(len(g.state.cast_history),1);self.check(g)

    def test_context_carries_captured_condition_and_actual_activation(self):
        self.card('context',lambda c:[GainArmor(c.player_id,c.play.prior_turn_plays+c.combo.id)])
        g=self.ready('context');self.play(g,'context');self.assertEqual(self.armor(g),2);self.check(g)

    def test_generic_payload_runs_even_when_combo_is_disabled(self):
        self.card('mixed',on_play='armor');g=self.game(hand=('mixed',));self.play(g,'mixed')
        self.assertEqual(self.armor(g),2);self.assertEqual(self.records(g),[]);self.check(g)

    def test_generic_battlecry_then_combo_and_repeat_policy_are_independent(self):
        self.r.register_behavior('ordinary',lambda c:[GainArmor(1,5)])
        self.card('mixed',lambda c:[GainArmor(1,c.state.entities[c.state.players[1].hero_id].armor)],
            on_play='ordinary',battlecry='armor')
        self.r.register_card(CardDefinition('repeat','repeat',CardType.MINION,health=3,battlecry_repeats=(BattlecryRepeatSpec(),)))
        g=self.ready('mixed',board=('repeat',));self.play(g,'mixed')
        self.assertEqual(self.armor(g),18);self.assertEqual(len(g.state.battlecry_history),2)
        self.assertEqual(len(self.records(g)),1);self.check(g)

    def test_combo_does_not_enter_battlecry_historical_candidates(self):
        from hs_sim.engine import PlayedBattlecryQuery, played_battlecry_candidates
        g=self.ready();self.play(g)
        self.assertEqual(played_battlecry_candidates(g.state,1,PlayedBattlecryQuery()),());self.check(g)

    def test_normal_summon_does_not_activate_combo(self):
        self.script('summon',lambda c:[Summon(1,'combo')]);g=self.ready('summon');self.play(g,'summon')
        self.assertEqual(self.records(g),[]);self.assertEqual(self.armor(g),0);self.check(g)

    def test_copy_preserves_declaration_with_distinct_attachment_identity(self):
        self.script('copy',lambda c:[CopyMinion(c.state.players[1].board[0],1)])
        g=self.ready('copy',board=('combo',));self.play(g,'copy')
        ids=[next(a.id for a in g.state.entities[i].abilities if a.kind=='combo') for i in g.state.players[1].board]
        self.assertEqual(len(set(ids)),2);self.assertEqual(self.records(g),[]);self.check(g)

    def test_silence_removes_passive_declaration(self):
        self.script('silence',lambda c:[Silence(c.state.players[1].board[0])])
        g=self.ready('silence',board=('combo',));self.play(g,'silence')
        self.assertFalse(any(a.kind=='combo' for a in g.state.entities[g.state.players[1].board[0]].abilities));self.check(g)

    def test_bounce_and_replay_allocate_new_declaration(self):
        self.script('bounce',lambda c:[ReturnToHand(c.state.players[1].board[0])])
        g=self.ready(tail=('bounce',));self.play(g);self.play(g,'bounce');self.play(g)
        self.assertEqual(self.armor(g),4)
        self.assertNotEqual(*[b.payload.ability_id for b in self.records(g)]);self.check(g)

    def test_weapon_combo_runs_after_equipping(self):
        self.card('weapon',lambda c:[GainArmor(1,3 if c.state.players[1].weapon_id==c.source_id else 99)],kind=CardType.WEAPON)
        g=self.ready('weapon');self.play(g,'weapon');self.assertEqual(self.armor(g),3);self.check(g)

    def test_hero_card_combo_runs_after_replacement(self):
        self.card('hero_card',lambda c:[GainArmor(1,3 if c.state.players[1].hero_id==c.source_id else 99)],
            kind=CardType.HERO,hero_card=True,initial_hero_power='power')
        g=self.ready('hero_card');self.play(g,'hero_card');self.assertEqual(self.armor(g),3);self.check(g)

    def test_dormant_hand_play_can_activate_combo(self):
        self.card('sleep',dormant_turns=2);g=self.ready('sleep');i=self.play(g,'sleep')
        self.assertIsNotNone(g.state.entities[i].dormancy);self.assertEqual(self.armor(g),2);self.check(g)

    def test_colossal_combo_runs_after_appendages(self):
        self.card('giant',lambda c:[GainArmor(c.player_id,len(c.state.players[c.player_id].board))],colossal=(AppendageSpec('body'),),keywords=(Keyword.COLOSSAL,))
        for name,fn in (('silence_giant',Silence),('kill_giant',Destroy),('steal_giant',lambda i:ChangeControl(i,2))):
            self.watch(name,'minion_summoned',lambda c,fn=fn:[fn(c.event.source_id)]
                if c.state.entities[c.event.source_id].card_id=='giant' else [])
        g=self.ready('giant');self.play(g,'giant');self.assertEqual(self.armor(g),2)
        self.assertTrue(g.state.colossal_history[0].completed);self.check(g)
        for name in ('silence_giant','kill_giant','steal_giant'):
            with self.subTest(before_capture=name):
                g=self.ready('giant',board=(name,));self.play(g,'giant')
                self.assertEqual(len(g.state.play_history[-1].combos),1)
                self.assertEqual(self.records(g),[])
                self.check(g)

    def test_entry_reactions_preserve_accepted_combo(self):
        mutations={'kill':lambda i:Destroy(i),'silence':lambda i:Silence(i),'steal':lambda i:ChangeControl(i,2),
            'morph':lambda i:Transform(i,'body'),'bounce':lambda i:ReturnToHand(i)}
        for name,fn in mutations.items():self.watch(name,'minion_summoned',lambda c,fn=fn:[fn(c.event.source_id)])
        for name in mutations:
            with self.subTest(mutation=name):
                g=self.ready(board=(name,));self.play(g)
                self.assertEqual((self.armor(g),self.armor(g,2)),(2,0))
                self.assertEqual(self.records(g)[0].card_id,'combo');self.check(g)

    def test_started_listener_mutations_preserve_captured_body(self):
        for name,fn in (('silence',Silence),('kill',Destroy),('bounce',ReturnToHand)):
            self.watch(name,'combo_started',lambda c,fn=fn:[fn(c.event.source_id)])
        for name in ('silence','kill','bounce'):
            with self.subTest(mutation=name):
                g=self.ready(board=(name,));self.play(g);self.assertEqual(self.armor(g),2);self.check(g)

    def test_started_listener_has_activation_context_with_original_player(self):
        self.watch('steal','combo_started',lambda c:[ChangeControl(c.event.source_id,2),GainArmor(c.combo.player_id,3)])
        g=self.ready(board=('steal',));i=self.play(g)
        self.assertEqual(g.state.entities[i].controller,2);self.assertEqual((self.armor(g),self.armor(g,2)),(5,0));self.check(g)

    def test_conditional_target_is_disabled_for_first_play(self):
        self.card('hit',lambda c:[Damage(c.target_id,2,c.source_id)],target_condition='combo',targeting=TargetSpec(TargetMode.IF_AVAILABLE))
        g=self.game(hand=('hit',));self.play(g,'hit');self.assertEqual(self.records(g),[]);self.check(g)

    def test_enabled_combo_uses_shared_manual_target_validation(self):
        self.card('hit',lambda c:[Damage(c.target_id,2,c.source_id)],target_condition='combo',targeting=TargetSpec(TargetMode.IF_AVAILABLE))
        g=self.ready('hit',enemy=('body',));snapshot=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'hit')
        self.assertEqual(g.snapshot(),snapshot);target=g.state.players[2].board[0]
        self.play(g,'hit',target);self.assertEqual(g.state.entities[target].health,3)
        self.assertEqual(self.records(g)[0].target_id,target);self.check(g)

    def test_target_leaving_before_body_skips_effect_without_retargeting(self):
        self.card('hit',lambda c:[Damage(c.target_id,2,c.source_id)],targeting=TargetSpec())
        self.watch('bounce','combo_started',lambda c:[ReturnToHand(c.event.target_id)])
        g=self.ready('hit',board=('bounce',),enemy=('body',));target=g.state.players[2].board[0]
        self.play(g,'hit',target);self.assertIn(target,g.state.players[2].hand)
        self.assertTrue(self.records(g)[0].completed);self.check(g)

    def test_full_board_during_counter_window_has_no_activation(self):
        self.watch('fill','minion_counter_check',lambda c:[Summon(1,'body') for _ in range(6)])
        g=self.ready(board=('fill',));self.play(g)
        self.assertEqual(g.state.play_history[-1].minion_result,'board_full')
        self.assertEqual(self.records(g),[]);self.assertEqual(len(g.state.play_history[-1].combos),1);self.check(g)

    def test_pause_before_begin_retains_queued_payload(self):
        self.r.register_behavior('pause',lambda c:[self.pause(c)])
        self.card('wait',on_play='pause');g=self.ready('wait');self.play(g,'wait')
        self.assertEqual(self.records(g),[]);self.check(g)
        restored=Game.from_snapshot(g.snapshot(),self.r);self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),2);self.check(g)

    def test_pause_in_started_listener_restores_captured_context(self):
        self.watch('pause','combo_started',lambda c:[self.pause(c)])
        g=self.ready(board=('pause',));self.play(g);self.assertFalse(self.records(g)[0].completed)
        self.check(g);restored=g.clone();self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),2);self.check(g)

    def test_pause_inside_combo_restores_and_finishes_once(self):
        self.card('wait',lambda c:[self.pause(c),GainArmor(c.combo.player_id,3)])
        g=self.ready('wait');self.play(g,'wait');self.assertFalse(self.records(g)[0].completed);self.check(g)
        restored=g.clone();self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def test_completion_listener_pause_has_completed_record(self):
        self.watch('pause','combo_finished',lambda c:[self.pause(c)])
        g=self.ready(board=('pause',));self.play(g);self.assertTrue(self.records(g)[0].completed)
        self.check(g);self.choose(g);self.check(g)

    def test_terminal_body_marks_interrupted(self):
        self.card('lethal',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id),GainArmor(1,99)])
        g=self.ready('lethal');self.play(g,'lethal')
        self.assertTrue(self.records(g)[0].interrupted);self.assertFalse(self.records(g)[0].completed)
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[-1].interrupted);self.check(g)

    def test_terminal_before_begin_does_not_invent_activation(self):
        self.watch('lethal','minion_summoned',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)])
        g=self.ready(board=('lethal',));self.play(g);self.assertEqual(self.records(g),[]);self.check(g)

    def test_mutation_and_random_failure_roll_back_payment_rng_and_history(self):
        self.card('bad',lambda c:[GainArmor(1,3),RandomDamage(tuple(c.state.players[p].hero_id for p in (1,2)),1,c.source_id),Summon(1,'unknown')])
        g=self.ready('bad');s=g.snapshot()
        with self.assertRaises(ResolutionError) as error:self.play(g,'bad')
        self.assertIn('unknown',str(error.exception))
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_failure_after_pause_rolls_back_to_pending_combo(self):
        self.r.register_behavior('bad',lambda c:[Summon(1,'unknown')])
        self.card('wait',lambda c:[self.pause(c),InvokeBehavior('bad',c.source_id,1)])
        g=self.ready('wait');self.play(g,'wait');s=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g)
        self.assertEqual(g.snapshot(),s);self.check(g)

    def test_rewind_retry_replaces_combo_history_and_payment(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('rewind');self.play(g,'rewind');self.check(g);self.choose(g,'retry')
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(self.records(g))),(3,8,1));self.check(g)

    def test_retained_outcomes_have_distinct_iteration_records(self):
        self.card('rewind',lambda c:[GainArmor(1,c.rewind_attempt+2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.ready('rewind',board=('retainer',));self.play(g,'rewind')
        self.assertEqual((self.armor(g),g.state.players[1].mana,len(g.state.play_history)),(9,8,2))
        self.assertEqual([b.iteration for b in self.records(g)],[1,2,3])
        self.assertEqual({b.outcome_id for b in self.records(g)},{1});self.check(g)

    def test_disabled_combo_remains_disabled_across_retained_outcomes(self):
        self.card('rewind',keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.game(hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual(self.armor(g),0);self.assertEqual(self.records(g),[])
        self.assertEqual(g.state.rewind_outcomes[0].completed,3);self.check(g)

    def test_retained_choices_restore_between_outcomes(self):
        self.card('rewind',lambda c:[self.pause(c),GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('rewind',board=('retainer',));self.play(g,'rewind');self.check(g);self.choose(g);self.check(g)
        self.assertEqual([b.completed for b in self.records(g)],[True,False])
        restored=g.clone();self.choose(g);self.choose(restored)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),3);self.check(g)

    def test_retained_payload_survives_source_transformation(self):
        self.card('rewind',lambda c:[Transform(c.source_id,'body'),GainArmor(1,2)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('rewind',board=('retainer',));i=self.play(g,'rewind')
        self.assertEqual(g.state.entities[i].card_id,'body');self.assertEqual(self.armor(g),4)
        self.assertEqual([b.card_id for b in self.records(g)],['rewind','rewind']);self.check(g)

    def test_retained_lethal_stops_further_activations(self):
        self.card('rewind',lambda c:[Damage(c.state.players[2].hero_id,100,c.source_id)],keywords=(Keyword.REWIND,),rewind=RewindSpec(2))
        g=self.ready('rewind',board=('retainer',));self.play(g,'rewind')
        self.assertEqual(len(self.records(g)),1);self.assertTrue(self.records(g)[0].interrupted);self.check(g)

    def test_history_queries_are_strict_and_player_scoped(self):
        g=self.ready(tail=('combo',));self.play(g);self.play(g)
        self.assertEqual(len(activated_combos(g.state,1,completed=True,turn=g.state.turn)),2)
        self.assertEqual(len(activated_combos(g.state,1,before_id=2)),1)
        self.assertEqual(activated_combos(g.state,2),());self.assertEqual(activated_combos(g.state,1,completed=False),())
        for kw in ({'completed':1},{'before_id':True},{'turn':-1}):
            with self.assertRaises(ValueError):activated_combos(g.state,1,**kw)
        with self.assertRaises(ValueError):activated_combos(g.state,True)

    def test_public_views_do_not_expose_diagnostic_history_or_events(self):
        g=self.ready();self.play(g)
        self.assertEqual(sum(e.kind.startswith('combo_') for e in g.events),2)
        for p in (1,2):
            public=json.dumps((g.observe(p),g.player_events(p)))
            for value in ('combo_history','combo_id','combo_started','combo_finished','behavior_id','combo_card_id'):
                self.assertNotIn(value,public)
        self.check(g)

    def test_player_command_uses_existing_legality(self):
        g=self.ready();p=g.for_player(1);listing=p.legal_actions();a=next(a for a in listing['actions'] if a['type']=='play_card')
        self.assertTrue(p.submit({'revision':listing['revision'],'action':a})['accepted'])
        self.assertEqual(len(self.records(g)),1);self.check(g)

    def test_snapshot_rejects_record_provenance_and_progress_tampering(self):
        g=self.ready();self.play(g)
        for changes in ({'play_id':1},{'card_id':'body'},{'target_id':999},{'id':2},{'iteration':2},
                {'completed':False},{'player_id':2},{'action':0},{'turn':99},{'outcome_id':99}):
            with self.subTest(changes=changes):
                s=g.snapshot();s['state']['combo_history'][0].update(changes);self.reject(s)

    def test_snapshot_rejects_unknown_and_mismatched_payload(self):
        g=self.ready();self.play(g)
        for changes in ({'behavior_id':'missing'},{'ability_id':999999},{'ability_id':True},{'card_id':'body'}):
            s=g.snapshot();s['state']['combo_history'][0]['payload'].update(changes);self.reject(s)

    def test_snapshot_rejects_duplicate_activation(self):
        g=self.ready();self.play(g);s=g.snapshot();b=deepcopy(s['state']['combo_history'][0]);b['id']=2
        s['state']['combo_history'].append(b);self.reject(s)

    def test_snapshot_rejects_missing_finish_marker(self):
        self.card('wait',lambda c:[self.pause(c)]);g=self.ready('wait');self.play(g,'wait');s=g.snapshot()
        marker=self.nested(s['resolution_frame'],'FinishCombo');self.assertIsNotNone(marker)
        marker['fields']['record_id']=99;self.reject(s)

    def test_snapshot_rejects_corrupt_queued_begin(self):
        self.watch('pause','minion_summoned',lambda c:[self.pause(c)])
        g=self.ready(board=('pause',));self.play(g);s=g.snapshot()
        marker=self.nested(s['resolution_frame'],'BeginComboBatch');self.assertIsNotNone(marker)
        marker['fields']['play_id']=1;self.reject(s)

    def test_snapshot_rejects_corrupt_retained_payload(self):
        self.card('rewind',lambda c:[self.pause(c)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('rewind',board=('retainer',));self.play(g,'rewind');s=g.snapshot()
        s['state']['rewind_outcomes'][0]['combos'][0]['behavior_id']='armor';self.reject(s)

    def test_previous_schema_and_missing_history_are_rejected(self):
        g=self.ready();s=g.snapshot();s['schema_version']=81
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,self.r)
        s=g.snapshot();del s['state']['combo_history'];self.reject(s)

    def test_invalid_definitions_reject_wrong_kinds_missing_keyword_and_choose_one_composite(self):
        for kind in (CardType.SPELL,CardType.HERO_POWER,CardType.LOCATION):
            with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',kind,combo='armor',keywords=(Keyword.COMBO,)))
        with self.assertRaises(ValueError):self.r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,combo='armor'))
        spec=ChooseOneSpec((ChooseBranch('a','A','armor'),ChooseBranch('b','B','armor')),ChooseBranch('both','Both','armor'))
        with self.assertRaisesRegex(ValueError,'Unsupported Choose One composite root declaration'):
            self.card('mixed-choice',choose_one=spec)
        self.assertNotIn('mixed-choice',self.r.cards)
        r=Registry('bad');r.register_card(CardDefinition('bad','bad',CardType.MINION,health=1,combo='missing',keywords=(Keyword.COMBO,)))
        with self.assertRaises(ValueError):r.freeze()

    def test_record_and_marker_scalar_types_reject_invalid_values(self):
        g=self.ready();self.play(g);record=self.records(g)[0]
        for changes in ({'player_id':True},{'iteration':0},{'interrupted':True},{'payload':'bad'},{'play_id':0}):
            with self.assertRaises(ValueError):replace(record,**changes)
        for args in ((True,1,record.payload),(1,True,record.payload),(1,1,'bad')):
            with self.assertRaises(ValueError):BeginCombo(*args)
        with self.assertRaises(ValueError):FinishCombo(True)

    def test_snapshot_rejects_mismatched_ability_declaration(self):
        g=self.game(board=('combo',));s=g.snapshot()
        entity=s['state']['entities'][str(g.state.players[1].board[0])]
        next(a for a in entity['abilities'] if a['kind']=='combo')['combo_card_id']='body';self.reject(s)

    def test_countered_combo_has_declaration_but_no_activation(self):
        from hs_sim.engine import CounterMinion, SecretSpec, SetSecret
        self.r.register_secret_condition('minion',lambda c:c.window is not None and
            c.window.kind=='minion' and not c.window.countered and c.window.player_id!=c.player_id)
        self.r.register_behavior('counter',lambda c:[CounterMinion(c.window.id)])
        self.r.register_card(CardDefinition('counter','counter',CardType.SPELL,keywords=(Keyword.SECRET,),
            secret=SecretSpec('counter',('minion_counter_check',),'minion','counter')))
        self.script('arm',lambda c:[SetSecret(2,'counter')])
        g=self.ready('arm',tail=('combo','combo'));self.play(g,'arm');self.play(g)
        self.assertTrue(g.state.play_history[-1].countered);self.assertEqual(self.records(g),[])
        self.assertEqual(len(g.state.play_history[-1].combos),1)
        self.play(g);self.assertEqual(len(self.records(g)),1);self.assertEqual(self.armor(g),2);self.check(g)

    def test_magnetic_attachment_does_not_activate_combo(self):
        from hs_sim.engine.model import CardMetadata, CardClass
        meta=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=('mech',))
        self.r.register_card(CardDefinition('mech','mech',CardType.MINION,health=4,metadata=meta))
        self.card('magnet',keywords=(Keyword.MAGNETIC,),metadata=meta,magnetic_tribes=('mech',))
        g=self.ready('magnet',board=('mech',));g.apply(PlayCard(1,g.state.players[1].hand[0],position=0))
        self.assertEqual(g.state.play_history[-1].minion_result,'magnetized')
        self.assertEqual(self.records(g),[]);self.assertEqual(len(g.state.play_history[-1].combos),1);self.check(g)

    def test_next_turn_resets_combo_condition(self):
        g=self.ready();g.apply(EndTurn(1));g.apply(EndTurn(2));self.play(g)
        self.assertFalse(g.state.play_history[-1].combo);self.assertEqual(self.records(g),[]);self.check(g)

    def test_hero_power_and_summon_do_not_count_as_hand_play(self):
        from hs_sim.engine import Scenario, PlayerSetup, UseHeroPower
        g=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('combo',),hero_power_card_id='power',board=('body',),mana=10,max_mana=10),
            PlayerSetup('hero')),seed=73),self.r)
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id));self.play(g)
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.play_history[-1].combo)
        self.assertEqual(self.records(g),[]);self.check(g)

    def test_snapshot_rejects_forged_captured_combo_context(self):
        self.watch('pause','combo_started',lambda c:[self.pause(c)])
        g=self.ready(board=('pause',));self.play(g);s=g.snapshot()
        context=self.nested(s['resolution_frame'],'RuleContext');self.assertIsNotNone(context)
        context['fields']['combo']['fields']['player_id']=2;self.reject(s)


class RepresentativeComboTests(unittest.TestCase):
    def test_existing_si7_and_edwin_use_independent_declarations(self):
        from hs_sim.engine.representative import build_registry
        r=build_registry()
        for cid in ('EX1_134','EX1_613'):
            self.assertIsNotNone(r.card(cid).combo);self.assertIsNone(r.card(cid).on_play)
        self.assertIsNone(r.card('EX1_124').combo);self.assertIsNotNone(r.card('EX1_124').on_play)

    def test_real_combo_example_restores_and_replays(self):
        from examples.combo_activations import run
        g,s=run();self.assertEqual(s['schema_version'],265)
        self.assertEqual([b.card_id for b in g.state.combo_history],['EX1_134','EX1_613'])
        self.assertEqual(len(g.state.battlecry_history),1)


if __name__=='__main__':unittest.main()
