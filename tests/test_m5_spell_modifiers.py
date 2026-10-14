"""R-131: hand commitment budgets, live aura windows and durable consumption."""
import json
import unittest
from dataclasses import replace
import test_m5_spell_repeats as foundation
from hs_sim.engine import (AddSpellRepeatModifier as Add, RemoveSpellRepeatModifier as Remove,
    SpellRepeatSpec, CardDefinition, CardType, CardClass, Game, PlayCard, EndTurn,
    TriggerSpec, RewindSpec, Keyword, SnapshotError, ResolutionError, IllegalAction,
    Ruleset, ResolutionLimitExceeded, CastWhenDrawnSpec, AddToDeck)
from hs_sim.engine.effects import (GainArmor, Damage, Draw, Destroy, Silence, ChangeControl,
    ReturnToHand, ReplaceHero, RequestChoice, ChoiceOption, Summon, InvokeBehavior)
from hs_sim.engine.spell_casts import CastSpell
from hs_sim.engine.spell_history import RecastSpell
from hs_sim.engine.secrets import SetSecret
from hs_sim.engine.serialization import canonical_hash


class SpellModifierTests(unittest.TestCase):
    minion=foundation.SpellRepeatTests.minion
    spell=foundation.SpellRepeatTests.spell
    game=foundation.SpellRepeatTests.game
    play=foundation.SpellRepeatTests.play
    hero=foundation.SpellRepeatTests.hero
    board=foundation.SpellRepeatTests.board
    events=foundation.SpellRepeatTests.events
    choose=foundation.SpellRepeatTests.choose
    check=foundation.SpellRepeatTests.check

    def setUp(self):
        foundation.SpellRepeatTests.setUp(self)
        self.spell('armor',lambda c:[GainArmor(c.player_id,2)])
        self.granter('one',uses=1);self.granter('three',uses=3)
        self.granter('forever');self.granter('turn',uses=1,temporary=True)
        self.minion('retainer',health=4,retain_rewind_outcomes=True)
    def granter(self,cid,*,temporary=False,player=1,extra=(),**kw):
        self.cry(cid,lambda c:[Add(player,source_id=c.source_id,expires_turn=c.state.turn if temporary else None,**kw),*extra])
    def cry(self,cid,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,health=4,battlecry=cid)
    def watch(self,cid,event,fn):
        self.r.register_behavior(cid,fn);self.minion(cid,health=4,triggers=(TriggerSpec(event,cid),))
    def ready(self,grant='one',hand=('armor',),board=(),**kw):
        g=self.game(hand=(grant,*hand),board=board,**kw);self.play(g,grant);return g
    def mods(self,g,p=1):return g.state.players[p].spell_modifiers
    def armor(self,g,p=1):return self.hero(g,p).armor
    def receipt(self,g):return g.state.spell_policy_receipts[-1]
    def pause(self,c):return RequestChoice(c.player_id,(ChoiceOption('ok','OK',()),),source_id=c.source_id)
    def reject(self,s):
        s['state_hash']=canonical_hash({k:v for k,v in s.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as error:Game.from_snapshot(s,self.r)
        self.assertNotIn('digest mismatch',str(error.exception))
    def cycle(self,g):g.apply(EndTurn(1));g.apply(EndTurn(2))

    def test_one_use_counts_play_not_physical_casts(self):
        g=self.ready(hand=('armor','armor'));self.play(g,'armor')
        self.assertEqual((self.armor(g),len(g.state.cast_history),len(g.state.play_history)),(4,2,2))
        self.assertFalse(self.mods(g));self.play(g,'armor');self.assertEqual(self.armor(g),6)
        self.assertEqual(len(g.state.spell_policy_receipts),1);self.check(g)

    def test_three_uses_survive_turns_then_fourth_is_normal(self):
        g=self.ready('three',hand=('armor',)*4);self.play(g,'armor');self.cycle(g)
        self.assertEqual(self.mods(g)[0].uses_remaining,2)
        for _ in range(3):self.play(g,'armor')
        self.assertEqual(self.armor(g),14);self.assertFalse(self.mods(g))
        self.assertEqual([r.modifiers[0].uses_remaining for r in g.state.spell_policy_receipts],[3,2,1]);self.check(g)

    def test_unlimited_policy_records_without_consuming(self):
        g=self.ready('forever',hand=('armor','armor'));self.play(g,'armor');self.play(g,'armor')
        self.assertEqual(self.armor(g),8);self.assertIsNone(self.mods(g)[0].uses_remaining)
        self.assertFalse(self.events(g,'spell_modifier_used'));self.check(g)

    def test_unused_this_turn_expires(self):
        g=self.ready('turn');self.cycle(g);self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertFalse(g.state.spell_policy_receipts)
        self.assertEqual(len(self.events(g,'spell_modifier_expired')),1);self.check(g)

    def test_used_this_turn_does_not_expire_again(self):
        g=self.ready('turn');self.play(g,'armor');self.cycle(g)
        self.assertFalse(self.events(g,'spell_modifier_expired'));self.check(g)

    def test_expiry_uses_global_turn_for_enemy_policy(self):
        self.granter('enemy',player=2,uses=1,temporary=True)
        g=self.ready('enemy',hand=());self.assertEqual(len(self.mods(g,2)),1)
        g.apply(EndTurn(1));self.assertFalse(self.mods(g,2));self.check(g)

    def test_all_expired_policies_removed_before_reactions(self):
        self.watch('observer','spell_modifier_expired',lambda c:[GainArmor(1,len(c.state.players[1].spell_modifiers))])
        g=self.ready('turn',hand=('turn',),board=('observer',));self.play(g,'turn');g.apply(EndTurn(1))
        self.assertEqual(self.armor(g),0);self.assertEqual(len(self.events(g,'spell_modifier_expired')),2);self.check(g)

    def test_same_turn_grant_from_expiry_reaction_stabilizes(self):
        self.watch('observer','spell_modifier_expired',lambda c:[Destroy(c.source_id),Add(1,uses=1,expires_turn=c.state.turn)])
        g=self.ready('turn',hand=(),board=('observer',));g.apply(EndTurn(1))
        self.assertFalse(self.mods(g));self.assertEqual(len(self.events(g,'spell_modifier_expired')),2);self.check(g)

    def test_minion_play_does_not_consume(self):
        g=self.ready(hand=('plain','armor'));self.play(g,'plain');self.assertEqual(self.mods(g)[0].uses_remaining,1)
        self.play(g,'armor');self.assertEqual(self.armor(g),4);self.check(g)

    def test_overlapping_finite_and_unlimited_use_max_and_consume_all(self):
        self.granter('four',spec=SpellRepeatSpec(4,'any'),uses=3)
        g=self.ready('one',hand=('four','forever','armor'),board=('any',))
        self.play(g,'four');self.play(g,'forever');self.play(g,'armor')
        self.assertEqual(self.armor(g),8);self.assertEqual(len(self.receipt(g).modifiers),3)
        self.assertEqual([m.uses_remaining for m in self.mods(g)],[2,None]);self.check(g)

    def test_same_count_policies_do_not_multiply(self):
        g=self.ready(hand=('one','armor'),board=('any',));self.play(g,'one');self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_countered_spell_consumes_without_repeating(self):
        self.granter('armed',uses=1,extra=(SetSecret(2,'EX1_287'),))
        g=self.ready('armed',hand=('armor','armor'));self.play(g,'armor')
        self.assertEqual(self.armor(g),0);self.assertTrue(g.state.play_history[-1].countered)
        self.assertFalse(self.mods(g));self.assertFalse(g.state.spell_repeats)
        self.play(g,'armor');self.assertEqual(self.armor(g),2);self.check(g)

    def test_failed_payment_does_not_consume(self):
        self.spell('costly',lambda c:[],cost=11)
        g=self.ready(hand=('costly',));before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g,'costly')
        self.assertEqual(g.snapshot(),before)

    def test_new_policy_in_commit_reaction_waits_for_next_play(self):
        self.watch('observer','card_committed',lambda c:[Add(1,uses=1)] if c.event.source_id and c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.game(hand=('armor','armor'),board=('observer',));self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.mods(g)),1)
        self.play(g,'armor');self.assertEqual(self.armor(g),6);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_remove_captured_policy_in_commit_does_not_cancel_current_casts(self):
        self.watch('observer','card_committed',lambda c:[Remove(1,m.id) for m in c.state.players[1].spell_modifiers]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready('three',board=('observer',));self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertFalse(self.mods(g));self.check(g)

    def test_aura_added_in_commit_still_applies_at_acceptance(self):
        self.watch('observer','card_committed',lambda c:[Summon(1,'any')]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.game(hand=('armor',),board=('observer',));self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertFalse(g.state.spell_policy_receipts);self.check(g)

    def test_aura_removed_in_commit_does_not_use_early_capture(self):
        self.granter('twice',uses=1)
        self.minion('triple',health=4,spell_repeats=(SpellRepeatSpec(3,'any'),))
        self.watch('observer','card_committed',lambda c:[Silence(i) for i in c.state.players[1].board
            if c.state.entities[i].card_id=='triple'] if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready('twice',board=('observer','triple'));self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.check(g)

    def test_policy_source_silence_death_and_control_do_not_revoke_player_budget(self):
        for fn in (Silence,Destroy,lambda i:ChangeControl(i,2),ReturnToHand):
            with self.subTest(effect=fn):
                self.setUp();self.cry('mutate',lambda c,fn=fn:[fn(next(i for i in c.state.players[1].board if c.state.entities[i].card_id=='one'))])
                g=self.ready(hand=('mutate','armor'));self.play(g,'mutate');self.play(g,'armor')
                self.assertEqual(self.armor(g),4);self.check(g)

    def test_other_player_cannot_use_budget(self):
        g=self.ready(hand=(),enemy_hand=('armor',));g.apply(EndTurn(1));self.play(g,'armor')
        self.assertEqual(self.armor(g,2),2);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_cross_class_filter_uses_captured_hero_class(self):
        self.granter('foreign',spec=SpellRepeatSpec(),uses=1)
        self.watch('change','card_committed',lambda c:[ReplaceHero(1,'HERO_08')]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready('foreign',board=('change',));self.play(g,'armor')
        self.assertEqual(self.receipt(g).hero_class,CardClass.WARRIOR)
        self.assertEqual(g.state.players[1].hero_class,CardClass.MAGE);self.assertEqual(self.armor(g),4);self.check(g)

    def test_neutral_same_and_dual_class_spells_do_not_consume_foreign_policy(self):
        self.granter('foreign',spec=SpellRepeatSpec(),uses=1)
        for cid,cls in (('neutral',CardClass.NEUTRAL),('same',CardClass.WARRIOR),('dual',(CardClass.WARRIOR,CardClass.MAGE))):
            self.spell(cid,lambda c:[GainArmor(1,1)],cls=cls)
        g=self.ready('foreign',hand=('neutral','same','dual','armor'))
        for cid in ('neutral','same','dual'):self.play(g,cid)
        self.assertEqual(self.mods(g)[0].uses_remaining,1);self.play(g,'armor');self.assertEqual(self.armor(g),7);self.check(g)

    def test_unknown_cross_class_metadata_fails_atomically(self):
        self.granter('foreign',spec=SpellRepeatSpec(),uses=1);self.spell('unknown',lambda c:[],cls=None)
        g=self.ready('foreign',hand=('unknown',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'unknown')
        self.assertEqual(g.snapshot(),before)

    def test_unfiltered_policy_accepts_unknown_spell_metadata(self):
        self.spell('unknown',lambda c:[GainArmor(1,1)],cls=None)
        g=self.ready(hand=('unknown',));self.play(g,'unknown');self.assertEqual(self.armor(g),2);self.check(g)

    def test_generated_automatic_cast_does_not_consume_or_repeat(self):
        self.cry('auto',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.ready(hand=('auto','armor'));self.play(g,'auto');self.assertEqual(self.armor(g),2)
        self.assertEqual(len(self.mods(g)),1);self.play(g,'armor');self.assertEqual(self.armor(g),6);self.check(g)

    def test_nested_automatic_casts_do_not_recapture(self):
        self.spell('outer',lambda c:[CastSpell(1,'armor',c.source_id)])
        g=self.ready('three',hand=('outer',));self.play(g,'outer')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.mods(g)[0].uses_remaining,2)
        self.assertEqual(len(g.state.spell_policy_receipts),1);self.check(g)

    def test_historical_cast_does_not_consume(self):
        self.cry('history',lambda c:[RecastSpell(1,c.state.cast_history[0].id,c.source_id)])
        g=self.game(hand=('armor','one','history'),board=());self.play(g,'armor');self.play(g,'one');self.play(g,'history')
        self.assertEqual(self.armor(g),4);self.assertEqual(len(self.mods(g)),1);self.check(g)

    def test_independent_choices_suspend_and_restore_without_second_consumption(self):
        self.spell('pause',lambda c:[self.pause(c),GainArmor(1,1)])
        g=self.ready('three',hand=('pause',));self.play(g,'pause');self.check(g)
        self.assertEqual(self.mods(g)[0].uses_remaining,2)
        restored=Game.from_snapshot(g.snapshot(),self.r)
        for branch in (g,restored):
            self.choose(branch,'ok');self.assertIsNotNone(branch.state.pending_choice);self.check(branch)
            self.choose(branch,'ok');self.assertIsNone(branch.state.pending_choice)
        self.assertEqual(g.snapshot(),restored.snapshot());self.assertEqual(self.armor(g),2)

    def test_real_discovery_is_independent_per_cast(self):
        g=self.ready(hand=('GDB_873',));self.play(g,'GDB_873');self.check(g)
        first=g.state.pending_choice;self.choose(g,first.options[0].id)
        self.assertIsNotNone(g.state.pending_choice);self.assertEqual(len(g.state.players[1].combo_modifiers),1)
        self.choose(g,g.state.pending_choice.options[0].id)
        self.assertEqual(len(g.state.players[1].combo_modifiers),2);self.assertEqual(len(g.state.spell_policy_receipts),1);self.check(g)

    def test_choose_one_uses_same_branch_twice(self):
        g=self.ready(hand=('EX1_164',));self.play(g,'EX1_164',branch='draw')
        self.assertEqual(len(g.state.players[1].hand),6);self.check(g)

    def test_rewind_retry_restores_budget_before_recapture(self):
        self.spell('rewind',lambda c:[GainArmor(1,c.rewind_attempt+1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('three',hand=('rewind',));self.play(g,'rewind');self.check(g)
        self.choose(g,'retry');self.assertEqual(self.mods(g)[0].uses_remaining,2)
        self.assertEqual(len(g.state.spell_policy_receipts),1);self.assertEqual(self.armor(g),4);self.check(g)

    def test_retained_rewind_results_do_not_recapture(self):
        self.spell('rewind',lambda c:[GainArmor(1,1)],keywords=(Keyword.REWIND,),rewind=RewindSpec(1))
        g=self.ready('three',hand=('rewind',),board=('retainer',));self.play(g,'rewind')
        self.assertEqual(self.armor(g),4);self.assertEqual(self.mods(g)[0].uses_remaining,2)
        self.assertEqual(len(g.state.spell_policy_receipts),1);self.check(g)

    def test_mid_payload_grant_does_not_change_current_repeat_count(self):
        self.spell('give',lambda c:[Add(1,uses=1),GainArmor(1,1)])
        g=self.ready(hand=('give',));self.play(g,'give')
        self.assertEqual(self.armor(g),2);self.assertEqual(len(self.mods(g)),2)
        self.assertEqual(g.state.spell_repeats[-1].casts,2);self.check(g)

    def test_terminal_first_cast_cancels_repeat_without_refunding(self):
        self.spell('fatal',lambda c:[Damage(c.state.players[2].hero_id,50,c.source_id)])
        g=self.ready(hand=('fatal',));self.play(g,'fatal')
        self.assertEqual(g.state.status,'finished');self.assertFalse(self.mods(g))
        self.assertTrue(g.state.spell_repeats[-1].interrupted);self.check(g)

    def test_terminal_commit_reaction_keeps_consumption_without_repeat_record(self):
        self.watch('fatal','card_committed',lambda c:[Damage(c.state.players[2].hero_id,50,c.source_id)]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready(board=('fatal',));self.play(g,'armor')
        self.assertEqual(g.state.status,'finished');self.assertFalse(g.state.spell_repeats)
        self.assertFalse(self.mods(g));self.check(g)

    def test_payload_failure_rolls_back_whole_play_and_consumption(self):
        self.spell('bad',lambda c:[Add(1,source_id=99999)])
        g=self.ready(hand=('bad',));before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'bad')
        self.assertEqual(g.snapshot(),before)

    def test_choice_failure_restores_pending_state_with_single_consumption(self):
        self.spell('bad',lambda c:[RequestChoice(1,(ChoiceOption('bad','Bad',(Add(1,source_id=99999),)),),source_id=c.source_id)])
        g=self.ready('three',hand=('bad',));self.play(g,'bad');before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'bad')
        self.assertEqual(g.snapshot(),before);self.assertEqual(self.mods(g)[0].uses_remaining,2);self.check(g)

    def test_resolution_budget_exhaustion_rolls_back_consumption(self):
        self.granter('huge',spec=SpellRepeatSpec(500,'any'),uses=1)
        g=self.ready('huge',rules=Ruleset(max_resolution_steps=80));before=g.snapshot()
        with self.assertRaises(ResolutionLimitExceeded):self.play(g,'armor')
        self.assertEqual(g.snapshot(),before)

    def test_public_policy_facts_hide_sources_receipts_and_internal_ids(self):
        g=self.ready('three');self.play(g,'armor')
        for p in (1,2):
            view=g.observe(p);mods=view['players'][0]['spell_modifiers']
            self.assertEqual(mods,[dict(casts=2,class_mode='any',match=None,uses_remaining=2,expires_turn=None)])
            text=json.dumps(view)
            for forbidden in ('spell_policy_receipts','policy_source_id','modifier_id','source_card_id'):
                self.assertNotIn(forbidden,text)
        self.check(g)

    def test_pending_grant_effect_round_trips(self):
        self.cry('delayed',lambda c:[self.pause(c),Add(1,uses=3)])
        g=self.game(hand=('delayed','armor'),board=());self.play(g,'delayed');self.check(g)
        self.choose(g,'ok');self.play(g,'armor');self.assertEqual(self.mods(g)[0].uses_remaining,2);self.check(g)

    def test_invalid_effect_arguments_and_expired_grant_rejected(self):
        for args in (dict(player_id=True),dict(player_id=1,uses=0),dict(player_id=1,uses=True),
                     dict(player_id=1,expires_turn=0),dict(player_id=1,spec={}),dict(player_id=1,source_id=False)):
            with self.subTest(args=args),self.assertRaises(ValueError):Add(**args)
        self.cry('old',lambda c:[Add(1,expires_turn=1)])
        g=self.game(hand=('old',),board=());self.cycle(g);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.play(g,'old')
        self.assertEqual(g.snapshot(),before)

    def test_snapshot_rejects_modifier_identity_lifetime_and_spec_corruption(self):
        g=self.ready('three')
        for change in ({'uses_remaining':0},{'uses_remaining':True},{'id':99999},{'created_turn':99},
                       {'source_id':None},{'expires_turn':0},{'spec':{'casts':1,'class_mode':'any'}}, {'extra':1}):
            s=g.snapshot();s['state']['players']['1']['spell_modifiers'][0].update(change);self.reject(s)

    def test_snapshot_rejects_duplicate_live_attachment_identity(self):
        g=self.ready('three');s=g.snapshot();rows=s['state']['players']['1']['spell_modifiers'];rows.append(dict(rows[0]));self.reject(s)
        s=g.snapshot();s['state']['players']['1']['spell_modifiers'][0]['id']=g.state.entities[g.state.players[1].board[0]].abilities[0].id;self.reject(s)

    def test_snapshot_rejects_receipt_order_type_scope_and_stale_live_uses(self):
        g=self.ready('three');self.play(g,'armor')
        for change in ({'id':2},{'play_id':1},{'hero_class':'invalid'},{'modifiers':[]},{'extra':1}):
            s=g.snapshot();s['state']['spell_policy_receipts'][0].update(change);self.reject(s)
        s=g.snapshot();s['state']['players']['1']['spell_modifiers'][0]['uses_remaining']=3;self.reject(s)
        s=g.snapshot();s['state']['spell_repeats'][0]['casts']=3;self.reject(s)

    def test_snapshot_rejects_receipt_reuse_and_inconsistent_captured_uses(self):
        g=self.ready('three',hand=('armor','armor'));self.play(g,'armor');self.play(g,'armor')
        s=g.snapshot();s['state']['spell_policy_receipts'][1]['modifiers'][0]['uses_remaining']=3;self.reject(s)
        s=g.snapshot();s['state']['spell_policy_receipts'].reverse();self.reject(s)

    def test_snapshot_rejects_forged_public_policy_event(self):
        g=self.ready('three');self.play(g,'armor')
        for change in ({'casts':True},{'uses_remaining':None},{'policy_source_id':1}):
            s=g.snapshot();e=next(e for e in s['information']['players']['1']['events'] if e['kind']=='spell_modifier_used')
            e['spell_modifier'].update(change);self.reject(s)

    def test_old_schema_and_observation_version_rejected(self):
        g=self.ready();s=g.snapshot();self.assertEqual(s['schema_version'],266);s['schema_version']=84;self.reject(s)
        s=g.snapshot();s['information']['version']='player-view-v48';self.reject(s)

    def test_draw_cast_does_not_consume_or_repeat_player_budget(self):
        self.spell('drawn',lambda c:[GainArmor(1,3)],keywords=(Keyword.CASTS_WHEN_DRAWN,),cast_when_drawn=CastWhenDrawnSpec())
        self.cry('draw',lambda c:[AddToDeck(1,'drawn',position='top'),Draw(1)])
        g=self.ready(hand=('draw',));self.play(g,'draw')
        self.assertEqual(self.armor(g),3);self.assertEqual(len(self.mods(g)),1)
        self.assertFalse(g.state.spell_policy_receipts);self.check(g)

    def test_deathrattle_waits_until_both_repeated_payloads_finish(self):
        self.r.register_behavior('last',lambda c:[GainArmor(1,10)])
        self.minion('victim',health=1,deathrattle='last')
        self.spell('kill_and_count',lambda c:[Damage(c.target_id,1,c.source_id),GainArmor(1,len(c.state.players[1].board))],requires_target=True)
        g=self.ready(hand=('kill_and_count',),board=('victim',));self.play(g,'kill_and_count',g.state.players[1].board[0])
        self.assertEqual(self.armor(g),14);self.assertEqual(len(g.state.death_history),1);self.check(g)

    def test_receipt_cannot_reuse_a_live_unrelated_attachment_id(self):
        g=self.ready('three');self.play(g,'armor');s=g.snapshot()
        s['state']['spell_policy_receipts'][0]['modifiers'][0]['id']=g.state.entities[g.state.players[1].board[0]].abilities[0].id
        self.reject(s)

    def test_paused_commit_before_repeat_plan_restores_consumption(self):
        self.watch('observer','card_committed',lambda c:[self.pause(c)]
            if c.state.entities[c.event.source_id].kind==CardType.SPELL else [])
        g=self.ready('three',board=('observer',));self.play(g,'armor')
        self.assertEqual(self.mods(g)[0].uses_remaining,2);self.assertFalse(g.state.spell_repeats);self.check(g)
        self.choose(g,'ok');self.assertEqual(self.armor(g),4);self.check(g)

    def test_untargeted_empty_spell_still_consumes_and_records_two_casts(self):
        g=self.ready(hand=('noop',));self.play(g,'noop')
        self.assertFalse(self.mods(g));self.assertEqual(len(g.state.cast_history),2);self.check(g)

    def test_actual_electra_repeats_next_spell_and_uses_pinned_stats(self):
        card=self.r.card('BOT_411');self.assertEqual((card.cost,card.attack,card.health),(3,3,3))
        self.assertIn('elemental',card.metadata.tribes)
        g=self.game(hand=('BOT_411','CS2_029'),board=());self.play(g,'BOT_411')
        self.play(g,'CS2_029',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,18)
        self.assertFalse(self.mods(g));self.assertEqual(g.state.players[1].mana,3);self.check(g)

    def test_actual_electra_expires_unused(self):
        g=self.game(hand=('BOT_411','CS2_029'),board=());self.play(g,'BOT_411');self.cycle(g)
        self.play(g,'CS2_029',self.hero(g,2).id);self.assertEqual(self.hero(g,2).health,24)
        self.assertFalse(g.state.spell_policy_receipts);self.check(g)

    def test_actual_tyrande_has_three_uses_and_no_expiry(self):
        card=self.r.card('EDR_464');self.assertEqual((card.cost,card.attack,card.health),(7,5,7))
        g=self.game(hand=('EDR_464',)+('armor',)*4,board=());self.play(g,'EDR_464')
        self.assertIsNone(self.mods(g)[0].expires_turn);self.cycle(g)
        for _ in range(4):self.play(g,'armor')
        self.assertEqual(self.armor(g),14);self.assertFalse(self.mods(g));self.check(g)

    def test_actual_sources_summoned_without_battlecry_grant_nothing(self):
        self.cry('summon',lambda c:[Summon(1,'BOT_411'),Summon(1,'EDR_464')])
        g=self.game(hand=('summon','armor'),board=());self.play(g,'summon');self.play(g,'armor')
        self.assertEqual(self.armor(g),2);self.assertFalse(self.mods(g));self.check(g)

    def test_brann_tyrande_grants_two_budgets_that_overlap_by_max(self):
        g=self.game(hand=('EDR_464','armor'),board=('LOE_077',));self.play(g,'EDR_464')
        self.assertEqual([m.uses_remaining for m in self.mods(g)],[3,3]);self.play(g,'armor')
        self.assertEqual(self.armor(g),4);self.assertEqual([m.uses_remaining for m in self.mods(g)],[2,2]);self.check(g)

    def test_native_representative_terminal_example_restores_and_replays(self):
        from examples.spell_modifiers import run
        g,s=run();self.assertEqual(s['schema_version'],266)
        self.assertEqual((len(g.history),len(g.state.cast_history),len(g.state.spell_policy_receipts)),(12,7,3))
        self.assertEqual(g.state.winner,1)


if __name__=='__main__':unittest.main()
