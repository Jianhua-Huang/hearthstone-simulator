"""Real two-start rituals, original completion facts, draws and fixed bodies."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from functools import lru_cache
import json
import unittest

from hs_sim.cards.ritual_cards import DRAW, SUMMON, TOKEN, P as PROGRAM, load_batch, register_ritual_cards
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, IllegalAction, Keyword,
    PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.costs import local_cost
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RefreshMana, RequestChoice
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.model import CardClass, CardMetadata, PlayerEffectSpec, SpellSchool, SummonQuantitySpec
from hs_sim.engine.player_effects import RemovePlayerEffect
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry
from hs_sim.engine.rituals import KEY, RitualCompletion, completed_rituals
from hs_sim.engine.serialization import canonical_hash
from tools.card_batch import canonical, check_face

F='fixture.ritual.'
HIGH,MID,EXP,LOW,DOUBLE,WATCH,CANCEL,REFRESH,OTHER=(F+x for x in
    ('high','mid','exp','low','double','watch','cancel','refresh','other'))
META=CardMetadata(False,(CardClass.NEUTRAL,),None,tribes=())


@lru_cache(maxsize=None)
def fixture(mode=None,role='writer'):
    if role not in('writer','reader'):raise ValueError('Independent registry role required')
    r=build_registry();register_ritual_cards(r)
    for cid,cost in((HIGH,5),(MID,3),(EXP,7),(LOW,1)):
        r.register_card(CardDefinition(cid,cid,CardType.MINION,cost=cost,attack=1,health=6,metadata=META))
    r.register_card(CardDefinition(DOUBLE,DOUBLE,CardType.MINION,health=12,metadata=META,
        summon_quantities=(SummonQuantitySpec(2,(CardType.SPELL,)),)))
    def fail(c):raise ResolutionError('Ritual deliberate failure')
    r.register_behavior(F+'fail',fail)
    r.register_behavior(CANCEL,lambda c:tuple(RemovePlayerEffect(c.player_id,e.id)
        for e in c.state.players[c.player_id].player_effects if e.spec_id.startswith(PROGRAM)))
    r.register_behavior(REFRESH,lambda c:(RefreshMana(c.player_id,10),))
    for cid in(CANCEL,REFRESH):r.register_card(CardDefinition(cid,cid,CardType.SPELL,on_play=cid))
    r.register_behavior(OTHER,lambda c:())
    r.register_player_effect(PlayerEffectSpec(OTHER,OTHER,kind='sigil',duration=2,tick_event='turn_started',on_expire=OTHER))
    r.register_card(CardDefinition(OTHER,OTHER,CardType.SPELL,ongoing_effect_id=OTHER))
    if mode:
        def watch(c):
            if mode=='wait_summon':
                if c.state.entities[c.event.target_id].card_id!=TOKEN:return()
                owner=c.event.player_id
            else:
                if dict(c.event.data).get('effect_kind')!='ritual':return()
                owner=c.event.player_id
            if mode=='fail':return(InvokeBehavior(F+'fail',c.source_id,c.player_id),)
            others=tuple(RemovePlayerEffect(owner,e.id)for e in c.state.players[owner].player_effects
                if e.spec_id.startswith(PROGRAM))
            options=(ChoiceOption('ok','Completed:'+str(len(completed_rituals(c.state,owner)))),
                ChoiceOption('fail','Fail',(InvokeBehavior(F+'fail',c.source_id,c.player_id),)),
                ChoiceOption('cancel','Cancel remaining',others))
            return(RequestChoice(3-owner,options,c.source_id),)
        r.register_behavior(F+'watch',watch)
        r.register_card(CardDefinition(WATCH,WATCH,CardType.MINION,health=12,metadata=META,
            triggers=(TriggerSpec('minion_summoned'if mode=='wait_summon'else'player_effect_expired',F+'watch'),)))
    return r


class RitualCardTests(unittest.TestCase):
    def game(self,mode=None,*,hand=(SUMMON,),deck=(HIGH,MID,EXP,LOW)+(LOW,)*8,board=(),seat=1):
        self.mode=mode;self.seat=seat
        own=PlayerSetup('HERO_08',hand=hand,deck=deck,board=((WATCH,)if mode else())+board,mana=10,max_mana=10)
        other=PlayerSetup('HERO_01',deck=(LOW,)*16,mana=10,max_mana=10)
        return Game.from_scenario(Scenario((own,other)if seat==1 else(other,own),active_player=seat,seed=368),fixture(mode))
    def play(self,g,cid=SUMMON):
        i=next(i for i in g.state.players[self.seat].hand if g.state.entities[i].card_id==cid)
        g.apply(PlayCard(self.seat,i));return i
    def end(self,g,n=1):
        for _ in range(n):g.apply(EndTurn(g.state.active_player))
    def choose(self,g,key='ok'):
        q=g.state.pending_choice;g.apply(SelectChoice(q.player_id,q.id,(key,)))
    def effects(self,g):return[e for e in g.state.players[self.seat].player_effects if e.spec_id.startswith(PROGRAM)]
    def tokens(self,g):return[e for e in g.state.entities.values()if e.card_id==TOKEN and e.zone==Zone.BOARD]
    def portable(self,g):
        s=json.loads(json.dumps(g.snapshot()));r=fixture(self.mode,'reader')
        for other in(g.clone(),Game.from_snapshot(s,r),replay(build_replay(g),r)):
            self.assertTrue(other.snapshot()==s,'Original ritual clock, completion and payload must restore')
        return Game.from_snapshot(s,r)
    def rehash(self,s):
        s['events_hash']=canonical_hash(s['events']);s['state_hash']=canonical_hash({k:v for k,v in s.items()
            if k not in('schema_version','events','events_hash','state_hash')});return s
    def reject(self,g,edit):
        s=deepcopy(g.snapshot());edit(s)
        with self.assertRaises(SnapshotError):Game.from_snapshot(self.rehash(s),fixture(self.mode))

    def test_three_full_raw_faces_and_six_complete_primary_observations(self):
        d=load_batch();rows={x['record']['id']:x for x in d['cards']+d['dependencies']}
        self.assertEqual(set(rows),{DRAW,SUMMON,TOKEN});self.assertEqual(len(d['official_observations']),6)
        for row in rows.values():self.assertEqual(canonical(row['record']),row['record_sha256'])
        for o in d['official_observations']:
            check_face(rows[o['card_id']]['record'],o['face'],o['locale'],{'@':''}if o['card_id']!=TOKEN else None)
        for cid in(DRAW,SUMMON):
            card=fixture().card(cid);spec=fixture().player_effect(card.ongoing_effect_id)
            self.assertEqual((card.spell_school,spec.kind,spec.duration,spec.tick_event),(SpellSchool.SHADOW,'ritual',2,'turn_started'))
        self.assertIn(Keyword.TAUNT,fixture().card(TOKEN).keywords)

    def test_real_paid_spell_installs_one_source_independent_two_tick_ritual(self):
        g=self.game();source=self.play(g);effect,=self.effects(g)
        self.assertEqual((effect.source_id,effect.source_card_id,effect.remaining_turns),(source,SUMMON,2))
        self.assertEqual(g.state.players[1].mana,8);self.assertEqual(g.state.entities[source].zone,Zone.GRAVEYARD)
        self.assertEqual(completed_rituals(g.state,1),());self.portable(g)

    def test_only_two_future_actual_owner_starts_complete_after_installation(self):
        g=self.game();self.play(g);self.end(g);self.assertEqual(self.effects(g)[0].remaining_turns,2)
        self.end(g);self.assertEqual(self.effects(g)[0].remaining_turns,1);self.assertFalse(self.tokens(g))
        self.end(g);self.assertEqual(self.effects(g)[0].remaining_turns,1)
        self.end(g);self.assertFalse(self.effects(g));self.assertEqual(len(self.tokens(g)),2)
        row,=completed_rituals(g.state,1);self.assertEqual((row.owner_index,row.turn),(3,5));self.portable(g)

    def test_draw_ritual_discounts_only_two_original_draw_arrivals_and_real_payment(self):
        g=self.game(hand=(DRAW,));self.play(g,DRAW);self.assertEqual(g.state.players[1].mana,7)
        self.end(g,4);hand=g.state.players[1].hand
        self.assertEqual([g.state.entities[i].card_id for i in hand],[HIGH,MID,EXP,LOW])
        self.assertEqual([local_cost(g.state.entities[i])[0]for i in hand],[5,1,5,1])
        self.play(g,MID);self.assertEqual(g.state.players[1].mana,9);self.portable(g)

    def test_missing_draws_use_ordinary_fatigue_and_still_complete_once(self):
        g=self.game(hand=(DRAW,),deck=());self.play(g,DRAW);self.end(g,4)
        self.assertEqual(len(completed_rituals(g.state,1)),1);self.assertEqual(len(g.state.players[1].hand),0)
        self.assertEqual(g.state.players[1].fatigue,4);self.portable(g)

    def test_full_hand_burns_real_draws_without_discounting_unrelated_hand_cards(self):
        g=self.game(hand=(DRAW,)+(HIGH,)*9);self.play(g,DRAW);self.end(g,4)
        self.assertEqual(len(g.state.players[1].hand),10)
        self.assertTrue(all(local_cost(g.state.entities[i])[0]in(5,1)for i in g.state.players[1].hand))
        self.assertEqual(len(completed_rituals(g.state,1)),1);self.portable(g)

    def test_both_rituals_finish_independently_in_original_installation_order(self):
        g=self.game(hand=(DRAW,SUMMON));draw=self.play(g,DRAW);summon=self.play(g,SUMMON);self.end(g,4)
        rows=completed_rituals(g.state,1);self.assertEqual([r.instance.source_id for r in rows],[draw,summon])
        self.assertEqual([r.id for r in rows],[1,2]);self.assertEqual(len(self.tokens(g)),2);self.portable(g)

    def test_duplicate_ritual_cards_have_distinct_instances_and_completions(self):
        g=self.game(hand=(SUMMON,SUMMON));self.play(g);self.play(g);self.end(g,4)
        rows=completed_rituals(g.state,1);self.assertEqual(len({r.instance.id for r in rows}),2)
        self.assertEqual(len(self.tokens(g)),4);self.portable(g)

    def test_quantity_extras_use_normal_summon_requests_without_repeating_completion(self):
        g=self.game(board=(DOUBLE,));self.play(g);self.end(g,4)
        self.assertEqual(len(self.tokens(g)),4);self.assertEqual(len(completed_rituals(g.state,1)),1);self.portable(g)

    def test_full_board_still_records_real_completion_with_no_delivered_minions(self):
        g=self.game(board=(HIGH,)*7);self.play(g);self.end(g,4)
        self.assertFalse(self.tokens(g));self.assertEqual(len(completed_rituals(g.state,1)),1);self.portable(g)

    def test_partial_board_capacity_keeps_one_original_actual_delivery(self):
        g=self.game(board=(HIGH,)*6);self.play(g);self.end(g,4)
        self.assertEqual(len(self.tokens(g)),1);self.assertEqual(len(completed_rituals(g.state,1)),1);self.portable(g)

    def test_ordinary_removal_cancels_ritual_without_creating_completion(self):
        g=self.game(hand=(SUMMON,CANCEL));self.play(g);self.play(g,CANCEL);self.end(g,4)
        self.assertFalse(self.effects(g));self.assertEqual(completed_rituals(g.state,1),());self.assertFalse(self.tokens(g));self.portable(g)

    def test_nonritual_sigil_expiry_is_not_a_completed_ritual(self):
        g=self.game(hand=(OTHER,));self.play(g,OTHER);self.end(g,4)
        self.assertEqual(completed_rituals(g.state,1),());self.portable(g)

    def test_completion_is_visible_before_expiry_observer_and_payload_wait_restores(self):
        g=self.game('wait');self.play(g);self.end(g,4)
        self.assertEqual(len(completed_rituals(g.state,1)),1);self.assertFalse(self.effects(g));self.assertFalse(self.tokens(g))
        other=self.portable(g);self.choose(g);self.choose(other);self.assertTrue(g.snapshot()==other.snapshot())
        self.assertEqual(len(self.tokens(g)),2);self.portable(g)

    def test_cancel_later_same_start_instance_from_first_expiry_wait_has_no_phantom_completion(self):
        g=self.game('wait',hand=(SUMMON,SUMMON));self.play(g);self.play(g);self.end(g,4)
        self.choose(g,'cancel');self.assertIsNone(g.state.pending_choice)
        self.assertEqual(len(self.tokens(g)),2);self.assertEqual(len(completed_rituals(g.state,1)),1);self.portable(g)

    def test_minion_entry_wait_preserves_completed_instance_and_owed_second_request(self):
        g=self.game('wait_summon');self.play(g);self.end(g,4)
        self.assertEqual(len(self.tokens(g)),1);self.assertEqual(len(completed_rituals(g.state,1)),1)
        other=self.portable(g);self.choose(g);self.choose(other);self.assertTrue(g.snapshot()==other.snapshot())
        self.choose(g);self.assertEqual(len(self.tokens(g)),2);self.portable(g)

    def test_expiry_failure_rolls_back_turn_handoff_tick_fact_cursor_and_payload(self):
        g=self.game('fail');self.play(g);self.end(g,3);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.end(g)
        self.assertTrue(g.snapshot()==before);self.assertEqual(self.effects(g)[0].remaining_turns,1)
        self.assertEqual(completed_rituals(g.state,1),())

    def test_failed_expiry_selection_keeps_original_completion_and_wait_without_repeat(self):
        g=self.game('wait');self.play(g);self.end(g,4);before=g.snapshot()
        with self.assertRaises(ResolutionError):self.choose(g,'fail')
        self.assertTrue(g.snapshot()==before);self.choose(g)
        self.assertEqual(len(completed_rituals(g.state,1)),1);self.assertEqual(len(self.tokens(g)),2);self.portable(g)

    def test_completed_history_survives_later_turns_and_is_separated_by_player(self):
        g=self.game(seat=2);self.play(g);self.end(g,6)
        self.assertEqual(completed_rituals(g.state,1),());self.assertEqual(len(completed_rituals(g.state,2)),1);self.portable(g)

    def test_completed_query_is_pure_and_records_are_immutable_strict_values(self):
        g=self.game();self.play(g);self.end(g,4);before=g.snapshot();row,=completed_rituals(g.state,1)
        with self.assertRaises(FrozenInstanceError):row.id=9
        for key,value in(('owner_index',True),('event_sequence',0),('id',True)):
            with self.assertRaises(ValueError):replace(row,**{key:value})
        for pid in(0,3,True):
            with self.assertRaises(ValueError):completed_rituals(g.state,pid)
        self.assertTrue(g.snapshot()==before)

    def test_rehashed_missing_changed_and_duplicate_completion_facts_are_rejected(self):
        g=self.game();self.play(g);self.end(g,4)
        for edit in(lambda s:s['state']['ritual_completions'].clear(),
                lambda s:s['state']['ritual_completions'][0].update(owner_index=999),
                lambda s:s['state']['ritual_completions'].append(deepcopy(s['state']['ritual_completions'][0]))):
            self.reject(g,edit)

    def test_rehashed_missing_private_expiry_proof_or_foreign_original_instance_rejects(self):
        g=self.game('wait');self.play(g);self.end(g,4)
        self.reject(g,lambda s:next(e for e in s['events']if e['kind']=='player_effect_expired')['data'].pop(KEY))
        self.reject(g,lambda s:s['state']['ritual_completions'][0]['instance'].update(id=9999))

    def test_old_schema_and_unknown_ritual_clock_cannot_be_silently_upgraded(self):
        g=self.game();s=g.snapshot();s['schema_version']=520
        with self.assertRaises(SnapshotError):Game.from_snapshot(s,fixture())
        spec=fixture().player_effect(PROGRAM+SUMMON)
        for kwargs in(dict(duration=1),dict(tick_event='turn_ended'),dict(tick_player='opponent'),dict(on_expire=None)):
            with self.assertRaises(ValueError):replace(spec,**kwargs)

    def test_shared_objective_area_rejects_sixth_ritual_before_payment(self):
        g=self.game(hand=(SUMMON,)*6+(REFRESH,))
        for _ in range(5):self.play(g)
        self.play(g,REFRESH);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.play(g)
        self.assertTrue(g.snapshot()==before);self.assertEqual(len(self.effects(g)),5)

    def test_public_timer_and_expiry_keep_private_original_completion_out_of_player_dtos(self):
        g=self.game('wait',seat=2);self.play(g);self.end(g,4);before=g.snapshot()
        for pid in(1,2):
            text=json.dumps(g.for_player(pid).observe());g.for_player(pid).legal_actions()
            for key in(KEY,'ritual_completions','next_ritual_completion_id','owner_index','event_sequence'):
                self.assertNotIn('"'+key+'"',text)
        self.assertTrue(g.snapshot()==before);self.choose(g);self.portable(g)
