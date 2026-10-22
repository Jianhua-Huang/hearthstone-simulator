"""Real original-deck entrance; scoped host clock and affected continuations."""
from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace
import unittest

from hs_sim.cards.nozdormu_turn_clock_card import CARD, load_batch, register_nozdormu_turn_clock_card
from hs_sim.engine import (CardDefinition, CardType, DeckPolicy, DeckSpec, EndTurn, Game,
    IllegalAction, Keyword, MatchSetup, PlayCard, PlayerSetup, RewindSpec, Scenario,
    SelectChoice, SnapshotError, TriggerSpec, ResolutionError)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import ChoiceOption, Damage, GainArmor, RequestChoice, Summon
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.turn_clocks import (AdvanceTurnTime, INSTALL, ADVANCE, TIMEOUT,
    current, history_action_from_dict, history_action_to_dict)
from hs_sim.engine.turn_scheduling import QueueTurns
from opening_fixtures import registry as opening_registry, metadata

ASK = 'clock-test.ask'
WATCH = 'clock-test.watch'


def fixture(mode='normal'):
    r = opening_registry()
    register_nozdormu_turn_clock_card(r)
    def ask(player, source):
        after = (RequestChoice(3-player, (ChoiceOption('other','Other',(GainArmor(3-player,2),)),),source_id=source),) if mode=='handoff' else ()
        if mode == 'nested':
            after = (RequestChoice(player,(ChoiceOption('inner','Inner',(GainArmor(player,3),)),),source_id=source),)
        return (RequestChoice(player,(ChoiceOption('a','A',(GainArmor(player,1),)+after),
            ChoiceOption('b','B',(GainArmor(player,2),)+after)),source_id=source),)
    # Hero IDs are resolved from the real context; no live game state is captured.
    def body(c):
        if mode == 'extra': return (QueueTurns((c.player_id,),c.source_id),)
        if mode == 'watch': return (Summon(c.player_id,WATCH,c.source_id),)
        if mode == 'rewind': return (GainArmor(c.player_id,c.rewind_attempt+1),)
        if mode == 'lethal':
            hit = Damage(c.state.players[3-c.player_id].hero_id,100,c.source_id)
            return (RequestChoice(c.player_id,(ChoiceOption('a','A',(hit,)),ChoiceOption('b','B',(hit,))),source_id=c.source_id),)
        if mode == 'broken':
            return (RequestChoice(c.player_id,(ChoiceOption('bad','Bad',(GainArmor(c.player_id,1),)),),
                source_id=c.source_id,on_select='clock-test.fail'),)
        return ask(c.player_id,c.source_id)
    r.register_behavior(ASK,body)
    def fail(c): raise RuntimeError('Explicit timeout callback failure')
    r.register_behavior('clock-test.fail',fail)
    kw = dict(keywords=(Keyword.REWIND,),rewind=RewindSpec(2)) if mode=='rewind' else {}
    r.register_card(CardDefinition(ASK,'Explicit clock decision',CardType.SPELL,on_play=ASK,metadata=metadata(),**kw))
    r.register_behavior(WATCH,lambda c: (RequestChoice(c.player_id,(ChoiceOption('end','End',(GainArmor(c.player_id,1),)),),source_id=c.source_id),)
                        if c.event.player_id==c.player_id else ())
    r.register_card(CardDefinition(WATCH,'Explicit end observer',CardType.MINION,health=3,
        triggers=(TriggerSpec('turn_ended',WATCH),)))
    r.validate()
    return r


