"""Accepted-cast hand facts, physical residence, frozen play/history and privacy."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
import unittest
from dataclasses import replace
import test_m5_hand_progress as foundation
from hs_sim.engine import (Game,CardDefinition,CardType,HandProgressSpec,HeldSpellProgress,
    held_spell_condition,AddSpellRepeatModifier,EndTurn,RewindSpec,Keyword,TriggerSpec,
    CastSpell,CastWhenDrawnSpec,SnapshotError,ResolutionError,IllegalAction,UseHeroPower,
    UpgradeHandCard,Zone,SpellRepeatSpec)
from hs_sim.engine.effects import (GainArmor,AddToHand,Draw,Damage,Destroy,ReturnToHand,
    Silence,Summon,RequestChoice,ChoiceOption,InvokeBehavior)
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard,AddToDeck
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.battlecry_sources import RepeatBattlecry,TriggerBattlecry
from hs_sim.engine.summon_sources import MinionReference
from hs_sim.engine.played_battlecries import RepeatPlayedBattlecry


class HeldSpellTests(unittest.TestCase):
    spell=foundation.HandProgressTests.spell
    minion=foundation.HandProgressTests.minion
    game=foundation.HandProgressTests.game
    find=foundation.HandProgressTests.find
    play=foundation.HandProgressTests.play
    card=foundation.HandProgressTests.card
    progress=foundation.HandProgressTests.progress
    ref=foundation.HandProgressTests.ref
    check=foundation.HandProgressTests.check

    def setUp(self):
        foundation.HandProgressTests.setUp(self)
        self.r.register_behavior('conditional',lambda c:[AddSpellRepeatModifier(c.player_id,uses=1,source_id=c.source_id)] if held_spell_condition(c) else [])
        self.minion('held',HandProgressSpec('spell_cast'),battlecry='conditional')
        self.minion('two',HandProgressSpec('spell_cast',goal=2),battlecry='conditional')
        self.spell('armor',lambda c:[GainArmor(1,2)])
        self.minion('retainer',retain_rewind_outcomes=True)
        self.minion('double',spell_repeats=(SpellRepeatSpec(class_mode='any'),))
    def cry(self,cid,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,battlecry=cid)
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,triggers=(TriggerSpec(event,cid),))
    def armor(self,g):return g.state.entities[g.state.players[1].hero_id].armor
    def mods(self,g):return g.state.players[1].spell_modifiers
    def chosen(self,g,option='ok'):
        from hs_sim.engine import SelectChoice
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,(option,)))
    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as e:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(e.exception))
    def marked(self,hand=('held',),board=(),enemy_hand=()):
        g=self.game(hand=(*hand,'low'),board=board,enemy_hand=enemy_hand);self.play(g,'low');return g

    def test_no_prior_spell_yields_no_modifier(self):
        g=self.game(hand=('held','armor'));self.play(g,'held');self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertFalse(self.mods(g));self.check(g)

    def test_prior_spell_marks_hand_and_freezes_qualified_play(self):
        g=self.marked(hand=('held','armor'));self.assertTrue(self.progress(g,'held').consumed)
        self.play(g,'held');p=g.state.play_history[-1]
        self.assertTrue(p.held_spells.completed);self.assertEqual(p.held_spells.cast_ids,(1,))
        self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_all_held_cards_mark_atomically_before_reactions(self):
        self.watch('watch','hand_progressed',lambda c:[GainArmor(1,sum(a.consumed for i in c.state.players[1].hand
            for a in c.state.entities[i].abilities if a.kind=='hand_progress'))])
        g=self.marked(hand=('held','held'),board=('watch',));self.assertEqual(self.armor(g),4);self.check(g)

    def test_cast_before_card_is_acquired_does_not_count(self):
        self.spell('acquire',lambda c:[AddToHand(1,'held')])
        g=self.game(hand=('low','acquire'));self.play(g,'low');self.play(g,'acquire')
        self.assertFalse(self.progress(g,'held').consumed);self.play(g,'held');self.assertFalse(self.mods(g));self.check(g)

    def test_nested_cast_after_acquisition_in_same_action_counts(self):
        self.spell('nested',lambda c:[AddToHand(1,'held'),CastSpell(1,'armor',c.source_id)])
        g=self.game(hand=('nested',));self.play(g,'nested')
        self.assertEqual(self.progress(g,'held').progress_keys,('cast:2',));self.play(g,'held')
        self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_later_repetition_can_mark_card_acquired_during_first_cast(self):
        self.spell('acquire',lambda c:[AddToHand(1,'held')])
        g=self.game(hand=('acquire',),board=('double',));self.play(g,'acquire')
        progress=[next(a for a in g.state.entities[i].abilities if a.kind=='hand_progress') for i in g.state.players[1].hand]
        self.assertEqual([a.consumed for a in progress],[True,False]);self.check(g)

    def test_two_spell_condition_counts_independent_repeated_casts(self):
        g=self.marked(hand=('two',),board=('double',))
        self.assertEqual(self.progress(g,'two').progress_keys,('cast:1','cast:2'));self.play(g,'two')
        self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_countered_spell_does_not_mark(self):
        self.cry('arm',lambda c:[SetSecret(2,'EX1_287')])
        g=self.game(hand=('held','arm','low'));self.play(g,'arm');self.play(g,'low')
        self.assertFalse(self.progress(g,'held').consumed);self.play(g,'held');self.assertFalse(self.mods(g));self.check(g)

    def test_accepted_empty_spell_counts(self):
        g=self.marked();self.assertEqual(self.progress(g,'held').progress_keys,('cast:1',));self.check(g)

    def test_enemy_spell_does_not_count(self):
        g=self.game(hand=('held',),enemy_hand=('low',));g.apply(EndTurn(1));self.play(g,'low')
        self.assertFalse(self.progress(g,'held').consumed);self.check(g)

    def test_nonspell_play_and_hero_power_do_not_count(self):
        g=self.game(hand=('held','plain'));self.play(g,'plain')
        g.apply(UseHeroPower(1,g.state.players[1].hero_power_id))
        self.assertFalse(self.progress(g,'held').consumed);self.check(g)

    def test_generated_cast_counts_for_condition_but_does_not_consume_grant(self):
        self.cry('auto',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.game(hand=('held','auto','auto'));self.play(g,'auto');self.play(g,'held');self.play(g,'auto')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_draw_cast_counts_at_accepted_payload(self):
        self.spell('drawn',lambda c:[],keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        self.cry('draw',lambda c:[AddToDeck(1,'drawn',position='top'),Draw(1)])
        g=self.game(hand=('held','draw'));self.play(g,'draw')
        self.assertTrue(self.progress(g,'held').consumed);self.check(g)

    def test_historical_spell_counts_without_hand_play(self):
        self.cry('recast',lambda c:[RecastSpell(1,1,c.source_id)])
        self.cry('acquire',lambda c:[AddToHand(1,'held')])
        g=self.game(hand=('low','acquire','recast'));self.play(g,'low');self.play(g,'acquire');self.play(g,'recast')
        self.assertEqual(self.progress(g,'held').progress_keys,('cast:2',));self.check(g)

    def test_failed_automatic_target_does_not_count(self):
        self.spell('targeted',lambda c:[],requires_target=True)
        self.cry('auto',lambda c:[CastSpell(1,'targeted',c.source_id,target_id=9999,targeting='explicit')])
        g=self.game(hand=('held','auto'));self.play(g,'auto')
        self.assertFalse(self.progress(g,'held').consumed);self.check(g)

    def test_optional_cast_filter_receives_cast_context(self):
        self.r.register_trigger_condition('only_auto',lambda c:c.cast.origin=='effect')
        self.minion('filtered',HandProgressSpec('spell_cast',condition_id='only_auto'),battlecry='conditional')
        self.cry('auto',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.marked(hand=('filtered','auto'));self.assertFalse(self.progress(g,'filtered').consumed)
        self.play(g,'auto');self.assertTrue(self.progress(g,'filtered').consumed);self.check(g)

    def test_nonboolean_condition_rolls_back_entire_cast(self):
        self.r.register_trigger_condition('bad',lambda c:1)
        self.minion('bad',HandProgressSpec('spell_cast',condition_id='bad'))
        g=self.game(hand=('bad','low'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'low')
        self.assertEqual(g.snapshot(),before)

    def test_current_copy_inherits_earned_state_base_copy_does_not(self):
        self.cry('copy',lambda c:[CopyCard(self.ref(c,'held'),1,mode='current'),CopyCard(self.ref(c,'held'),1,mode='base')])
        g=self.marked(hand=('held','copy'));self.play(g,'copy')
        values=[next(a for a in g.state.entities[i].abilities if a.kind=='hand_progress').consumed for i in g.state.players[1].hand]
        self.assertEqual(values,[True,True,False]);self.check(g)

    def test_copy_created_before_spell_counts_independently(self):
        self.cry('copy',lambda c:[CopyCard(self.ref(c,'two'),1,mode='current')])
        g=self.game(hand=('two','copy','low','low'));self.play(g,'low');self.play(g,'copy');self.play(g,'low')
        values=[next(a for a in g.state.entities[i].abilities if a.kind=='hand_progress') for i in g.state.players[1].hand]
        self.assertEqual([a.progress_value for a in values],[2,2]);self.assertNotEqual(values[0].id,values[1].id);self.check(g)

    def test_hand_transfer_resets_earned_state(self):
        self.cry('transfer',lambda c:[MoveCard(self.ref(c,'held'),2,Zone.HAND)])
        g=self.marked(hand=('held','transfer'));self.play(g,'transfer')
        self.assertFalse(self.progress(g,'held',2).consumed);self.check(g)

    def test_leave_hand_and_redraw_resets_same_entity(self):
        self.cry('cycle',lambda c:[MoveCard(self.ref(c,'held'),1,Zone.DECK,position='top'),Draw(1)])
        g=self.marked(hand=('held','cycle'));i=self.find(g,'held');self.play(g,'cycle')
        self.assertEqual(self.find(g,'held'),i);self.assertFalse(self.progress(g,'held').consumed);self.check(g)

    def test_return_from_board_resets_but_old_play_remains_true(self):
        self.cry('bounce',lambda c:[ReturnToHand(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='held'))])
        g=self.marked(hand=('held','bounce'));self.play(g,'held');old=g.state.play_history[-1]
        self.play(g,'bounce');self.assertFalse(self.progress(g,'held').consumed)
        self.assertTrue(old.held_spells.completed);self.check(g)

    def test_hand_upgrade_replaces_condition_with_new_form(self):
        self.cry('upgrade',lambda c:[UpgradeHandCard(self.ref(c,'held'),'two')])
        g=self.marked(hand=('held','upgrade'));self.play(g,'upgrade')
        self.assertEqual(self.progress(g,'two').progress_value,0);self.check(g)

    def test_held_card_play_uses_frozen_condition_after_entry_mutation(self):
        self.watch('silencer','minion_play_accepted',lambda c:[Silence(c.event.source_id)]
            if c.state.entities[c.event.source_id].card_id=='held' else [])
        # A silence may suppress the captured Battlecry itself; the immutable play
        # still must retain its true original held condition.
        g=self.marked(hand=('held',),board=('silencer',));self.play(g,'held')
        self.assertTrue(g.state.play_history[-1].held_spells.completed);self.check(g)

    def test_discovery_pause_restores_cast_witness_without_recount(self):
        self.spell('pause',lambda c:[self.pause(c),GainArmor(1,1)])
        g=self.game(hand=('two','pause'));self.play(g,'pause');self.check(g)
        self.assertEqual(self.progress(g,'two').progress_value,1)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for branch in (g,restored):self.chosen(branch)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.progress(g,'two').progress_value,1);self.check(g)

    def test_failed_choice_restores_pending_and_original_fact(self):
        self.spell('bad',lambda c:[RequestChoice(1,(ChoiceOption('ok','OK',(AddSpellRepeatModifier(1,source_id=99999),)),),source_id=c.source_id)])
        g=self.game(hand=('held','bad'));self.play(g,'bad');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.chosen(g)
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_payload_failure_rolls_back_condition_fact(self):
        self.spell('bad',lambda c:[AddToHand(1,'missing')]);g=self.game(hand=('held','bad'));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_normal_rewind_replaces_fact_instead_of_counting_attempts(self):
        self.spell('rewind',lambda c:[GainArmor(1,1)],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(hand=('two','rewind'));self.play(g,'rewind');self.check(g);self.chosen(g,'retry')
        self.assertEqual(self.progress(g,'two').progress_value,1);self.assertEqual(self.progress(g,'two').progress_keys,('cast:1',));self.check(g)

    def test_retained_outcomes_do_not_create_extra_cast_witnesses(self):
        self.spell('rewind',lambda c:[],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(hand=('two','rewind'),board=('retainer',));self.play(g,'rewind')
        self.assertEqual(self.progress(g,'two').progress_value,1);self.check(g)

    def test_retained_and_repeated_casts_count_physical_casts(self):
        self.spell('rewind',lambda c:[],rewind=RewindSpec(1),keywords=(Keyword.REWIND,))
        g=self.game(hand=('two','rewind'),board=('retainer','double'));self.play(g,'rewind')
        self.assertEqual(self.progress(g,'two').progress_value,2);self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_terminal_cast_after_acceptance_keeps_fact(self):
        self.spell('fatal',lambda c:[Damage(c.state.players[2].hero_id,40,c.source_id)])
        g=self.game(hand=('held','fatal'));self.play(g,'fatal')
        self.assertTrue(self.progress(g,'held').consumed);self.assertEqual(g.state.status,'finished');self.check(g)

    def test_historical_hand_battlecry_uses_original_frozen_condition(self):
        self.cry('repeat',lambda c:[RepeatBattlecry(1,c.source_id,next(b.id for b in c.state.battlecry_history if b.payload.card_id=='held'))])
        g=self.marked(hand=('held','repeat'));self.play(g,'held');self.play(g,'repeat')
        self.assertEqual(len(self.mods(g)),2);self.check(g)

    def test_played_history_uses_original_unqualified_condition(self):
        self.cry('repeat',lambda c:[RepeatPlayedBattlecry(1,c.source_id,next(p.id for p in c.state.play_history if p.card_id=='held'))])
        g=self.game(hand=('held','low','repeat'));self.play(g,'held');self.play(g,'low');self.play(g,'repeat')
        self.assertFalse(self.mods(g));self.check(g)

    def test_direct_summoned_carrier_is_unqualified(self):
        self.cry('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='held')]),c.source_id)])
        g=self.game(hand=('low','trigger'),board=('held',));self.play(g,'low');self.play(g,'trigger')
        self.assertFalse(self.mods(g));self.check(g)

    def test_hidden_hand_progress_does_not_leak_to_opponent(self):
        g=self.marked();view=g.observe(2);text=json.dumps(view)
        self.assertNotIn('cast_ids',text);self.assertNotIn('progress_keys',text);self.assertNotIn('held_spells',text)
        self.assertTrue(all('hand_progress' not in c for c in view['players'][0]['hand']))
        own=g.observe(1)['players'][0]['hand'][0]['hand_progress'];self.assertEqual(own['kind'],'spell_cast');self.assertTrue(own['completed']);self.check(g)

    def test_invalid_spec_callbacks_and_repeat_rejected(self):
        for kw in (dict(on_complete='x'),dict(on_progress='x'),dict(upgrade_card_id='x'),dict(repeat=True),dict(event='x')):
            with self.subTest(kw=kw),self.assertRaises(ValueError):HandProgressSpec('spell_cast',**kw)

    def test_snapshot_rejects_invalid_live_cast_witness_and_count(self):
        g=self.marked()
        for changes in ({'progress_keys':['cast:99']},{'progress_keys':['event:1']},{'progress_value':0},
                        {'progress_completions':2},{'progress_keys':['cast:1','cast:1']}):
            s=g.snapshot();a=next(a for a in s['state']['entities'][str(self.find(g,'held'))]['abilities'] if a['kind']=='hand_progress')
            a.update(changes);self.reject(s)

    def test_snapshot_rejects_frozen_play_fact_corruption(self):
        g=self.marked();self.play(g,'held')
        for changes in ({'cast_ids':[99]},{'before_cast_id':1},{'before_cast_id':True},{'cast_ids':[1,1]},{'extra':1}):
            s=g.snapshot();s['state']['play_history'][-1]['held_spells'].update(changes);self.reject(s)

    def test_countered_cast_cannot_be_forged_as_witness(self):
        self.cry('arm',lambda c:[SetSecret(2,'EX1_287')]);g=self.game(hand=('arm','low','held'));self.play(g,'arm');self.play(g,'low')
        s=g.snapshot();a=next(a for a in s['state']['entities'][str(self.find(g,'held'))]['abilities'] if a['kind']=='hand_progress')
        a.update(progress_value=1,progress_completions=1,consumed=True,progress_keys=['cast:1']);self.reject(s)

    def test_old_snapshot_schema_rejected(self):
        g=self.marked();s=g.snapshot();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION);s['schema_version']=85;self.reject(s)

    def test_current_copy_to_enemy_inherits_fact_without_forging_enemy_cast(self):
        self.cry('copy',lambda c:[CopyCard(self.ref(c,'held'),2,mode='current')])
        g=self.marked(hand=('held','copy'));self.play(g,'copy');g.apply(EndTurn(1));self.play(g,'held')
        self.assertEqual(len(g.state.players[2].spell_modifiers),1)
        self.assertEqual(g.state.play_history[-1].held_spells.cast_ids,(1,));self.check(g)

    def test_card_acquired_in_commit_window_counts_at_later_acceptance(self):
        self.watch('watch','card_committed',lambda c:[AddToHand(1,'held')]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.game(hand=('low',),board=('watch',));self.play(g,'low')
        self.assertTrue(self.progress(g,'held').consumed);self.check(g)

    def test_automatic_start_reaction_acquires_before_payload_acceptance(self):
        self.watch('watch','spell_cast_started',lambda c:[AddToHand(1,'held')])
        self.cry('auto',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.game(hand=('auto',),board=('watch',));self.play(g,'auto')
        self.assertTrue(self.progress(g,'held').consumed);self.check(g)

    def test_direct_qualified_board_carrier_keeps_earned_condition(self):
        self.cry('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[next(
            i for i in c.state.players[1].board if c.state.entities[i].card_id=='held')]),c.source_id)])
        g=self.marked(hand=('held','trigger'));self.play(g,'held');self.play(g,'trigger')
        self.assertEqual(len(self.mods(g)),2);self.check(g)

    def test_historical_effect_battlecry_rejects_missing_frozen_fact(self):
        self.cry('trigger',lambda c:[TriggerBattlecry(MinionReference.capture(c.state.entities[next(
            i for i in c.state.players[1].board if c.state.entities[i].card_id=='held')]),c.source_id)])
        self.cry('repeat',lambda c:[RepeatBattlecry(1,c.source_id,next(b.id for b in c.state.battlecry_history
            if b.payload.card_id=='held' and b.origin=='effect'))])
        g=self.game(hand=('trigger','repeat'),board=('held',));self.play(g,'trigger');before=g.snapshot()
        with self.assertRaisesRegex(ResolutionError,'no frozen held-spell facts'):self.play(g,'repeat')
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_history_chain_keeps_original_fact_after_original_bounces(self):
        self.cry('bounce',lambda c:[ReturnToHand(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='held'))])
        self.cry('repeat',lambda c:[RepeatBattlecry(1,c.source_id,next(b.id for b in reversed(c.state.battlecry_history)
            if b.payload.card_id=='held'))])
        g=self.marked(hand=('held','bounce','repeat','repeat'));self.play(g,'held');self.play(g,'bounce')
        self.play(g,'repeat');self.play(g,'repeat')
        self.assertEqual(len(self.mods(g)),3);self.assertFalse(self.progress(g,'held').consumed);self.check(g)

    def test_live_progress_stops_at_goal_even_with_more_casts(self):
        g=self.game(hand=('held','low','low'));self.play(g,'low');self.play(g,'low')
        self.assertEqual(self.progress(g,'held').progress_keys,('cast:1',));self.check(g)

    def test_snapshot_requires_explicit_frozen_condition_field(self):
        g=self.marked();self.play(g,'held');s=g.snapshot();del s['state']['play_history'][-1]['held_spells'];self.reject(s)

    def test_actual_twinbow_pinned_declaration(self):
        card=self.r.card('TSC_071');self.assertEqual((card.cost,card.attack,card.health),(4,4,4))
        self.assertIn('naga',card.metadata.tribes);self.assertEqual(card.hand_progress,HandProgressSpec('spell_cast'))

    def test_actual_unqualified_twinbow_does_not_grant(self):
        g=self.game(hand=('TSC_071','armor'));self.play(g,'TSC_071');self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertFalse(self.mods(g));self.check(g)

    def test_actual_qualified_twinbow_policy_survives_turn_change(self):
        g=self.marked(hand=('TSC_071','armor'));self.play(g,'TSC_071');g.apply(EndTurn(1));g.apply(EndTurn(2))
        self.play(g,'armor');self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_actual_brann_twinbow_grants_independent_overlapping_budgets(self):
        g=self.marked(hand=('TSC_071','armor'),board=('LOE_077',));self.play(g,'TSC_071')
        self.assertEqual(len(self.mods(g)),2);self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_actual_twinbow_next_countered_spell_consumes_without_repetition(self):
        self.cry('arm',lambda c:[SetSecret(2,'EX1_287')])
        g=self.marked(hand=('TSC_071','arm','armor'));self.play(g,'TSC_071');self.play(g,'arm');self.play(g,'armor')
        self.assertEqual(self.armor(g),0);self.assertFalse(self.mods(g));self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_native_representative_terminal_example_restores_and_replays(self):
        from examples.held_spells import run
        g,s=run();self.assertEqual(s['schema_version'],SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual((len(g.history),len(g.state.cast_history),len(g.state.spell_policy_receipts)),(11,6,1))
        self.assertEqual(g.state.winner,1)


if __name__=='__main__':unittest.main()
