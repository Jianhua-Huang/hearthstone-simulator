"""Public grants, complete-policy alternatives and seat-local capabilities."""
from copy import deepcopy
from dataclasses import replace
import json,unittest
from unittest.mock import patch
import examples.multiple_body_target_policies as f
from hs_sim.engine import BodyReference,Game,PlayCard
from hs_sim.engine.body_grant_authority import authorize_grant
from hs_sim.engine.body_player_commands import complete_profiles,current_bodies,identity
from hs_sim.engine.body_target_authority import matching_body_target_authorities,body_target_authorities
from hs_sim.engine.body_targets import body_target_declarations
from hs_sim.engine.errors import IllegalAction,ResolutionError,SnapshotError
from hs_sim.engine.model import AbilityInstance,Zone
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


class MultipleBodyTargetPolicyTests(unittest.TestCase):
    def game(self,mode='normal',reverse=False,setup=True,**kwargs):
        game=Game.from_scenario(f.scenario(**kwargs),f.registry(mode,reverse))
        if setup:self.spell(game,'setup')
        return game

    def spell(self,game,name):
        result=game.for_player(1).submit(f.spell_command(game,name));self.assertTrue(result['accepted'],result)

    def source(self,game,name='unit'):
        return next(e for e in game.state.entities.values() if e.card_id==name and e.zone==Zone.HAND)

    def roundtrip(self,game,mode='normal',reverse=False):
        snapshot=game.snapshot();views=[game.for_player(p).observe() for p in (1,2)]
        for other in (Game.from_snapshot(snapshot,f.registry(mode,reverse)),game.clone(),replay(build_replay(game),f.registry(mode,reverse))):
            self.assertEqual(other.snapshot(),snapshot)
            self.assertEqual([other.for_player(p).observe() for p in (1,2)],views)

    def test_complete_alternative_survives_earlier_and_later_partial_policy(self):
        for reverse in (False,True):
            with self.subTest(reverse=reverse):
                game=self.game(reverse=reverse);source=self.source(game);before=game.snapshot()
                profiles=complete_profiles(game,source)
                self.assertEqual([p for p,_ in profiles],[f.profiles(reverse)[0]])
                self.assertEqual(len(profiles[0][1]),3)
                options=game.for_player(1).independent_targets(f.ref(game,'unit'),position=0)
                self.assertIsNone(options['error']);self.assertEqual(len(options['choices']),1)
                self.assertEqual(len(options['choices'][0]['bodies']),3)
                legal=game.for_player(1).legal_actions();self.assertIsNone(legal['error'])
                self.assertTrue(any(a.get('body_targets') for a in legal['actions']))
                self.assertEqual(game.snapshot(),before)

    def test_matching_and_prospective_grant_are_pure_without_candidates_quote_or_rng(self):
        game=self.game(setup=False);source=self.source(game);before=game.snapshot();rng=game._rng.getstate()
        ability=AbilityInstance(game.state.next_attachment_id,'battlecry',behavior_id='body',source_id=source.id,battlecry_card_id='enemy_body')
        with (patch('hs_sim.engine.targeting.target_choices',side_effect=AssertionError('candidate query')),
              patch('hs_sim.engine.costs.quote_cost',side_effect=AssertionError('quote'))):
            self.assertEqual([p for p,_ in complete_profiles(game,source)],['paid_z'])
            self.assertEqual(len(current_bodies(game,1)),1)
            self.assertEqual(authorize_grant(game._state,game.registry,game._state.entities[source.id],ability),'paid_z')
            self.assertIsNone(matching_body_target_authorities(game._state,game.registry,BodyReference.capture(source),'paid_a'))
        self.assertEqual(game.snapshot(),before);self.assertEqual(game._rng.getstate(),rng)

    def test_real_complete_json_executes_each_original_target_and_pays_once(self):
        game=self.game();command=f.paid_command(game);self.assertTrue(game.for_player(1).submit(command)['accepted'])
        record=game.state.play_history[-1];receipt=record.body_targets
        self.assertEqual(receipt.action.body_target_profile_id,'paid_z');self.assertEqual(len(receipt.selected),3)
        self.assertEqual(game.state.players[1].mana,8)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,3)
        self.assertEqual([r.target_id for r in (*game.state.battlecry_history,*game.state.combo_history)],
            [r.target_id for r in receipt.selected])
        self.assertEqual(game.state.entities[game.state.players[2].board[0]].damage,2)
        self.roundtrip(game)

    def test_all_partial_policies_report_explicit_error_and_allocate_no_body_handles(self):
        game=self.game('missing',setup=False);before=game.snapshot()
        self.assertFalse(current_bodies(game,1));self.assertFalse(game._information.players[1].body_refs)
        result=game.for_player(1).independent_targets(f.ref(game,'unit'),position=0)
        self.assertIsNone(result['choices']);self.assertEqual(result['error'],'unsupported_body_target_policy')
        legal=game.for_player(1).legal_actions();self.assertIsNone(legal['actions'])
        self.assertEqual(legal['error'],'unsupported_body_target_policy');self.assertEqual(game.snapshot(),before)

    def test_physical_carrier_scope_gaps_are_partial_without_borrowed_authority(self):
        for mode in ('scope_kind','scope_card'):
            with self.subTest(mode=mode):
                game=self.game(mode,setup=False);source=self.source(game);before=game.snapshot()
                self.assertIsNone(matching_body_target_authorities(game._state,game.registry,BodyReference.capture(source),'paid_z'))
                with self.assertRaises(IllegalAction):body_target_authorities(game._state,game.registry,BodyReference.capture(source),'paid_z')
                result=game.for_player(1).independent_targets(f.ref(game,'unit'),position=0)
                self.assertEqual(result['error'],'unsupported_body_target_policy');self.assertEqual(game.snapshot(),before)

    def test_complete_custom_root_still_errors_while_body_storage_remains_legal(self):
        game=self.game('custom_complete');before=game.snapshot()
        self.assertEqual(len(current_bodies(game,1)),3)
        result=game.for_player(1).independent_targets(f.ref(game,'unit'),position=0)
        self.assertEqual(result['error'],'unsupported_rule')
        self.assertEqual(game.for_player(1).legal_actions()['error'],'unsupported_rule');self.assertEqual(game.snapshot(),before)

    def test_partial_policies_cannot_union_their_bindings_to_authorize_a_grant(self):
        game=self.game('split',setup=False);before=game.snapshot()
        result=game.for_player(1).submit(f.spell_command(game,'setup'))
        self.assertFalse(result['accepted']);self.assertEqual(result['error'],'resolution_failed')
        self.assertEqual(game.snapshot(),before)

    def test_actual_remove_and_new_grant_switch_policy_and_retire_old_handles(self):
        game=self.game('switch',setup=False,switch=True);self.spell(game,'grant_a')
        old=f.paid_command(game,'empty');old_handles={b['body'] for b in old['action']['body_targets']}
        self.spell(game,'remove');self.assertFalse(current_bodies(game,1))
        self.spell(game,'grant_b');fresh=f.paid_command(game,'empty')
        self.assertTrue(old_handles.isdisjoint(b['body'] for b in fresh['action']['body_targets']))
        old['revision']=fresh['revision'];before=game.snapshot()
        self.assertFalse(game.for_player(1).submit(old)['accepted']);self.assertEqual(game.snapshot(),before)
        self.assertTrue(game.for_player(1).submit(fresh)['accepted'])
        self.assertEqual(game.state.play_history[-1].body_targets.action.body_target_profile_id,'paid_a')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor,1)
        self.roundtrip(game,'switch')

    def test_current_copy_keeps_complete_authority_with_new_unborrowable_handles(self):
        game=self.game(copy=True);old=f.paid_command(game);self.spell(game,'copy')
        fresh=f.paid_command(game,index=1)
        self.assertTrue({b['body'] for b in old['action']['body_targets']}.isdisjoint(b['body'] for b in fresh['action']['body_targets']))
        old['revision']=fresh['revision'];old['action']['card']=fresh['action']['card'];before=game.snapshot()
        self.assertFalse(game.for_player(1).submit(old)['accepted']);self.assertEqual(game.snapshot(),before)
        self.assertTrue(game.for_player(1).submit(fresh)['accepted']);self.roundtrip(game)

    def test_actual_waiting_restores_clones_replays_and_resumes_same_policy(self):
        game=self.game('wait');self.assertTrue(game.for_player(1).submit(f.paid_command(game))['accepted'])
        self.assertIsNotNone(game.state.pending_choice);self.roundtrip(game,'wait')
        legal=game.for_player(1).legal_actions();self.assertIsNone(legal['error'])
        self.assertTrue(game.for_player(1).submit({'revision':legal['revision'],'action':legal['actions'][0]})['accepted'])
        self.assertIsNone(game.state.pending_choice);self.roundtrip(game,'wait')

    def test_runtime_failure_rolls_back_payment_rng_histories_and_private_ledger(self):
        game=self.game('fail');before=game.snapshot();command=f.paid_command(game)
        response=game.for_player(1).submit(command)
        self.assertFalse(response['accepted']);self.assertEqual(response['error'],'resolution_failed')
        self.assertEqual(game.snapshot(),before)

    def test_rehashed_partial_policy_handle_injection_is_rejected(self):
        game=self.game();original=game.snapshot();source=self.source(game)
        declaration=body_target_declarations(game._state,game.registry,BodyReference.capture(source),'paid_a')[0]
        forged=deepcopy(original);ledger=forged['information']['players']['1']
        ledger['body_refs'][identity('paid_a',declaration.reference)]='b1_'+str(ledger['next_body_ref']);ledger['next_body_ref']+=1
        forged['state_hash']=canonical_hash({k:v for k,v in forged.items() if k not in ('schema_version','events','events_hash','state_hash')})
        with self.assertRaisesRegex(SnapshotError,'Private body capabilities'):Game.from_snapshot(forged,f.registry())
        self.assertEqual(game.snapshot(),original)

    def test_unknown_or_malformed_declarations_are_not_classified_as_partial(self):
        game=self.game(setup=False);source=self.source(game);before=game.snapshot()
        with patch('hs_sim.engine.targeting.target_choices',side_effect=AssertionError('candidate')):
            with self.assertRaises(ValueError):matching_body_target_authorities(game._state,game.registry,BodyReference.capture(source),'unknown')
            entity=game.state.entities[source.id]
            slot=next(i for i,a in enumerate(entity.abilities) if a.kind=='battlecry')
            wrong=replace(entity.abilities[slot],behavior_id='unsupported.callback')
            detached=game.state;detached.entities[source.id].abilities[slot]=wrong
            with self.assertRaises(ValueError):matching_body_target_authorities(detached,game.registry,BodyReference.capture(entity),'paid_z')
        self.assertEqual(game.snapshot(),before)

    def test_enemy_hidden_cards_do_not_change_options_commands_or_filtered_views(self):
        a=self.game(enemy_card='hidden');b=self.game(enemy_card='enemy')
        self.assertEqual(a.for_player(1).observe(),b.for_player(1).observe())
        self.assertEqual(a.for_player(1).independent_targets(f.ref(a,'unit'),position=0),b.for_player(1).independent_targets(f.ref(b,'unit'),position=0))
        self.assertEqual(f.paid_command(a),f.paid_command(b))
        rendered=json.dumps(a.for_player(1).independent_targets(f.ref(a,'unit')))
        for forbidden in ('paid_a','paid_z','profile_id','ability_id','behavior_id','grant_source_id','zone_epoch','original_state_hash'):
            self.assertNotIn(forbidden,rendered)

    def test_partial_handles_cannot_be_mixed_into_an_actual_complete_command(self):
        game=self.game();source=self.source(game);command=f.paid_command(game);before=game.snapshot()
        partial=body_target_declarations(game._state,game.registry,BodyReference.capture(source),'paid_a')
        self.assertTrue(all(identity('paid_a',d.reference) not in game._information.players[1].body_refs for d in partial))
        for mutate in (lambda a:a['body_targets'][0].update(body='b2_1'),
                       lambda a:a['body_targets'].pop(),
                       lambda a:a.update(body_target_profile_id='paid_a')):
            bad=deepcopy(command);mutate(bad['action'])
            self.assertFalse(game.for_player(1).submit(bad)['accepted']);self.assertEqual(game.snapshot(),before)


if __name__=='__main__':unittest.main()