class NozdormuTurnClockTests(unittest.TestCase):
    def test_source_absent_frozen_projection_needs_no_synthetic_event_host(self):
        from hs_sim.engine.turn_clocks import installation
        g = self.game(both=False)
        probe = SimpleNamespace(_state=g.state, registry=g.registry)
        self.assertIsNone(installation(probe))
        self.assertIsNone(current(probe))

    def test_eligible_frozen_projection_requires_and_preserves_real_clock_events(self):
        from hs_sim.engine.turn_clocks import installation
        g = self.game()
        probe = SimpleNamespace(_state=g.state, registry=g.registry)
        with self.assertRaisesRegex(ValueError, 'original event receipts'): installation(probe)
        self.tick(g, 1234)
        probe = SimpleNamespace(_state=g.state, registry=g.registry, _events=tuple(g._events))
        self.assertEqual(current(probe), current(g))
        self.assertEqual(current(probe)['elapsed_ms'], 1234)

    def game(self, *, mode='normal', both=True, first=1, opening=False, duplicate=False, seed=71):
        r=fixture(mode)
        own=(CARD,)+(ASK,)*7
        other=((CARD,)+(ASK,)*7) if both else (ASK,)*8
        if duplicate: own=(CARD,CARD)+(ASK,)*6
        from hs_sim.engine.model import CardClass
        decks=tuple(DeckSpec('mage.hero','mage.power',CardClass.MAGE,cards) for cards in (own,other))
        policy=DeckPolicy('clock-experiment-v1','explicit-clock-target','experimental',tuple(r.cards),
            deck_size=8,max_copies=8,legendary_copies=2 if duplicate else 1)
        g=Game.from_decks(MatchSetup(decks,policy,'coin',seed,first),r)
        if not opening:
            while g.state.pending_choice is not None:
                c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,()))
        return g

    def play(self,g):
        p=g.state.active_player
        eid=next(e for e in g.state.players[p].hand if g.state.entities[e].card_id==ASK)
        g.apply(PlayCard(p,eid))
        return eid

    def tick(self,g,ms):
        g.apply(AdvanceTurnTime(current(g)['owner_turn_id'],ms))

    def check(self,g):
        saved=json.loads(json.dumps(g.snapshot()))
        self.assertEqual(g.clone().snapshot(),saved)
        # Fresh independent registry, not a mutable runtime cache from this match.
        mode=getattr(self,'mode','normal')
        self.assertEqual(Game.from_snapshot(saved,fixture(mode)).snapshot(),saved)
        self.assertEqual(replay(build_replay(g),fixture(mode)).snapshot(),saved)

    def reject(self,snapshot,*,mode='normal'):
        snapshot['events_hash']=canonical_hash(snapshot['events'])
        if 'turn_clock' in snapshot:
            snapshot['turn_clock']['events']=[deepcopy(e)for e in snapshot['events'] if e['kind'] in (INSTALL,ADVANCE,TIMEOUT)]
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items()
            if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError)as caught:Game.from_snapshot(snapshot,fixture(mode))
        self.assertNotIn('digest mismatch',str(caught.exception))

    def test_complete_core_face_and_profile_are_pinned(self):
        item=load_batch()['cards'][0];r=fixture();card=r.card(CARD)
        self.assertEqual((card.cost,card.attack,card.health),(7,8,8))
        self.assertEqual(json.loads(json.dumps(asdict(card.metadata))),item['metadata'])
        self.assertEqual(r._turn_clock_profiles[CARD].limit_ms,15000)
        self.assertFalse(load_batch()['cn_calibrated'])

    def test_only_both_original_decks_install_once_before_deal(self):
        for first in (1,2):
            g=self.game(first=first,opening=True,duplicate=True)
            self.assertEqual(sum(e.kind==INSTALL for e in g.events),1)
            self.assertIsNone(current(g))
            self.assertNotIn('turn_clock',g.observe(1))
            while g.state.pending_choice is not None:
                c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,()))
            self.assertEqual(current(g)['remaining_ms'],15000)
            self.assertEqual(current(g)['player_id'],first)
            self.check(g)

    def test_one_deck_and_scenario_do_not_forge_starting_facts(self):
        g=self.game(both=False)
        self.assertIsNone(current(g));self.assertNotIn('turn_clock',g.snapshot())
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(AdvanceTurnTime(1,15000))
        self.assertEqual(g.snapshot(),before)
        r=fixture();s=Game.from_scenario(Scenario((PlayerSetup('mage.hero',deck=(CARD,)),
            PlayerSetup('mage.hero',deck=(CARD,)))),r)
        self.assertIsNone(current(s));self.assertNotIn('turn_clock',s.observe(1))

    def test_partial_time_is_hashed_replayable_and_does_not_consume_rng_or_action(self):
        g=self.game();before=g.snapshot();self.tick(g,7000)
        self.assertEqual(current(g)['remaining_ms'],8000)
        self.assertNotEqual(g.state_hash(),before['state_hash'])
        self.assertEqual(g.snapshot()['rng_state'],before['rng_state'])
        self.assertEqual(g.state.action_number,before['state']['action_number'])
        self.assertEqual(g.history[-1]['action']['type'],'advance_turn_time')
        self.check(g)

    def test_exact_expiry_ends_once_and_resets_next_turn_without_overflow(self):
        g=self.game();token=current(g)['owner_turn_id'];self.tick(g,14999)
        self.assertEqual(g.state.turn,1);self.tick(g,90000)
        self.assertEqual((g.state.turn,g.state.active_player),(2,2))
        self.assertEqual(current(g)['remaining_ms'],15000)
        self.assertEqual(sum(e.kind=='turn_ended'for e in g.events),1)
        before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(AdvanceTurnTime(token,1))
        self.assertEqual(g.snapshot(),before);self.check(g)

    def test_manual_end_discards_only_old_interval_time(self):
        g=self.game();self.tick(g,12000);g.apply(EndTurn(1))
        self.assertEqual(current(g)['elapsed_ms'],0)
        self.tick(g,1000);self.assertEqual(current(g)['remaining_ms'],14000)
        self.check(g)

    def test_partial_time_during_paid_choice_keeps_manual_choice_boundary(self):
        g=self.game();self.play(g);choice=g.state.pending_choice
        before=g.snapshot()['resolution_frame'];self.tick(g,4000)
        self.assertEqual(g.snapshot()['resolution_frame'],before)
        self.check(g)
        g.apply(SelectChoice(choice.player_id,choice.id,('a',)))
        self.assertEqual((g.state.turn,len(g.state.play_history),len(g.state.cast_history)),(1,1,1))
        self.assertTrue(g.state.play_history[0].completed)
        self.assertEqual(current(g)['remaining_ms'],11000);self.check(g)

    def test_timeout_resumes_real_paid_choice_then_natural_end_without_repayment(self):
        g=self.game();self.play(g);self.check(g);self.tick(g,15000)
        self.assertEqual(g.state.turn,2);self.assertIsNone(g.state.pending_choice)
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1))
        self.assertTrue(g.state.play_history[0].completed)
        self.assertEqual(sum(e.kind==TIMEOUT for e in g.events),1)
        self.assertEqual(sum(e.kind=='choice_selected'for e in g.events),3)
        self.check(g)

    def test_each_new_active_owner_choice_in_expired_work_is_resumed(self):
        self.mode='nested';g=self.game(mode=self.mode);self.play(g);self.tick(g,15000)
        self.assertEqual(g.state.turn,2);self.assertEqual(sum(e.kind==TIMEOUT for e in g.events),2)
        self.assertIsNone(g.state.pending_choice);self.check(g)

    def test_opponent_pending_choice_pauses_and_cannot_be_charged(self):
        self.mode='handoff';g=self.game(mode=self.mode);self.play(g)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('a',)))
        self.assertEqual(g.state.pending_choice.player_id,2)
        self.assertTrue(current(g)['paused']);before=g.snapshot()
        with self.assertRaises(IllegalAction):self.tick(g,15000)
        self.assertEqual(g.snapshot(),before)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('other',)))
        self.assertEqual(current(g)['remaining_ms'],15000);self.check(g)

    def test_expired_active_work_waits_for_opponent_then_ends_original_turn(self):
        self.mode='handoff';g=self.game(mode=self.mode);self.play(g);self.tick(g,15000)
        self.assertEqual((g.state.turn,g.state.pending_choice.player_id),(1,2))
        self.assertEqual(current(g)['remaining_ms'],0);self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('other',)))
        self.assertEqual(g.state.turn,2);self.assertEqual(sum(e.kind=='turn_ended'for e in g.events),1)
        self.check(g)

    def test_natural_end_reaction_choice_is_not_timed_as_the_old_turn(self):
        self.mode='watch';g=self.game(mode=self.mode);self.play(g);self.tick(g,15000)
        self.assertEqual(g.state.pending_choice.player_id,1)
        self.assertIsNone(current(g));self.assertEqual(sum(e.kind==TIMEOUT for e in g.events),0)
        self.check(g)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('end',)))
        self.assertEqual(g.state.turn,2);self.check(g)

    def test_extra_turn_has_new_token_and_full_limit(self):
        self.mode='extra';g=self.game(mode=self.mode);self.play(g);old=current(g)['owner_turn_id'];self.tick(g,50000)
        self.assertEqual((g.state.turn,g.state.active_player),(2,1))
        self.assertEqual(current(g)['remaining_ms'],15000)
        self.assertNotEqual(current(g)['owner_turn_id'],old);self.check(g)

    def test_rewind_preserves_elapsed_time_and_timeout_resolves_bounded_retries(self):
        self.mode='rewind';g=self.game(mode=self.mode);self.play(g);self.tick(g,8000)
        c=g.state.pending_choice;g.apply(SelectChoice(c.player_id,c.id,('retry',)))
        self.assertEqual(current(g)['remaining_ms'],7000);self.check(g)
        self.tick(g,7000)
        self.assertEqual(g.state.turn,2);self.assertIsNone(g.snapshot()['rewind_session'])
        self.assertEqual((len(g.state.play_history),len(g.state.cast_history)),(1,1));self.check(g)

    def test_lethal_from_timeout_choice_does_not_start_another_turn(self):
        self.mode='lethal';g=self.game(mode=self.mode);self.play(g);self.tick(g,15000)
        self.assertEqual((g.state.status,g.state.winner,g.state.turn),('finished',1,1))
        self.assertIsNone(current(g));self.assertEqual(sum(e.kind=='turn_ended'for e in g.events),0)
        self.check(g)

    def test_failed_timeout_rolls_back_time_rng_choice_and_history(self):
        self.mode='broken';g=self.game(mode=self.mode);self.play(g);before=g.snapshot();history=g.history
        with self.assertRaises(ResolutionError):self.tick(g,15000)
        self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)

    def test_host_codec_is_strict_and_never_a_player_action(self):
        action=AdvanceTurnTime(1,100);wire=history_action_to_dict(action)
        self.assertEqual(history_action_from_dict(wire),action)
        for bad in (dict(wire,version=True),dict(wire,owner_turn_id=True),dict(wire,elapsed_ms=0),dict(wire,extra=1)):
            with self.assertRaises(ValueError):history_action_from_dict(bad)
        with self.assertRaises(ValueError):action_from_dict(wire)
        with self.assertRaises(ValueError):action_to_dict(action)
        for token,ms in ((True,1),(1,True),(1,0),(0,1),(1,-1)):
            with self.assertRaises(ValueError):AdvanceTurnTime(token,ms)

    def test_player_view_exposes_only_public_time_and_rejects_host_command(self):
        g=self.game();self.play(g);self.tick(g,4000)
        for viewer in (1,2):
            port=g.for_player(viewer);obs=port.observe();clock=obs['observation']['turn_clock']
            self.assertEqual(clock['remaining_ms'],11000)
            self.assertNotIn('owner_turn_id',clock)
            public=json.dumps((obs,port.events()),ensure_ascii=False)
            for word in ('rng_before','rng_after','turn_time_advanced','turn_clock_installed','original_deck'):
                self.assertNotIn(word,public)
            before=g.snapshot()
            result=port.submit(dict(revision=obs['revision'],action=history_action_to_dict(AdvanceTurnTime(1,15000))))
            self.assertFalse(result['accepted']);self.assertEqual(g.snapshot(),before)

    def test_rehashed_clock_changes_missing_commitment_and_lost_original_install_reject(self):
        g=self.game();self.tick(g,6000);snapshot=g.snapshot()
        charge=next(i for i,e in enumerate(snapshot['events'])if e['kind']==ADVANCE)
        for field,value in (('previous_ms',1),('owner_turn_id',2),('elapsed_ms',5000)):
            bad=deepcopy(snapshot);bad['events'][charge]['data'][field]=value;self.reject(bad)
        bad=deepcopy(snapshot);del bad['turn_clock'];self.reject(bad)
        bad=deepcopy(snapshot);event=next(e for e in bad['events']if e['kind']==INSTALL);event['amount']=15001;self.reject(bad)

    def test_rehashed_timeout_options_rng_or_selected_answer_reject(self):
        g=self.game();self.play(g);self.tick(g,15000);snapshot=g.snapshot()
        index=next(i for i,e in enumerate(snapshot['events'])if e['kind']==TIMEOUT)
        for field,value in (('options',['a']),('selected',[]),('choice_id',999)):
            bad=deepcopy(snapshot);proof=json.loads(bad['events'][index]['data']['proof']);proof[field]=value
            bad['events'][index]['data']['proof']=json.dumps(proof);self.reject(bad)

    def test_actual_minion_body_uses_normal_hand_payment_and_summon(self):
        r=fixture();g=Game.from_scenario(Scenario((PlayerSetup('mage.hero',hand=(CARD,),mana=7,max_mana=7),
            PlayerSetup('mage.hero'))),r)
        source=g.state.players[1].hand[0];g.apply(PlayCard(1,source))
        body=g.state.entities[source]
        self.assertEqual((body.attack,body.health,g.state.players[1].mana),(8,8,0))
        self.assertIn(source,g.state.players[1].board);self.assertIsNone(current(g))


if __name__=='__main__':unittest.main()
