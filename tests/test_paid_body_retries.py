"""Actual public Rewind producer, origin tampering and player isolation."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from hs_sim.engine import (BodyTargetProfile,Game,IllegalAction,SelectChoice,SnapshotError)
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash
import examples.paid_body_retry as f

class PaidBodyRetryTests(unittest.TestCase):
    def game(self,mode='normal',*,grants=True,crystals=10,**kwargs):
        self.mode=mode;self.kwargs=kwargs;g=Game.from_scenario(f.scenario(grants=grants,crystals=crystals),f.registry(mode,**kwargs))
        if grants:
            response=g.for_player(1).submit({'revision':g.for_player(1).observe()['revision'],'action':{'type':'play_card','card':f.card_ref(g,'setup')}})
            self.assertTrue(response['accepted'],response)
        return g
    def play(self,g):
        response=g.for_player(1).submit(f.command(g));self.assertTrue(response['accepted'],response)
    def choose(self,g,option='retry'):
        choice=g.state.pending_choice;g.apply(SelectChoice(choice.player_id,choice.id,(option,)))
    def check(self,g):
        snapshot=g.snapshot();views=[g.for_player(p).observe() for p in (1,2)]
        for other in (Game.from_snapshot(snapshot,f.registry(self.mode,**self.kwargs)),g.clone(),replay(build_replay(g),f.registry(self.mode,**self.kwargs))):
            self.assertEqual(other.snapshot(),snapshot);self.assertEqual([other.for_player(p).observe() for p in (1,2)],views)
    def reject(self,snapshot):
        snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError) as raised:Game.from_snapshot(snapshot,f.registry(self.mode,**self.kwargs))
        self.assertNotIn('digest mismatch',str(raised.exception))
    def test_retry_policy_is_exact_and_never_grants_generated_privilege(self):
        for value in (True,'random','player',None):
            with self.assertRaises(ValueError):BodyTargetProfile('p','paid_hand','manual','pre_payment',retry_targets=value)
        with self.assertRaises(ValueError):BodyTargetProfile('p','generated_whole','random','generated_acceptance',retry_targets='reuse_original_selection')
        self.assertEqual(BodyTargetProfile('p','paid_hand','manual','pre_payment').retry_targets,'reject')
    def test_keep_preserves_original_vector_without_retry_receipt(self):
        g=self.game();self.play(g);original=g.state.play_history[-1].body_targets;self.assertIsNone(original.retry_root)
        self.check(g);self.choose(g,'keep');self.assertEqual(g.state.play_history[-1].body_targets,original);self.assertEqual(g.state.players[1].mana,8);self.check(g)
    def test_two_retries_rebase_all_six_slots_with_independent_receipts_and_one_net_payment(self):
        g=self.game();self.play(g);first=g.state.play_history[-1];rng=g.snapshot()['rng_state']
        for attempt,face in ((1,'face1'),(2,'face2')):
            self.choose(g);p=g.state.play_history[-1];receipt=p.body_targets
            self.assertEqual(p.card_id,face);self.assertEqual(receipt.retry_attempt,attempt);self.assertEqual(receipt.retry_root,first.body_targets)
            self.assertEqual([s.target_id for s in receipt.action.body_targets],[s.target_id for s in first.body_targets.action.body_targets])
            self.assertEqual([s.ability_id for s in receipt.selected],[s.ability_id for s in first.body_targets.selected])
            self.assertTrue(all(s.carrier_card_id==face for s in receipt.selected))
            self.assertEqual(json.loads(receipt.origin.source_json)['zone_epoch'],json.loads(first.body_targets.origin.source_json)['zone_epoch']+1)
            self.assertGreater(receipt.origin.action,receipt.retry_root.origin.action)
            self.assertEqual(p.submitted_cost.quote_origin,'rewind_root');self.assertEqual(g.state.players[1].mana,8)
            self.assertEqual(len(g.state.play_history),2);self.assertEqual((len(g.state.battlecry_history),len(g.state.combo_history)),(3,3))
            self.assertNotEqual(g.snapshot()['rng_state'],rng);rng=g.snapshot()['rng_state'];self.check(g)
        self.assertIsNone(g.state.pending_choice);self.assertEqual(sum(e.kind=='timeline_rewound' for e in g.events),2)
    def test_complete_zero_vector_retries_with_real_root_and_no_fabricated_bodies(self):
        g=self.game('empty',grants=False);self.play(g)
        for n in (1,2):
            self.choose(g);p=g.state.play_history[-1];self.assertEqual(p.body_targets.selected,());self.assertEqual(p.body_targets.retry_attempt,n)
            self.assertEqual((len(g.state.battlecry_history),len(g.state.combo_history)),(0,0));self.assertEqual(g.state.players[1].mana,8);self.check(g)
    def test_manathirst_and_inactive_combo_recompute_actual_original_conditions(self):
        g=self.game(crystals=6);self.play(g);self.choose(g);p=g.state.play_history[-1]
        self.assertEqual([s.target_id for s in p.body_targets.selected if s.declaration_card_id=='high'],[None,None])
        self.assertEqual(p.body_targets.body_target_active,p.body_targets.retry_root.body_target_active);self.check(g)
        g=self.game(grants=False);self.play(g);self.choose(g);p=g.state.play_history[-1]
        self.assertFalse(p.combo);self.assertIsNone(next(s for s in p.body_targets.selected if s.family=='combo').target_id);self.assertFalse(g.state.combo_history);self.check(g)
    def test_body_waiting_initial_retry_and_keep_restore_actual_fresh_proofs(self):
        g=self.game('body_wait');self.play(g);self.check(g)
        while g.state.pending_choice.purpose.value!='rewind':self.choose(g,'go')
        self.choose(g);self.assertEqual(g.state.play_history[-1].body_targets.retry_attempt,1);self.check(g)
        while g.state.pending_choice.purpose.value!='rewind':self.choose(g,'go')
        self.choose(g,'keep');self.check(g)
    def test_retry_failure_rolls_back_to_original_waiting_result_and_rng(self):
        g=self.game('fail');self.play(g);before=g.snapshot();history=g.history;response=g.for_player(1).submit(f.choose_command(g))
        self.assertFalse(response['accepted']);self.assertEqual(response['error'],'resolution_failed');self.assertEqual(g.snapshot(),before);self.assertEqual(g.history,history)
        self.choose(g,'keep');self.check(g)
    def test_missing_future_root_or_carrier_scope_refuses_initial_acceptance_atomically(self):
        for kw in ({'missing_face':True},{'restricted':True}):
            g=self.game(**kw);before=g.snapshot();command=f.command(g);response=g.for_player(1).submit(command)
            self.assertFalse(response['accepted']);self.assertEqual(g.snapshot(),before)
    def test_terminal_rehashed_retry_root_and_budget_and_event_cursor_forgery_rejected(self):
        g=self.game();self.play(g);self.choose(g);self.choose(g)
        for mutate in (lambda r:r.update(retry_root=None),lambda r:r.update(retry_attempt=1),lambda r:r.update(retry_event_start=999999),
            lambda r:r['retry_root']['action'].update(body_target_profile_id='unknown'),lambda r:r['retry_root']['body_target_active'].__setitem__(0,False)):
            s=g.snapshot();mutate(s['state']['play_history'][-1]['body_targets']);self.reject(s)
    def test_current_receipt_cannot_be_replaced_by_initial_stale_carrier_or_candidate_vector(self):
        g=self.game();self.play(g);self.choose(g);self.choose(g)
        for mutate in (lambda r:r['selected'][0].update(carrier_card_id='unit'),lambda r:r['origin'].update(action=r['retry_root']['origin']['action']),
            lambda r:r['root_choices'].clear()):
            s=g.snapshot();mutate(s['state']['play_history'][-1]['body_targets']);self.reject(s)
    def test_retry_private_handle_counter_does_not_reuse_discarded_allocations(self):
        g=self.game('wait');self.play(g);first=g.snapshot()['information']['players']['1']['next_body_ref']
        self.choose(g,'go');self.choose(g);second=g.snapshot()['information']['players']['1']['next_body_ref']
        self.assertGreater(second,first);self.check(g);self.choose(g,'go');self.choose(g);third=g.snapshot()['information']['players']['1']['next_body_ref']
        self.assertGreater(third,second);self.choose(g,'go');self.check(g)
    def test_player_observations_hide_initial_receipt_retry_anchor_and_internal_identities(self):
        g=self.game('wait');self.play(g);self.choose(g,'go');self.choose(g)
        for player in (1,2):
            raw=json.dumps(g.for_player(player).observe())+json.dumps(g.for_player(player).events())
            for hidden in ('retry_root','retry_attempt','retry_event_start','original_state_hash','zone_epoch','body_target_profile_id','grant_source_id'):
                self.assertNotIn(hidden,raw)
