"""Actual empty root selection, payment, lifecycle and persisted authority."""
from copy import deepcopy
import json,unittest
import examples.empty_body_routes as f
from hs_sim.engine import Game,PlayCard
from hs_sim.engine.body_player_commands import current_bodies,current_empty_roots
from hs_sim.engine.errors import IllegalAction,SnapshotError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


class EmptyBodyRouteTests(unittest.TestCase):
    def game(self,mode='normal',**kwargs):return Game.from_scenario(f.scenario(**kwargs),f.registry(mode))
    def spell(self,g,name):
        result=g.for_player(1).submit(f.spell_command(g,name));self.assertTrue(result['accepted'],result)
    def roundtrip(self,g,mode='normal'):
        snapshot=g.snapshot();views=[g.for_player(p).observe() for p in (1,2)]
        for other in (Game.from_snapshot(snapshot,f.registry(mode)),g.clone(),replay(build_replay(g),f.registry(mode))):
            self.assertEqual(other.snapshot(),snapshot);self.assertEqual([other.for_player(p).observe() for p in (1,2)],views)
    def test_two_empty_policies_have_distinct_private_handles_and_pure_complete_plans(self):
        g=self.game();before=g.snapshot();query=g.for_player(1).independent_targets(f.ref(g,'unit'),position=0)
        self.assertIsNone(query['error']);self.assertEqual(len(query['choices']),2)
        self.assertTrue(all(c['bodies']==[] for c in query['choices']))
        self.assertEqual(len({c['body_route'] for c in query['choices']}),2)
        self.assertFalse(current_bodies(g,1));self.assertEqual(len(current_empty_roots(g,1)),2)
        self.assertIsNone(g.for_player(1).legal_actions()['error']);self.assertEqual(g.snapshot(),before)
        for hidden in ('profile_id','paid_a','paid_z','ability_id','zone_epoch','registry_fingerprint'):
            self.assertNotIn(hidden,json.dumps(query))
    def test_actual_empty_vector_uses_chosen_root_policy_and_pays_exactly_once(self):
        for enemy,profile in ((False,'paid_a'),(True,'paid_z')):
            with self.subTest(enemy=enemy):
                g=self.game();c=f.command(g,enemy=enemy);result=g.for_player(1).submit(c);self.assertTrue(result['accepted'],result)
                p=g.state.play_history[-1];self.assertEqual(p.body_targets.action.body_target_profile_id,profile)
                self.assertEqual(p.body_targets.selected,());self.assertEqual(p.body_targets.body_choices,())
                self.assertEqual(p.battlecries,());self.assertEqual(p.combos,())
                self.assertFalse(g.state.battlecry_history);self.assertFalse(g.state.combo_history)
                self.assertEqual(g.state.players[1].mana,8)
                target=g.state.players[2 if enemy else 1].board[0 if enemy else 1]
                self.assertEqual(g.state.entities[target].damage,2);self.roundtrip(g)
    def test_missing_route_wrong_seat_wrong_carrier_and_mixed_body_reject_atomically(self):
        g=self.game(plain=True);good=f.command(g);before=g.snapshot()
        other=f.command(g,'plain')['action']['body_route']
        for change in (lambda a:a.pop('body_route'),lambda a:a.pop('body_targets'),lambda a:a.update(body_route='b2_1'),
                       lambda a:a.update(body_route=other),lambda a:a.update(body_targets=[{'body':a['body_route'],'target':None}]),
                       lambda a:a.update(body_target_profile_id='paid_z')):
            bad=deepcopy(good);change(bad['action']);self.assertFalse(g.for_player(1).submit(bad)['accepted']);self.assertEqual(g.snapshot(),before)
    def test_real_bodyless_minion_uses_complete_empty_receipt_without_callbacks(self):
        g=self.game(plain=True);c=f.command(g,'plain');result=g.for_player(1).submit(c);self.assertTrue(result['accepted'],result)
        p=g.state.play_history[-1];self.assertIsNotNone(p.body_targets);self.assertEqual(p.body_targets.selected,())
        self.assertEqual(g.state.players[1].mana,9);self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor,0);self.roundtrip(g)
    def test_grant_retires_empty_routes_and_remove_allocates_new_routes(self):
        g=self.game(tools=('grant','remove'));old=f.command(g);handles={v['body_route'] for v in g.for_player(1).independent_targets(f.ref(g,'unit'))['choices']}
        self.spell(g,'grant');self.assertFalse(current_empty_roots(g,1));self.assertEqual(len(current_bodies(g,1)),1)
        old['revision']=g.for_player(1).observe()['revision'];before=g.snapshot();self.assertFalse(g.for_player(1).submit(old)['accepted']);self.assertEqual(g.snapshot(),before)
        self.spell(g,'remove');fresh=f.command(g)
        self.assertTrue(handles.isdisjoint(v['body_route'] for v in g.for_player(1).independent_targets(f.ref(g,'unit'))['choices']))
        self.assertTrue(g.for_player(1).submit(fresh)['accepted']);self.roundtrip(g)
    def test_consumed_original_body_is_excluded_but_preserved_in_original_origin(self):
        g=self.game(tools=('grant','consume'));self.spell(g,'grant');self.spell(g,'consume')
        self.assertFalse(current_bodies(g,1));self.assertEqual(len(current_empty_roots(g,1)),2)
        result=g.for_player(1).submit(f.command(g));self.assertTrue(result['accepted'],result)
        self.assertFalse(g.state.battlecry_history);self.assertEqual(g.state.play_history[-1].body_targets.selected,());self.roundtrip(g)
    def test_copied_carrier_cannot_borrow_original_empty_route(self):
        g=self.game(tools=('copy',));old=f.command(g);self.spell(g,'copy');fresh=f.command(g,index=1)
        self.assertNotEqual(old['action']['body_route'],fresh['action']['body_route'])
        old['revision']=fresh['revision'];old['action']['card']=fresh['action']['card'];before=g.snapshot()
        self.assertFalse(g.for_player(1).submit(old)['accepted']);self.assertEqual(g.snapshot(),before)
        self.assertTrue(g.for_player(1).submit(fresh)['accepted']);self.roundtrip(g)
    def test_hidden_move_and_draw_do_not_reuse_old_empty_route(self):
        g=self.game(tools=('hide','draw'));old=f.command(g);self.spell(g,'hide');self.assertFalse(current_empty_roots(g,1));self.spell(g,'draw')
        fresh=f.command(g);self.assertNotEqual(old['action']['body_route'],fresh['action']['body_route'])
        old['revision']=fresh['revision'];old['action']['card']=fresh['action']['card'];before=g.snapshot()
        self.assertFalse(g.for_player(1).submit(old)['accepted']);self.assertEqual(g.snapshot(),before)
        self.assertTrue(g.for_player(1).submit(fresh)['accepted']);self.roundtrip(g)
    def test_actual_root_choice_restores_clones_replays_and_resumes_empty_vector(self):
        g=self.game('wait');result=g.for_player(1).submit(f.command(g));self.assertTrue(result['accepted'],result)
        self.assertIsNotNone(g.state.pending_choice);self.roundtrip(g,'wait')
        legal=g.for_player(1).legal_actions();self.assertIsNone(legal['error'])
        self.assertTrue(g.for_player(1).submit({'revision':legal['revision'],'action':legal['actions'][0]})['accepted'])
        self.assertIsNone(g.state.pending_choice);self.roundtrip(g,'wait')
    def test_failed_root_rolls_back_rng_payment_receipt_and_private_root_ledger(self):
        g=self.game('fail');before=g.snapshot();result=g.for_player(1).submit(f.command(g))
        self.assertFalse(result['accepted']);self.assertEqual(result['error'],'resolution_failed');self.assertEqual(g.snapshot(),before)
    def test_original_empty_receipt_cannot_be_erased_after_true_snapshot_rehash(self):
        g=self.game();self.assertTrue(g.for_player(1).submit(f.command(g))['accepted']);snapshot=g.snapshot()
        forged=deepcopy(snapshot);forged['state']['play_history'][-1]['body_targets']=None
        forged['state_hash']=canonical_hash({k:v for k,v in forged.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaises(SnapshotError):Game.from_snapshot(forged,f.registry())
        self.assertEqual(g.snapshot(),snapshot)
    def test_forged_partial_root_ledger_or_wrong_counter_rejects_after_rehash(self):
        g=self.game();original=g.snapshot()
        for mutate in (lambda k:k['body_refs'].pop(next(iter(k['body_refs']))),lambda k:k.update(next_body_ref=True),
                       lambda k:k['body_refs'].update({next(iter(k['body_refs'])):'b2_1'})):
            forged=deepcopy(original);mutate(forged['information']['players']['1'])
            forged['state_hash']=canonical_hash({k:v for k,v in forged.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(forged,f.registry())
        self.assertEqual(g.snapshot(),original)
    def test_known_empty_root_is_not_legacy_blanket_hand_permission(self):
        g=self.game();entity=g.state.players[1].hand[0];before=g.snapshot()
        with self.assertRaises(IllegalAction):g.apply(PlayCard(1,entity))
        self.assertEqual(g.snapshot(),before)
    def test_no_legal_root_pool_returns_no_route_without_rng_or_payment(self):
        g=self.game(board=(),enemy_board=());before=g.snapshot();query=g.for_player(1).independent_targets(f.ref(g,'unit'),position=0)
        self.assertIsNone(query['error']);self.assertEqual(query['choices'],[])
        self.assertEqual(g.snapshot(),before);self.assertEqual(len(current_empty_roots(g,1)),2)


if __name__=='__main__':unittest.main()
