"""Real paid plays: original candidates/authority, hostile saves and restoration."""
from copy import deepcopy
from dataclasses import asdict
import json
import unittest

import test_paid_body_targets_runtime as runtime_fixture
from test_paid_body_targets_runtime import registry
from hs_sim.engine import CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.effects import Summon,Silence,Transform,ChangeControl,ReturnToHand
from hs_sim.engine.errors import SnapshotError,ResolutionError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


def rehash(snapshot):
    excluded={'schema_version','events','events_hash','state_hash'}
    snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in excluded})
    return snapshot


def origin_registry(mode='normal'):
    result=registry(mode)
    def source(context):
        return next(e for e in context.state.entities.values() if e.card_id=='unit' and e.zone==Zone.BOARD)
    result.register_behavior('spawn',lambda c:[Summon(c.player_id,'friend')])
    result.register_behavior('silence',lambda c:[Silence(source(c).id)])
    result.register_behavior('transform',lambda c:[Transform(source(c).id,'friend')])
    result.register_behavior('control',lambda c:[ChangeControl(source(c).id,2)])
    result.register_behavior('return',lambda c:[ReturnToHand(source(c).id)])
    for name in ('spawn','silence','transform','control','return'):
        result.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    return result


class BodyTargetOriginTests(unittest.TestCase):
    def game(self,mode='normal',*,carrier='unit'):
        fixture=runtime_fixture.PaidBodyTargetRuntimeTests()
        game=fixture.game(mode,carrier=carrier)
        game.apply(fixture.action(game))
        return game

    def receipt(self,snapshot):
        return snapshot['state']['play_history'][-1]['body_targets']

    def reject(self,snapshot,mode='normal',carrier='unit'):
        with self.assertRaises(SnapshotError) as error:
            Game.from_snapshot(rehash(snapshot),registry(mode,carrier))
        self.assertNotIn('digest mismatch',str(error.exception).lower())
        return str(error.exception)

    def rehash_origin(self,receipt):
        receipt['origin_hash']=canonical_hash(receipt['origin'])

    def roundtrip(self,game,factory=registry):
        snapshot=game.snapshot()
        self.assertEqual(Game.from_snapshot(snapshot,factory()).snapshot(),snapshot)
        self.assertEqual(game.clone().snapshot(),snapshot)
        self.assertEqual(replay(build_replay(game),factory()).snapshot(),snapshot)
        for seat in (1,2):
            self.assertEqual(Game.from_snapshot(snapshot,factory()).for_player(seat).observe(),game.for_player(seat).observe())

    def test_original_enemy_injection_now_rejects_after_real_snapshot_rehash(self):
        snapshot=self.game().snapshot();receipt=self.receipt(snapshot)
        receipt['body_choices'][0].append(receipt['action']['target_id'])
        self.assertIn('complete original candidate',self.reject(snapshot))

    def test_omitted_and_reordered_unselected_candidates_reject(self):
        game=self.game()
        for change in ('omit','reorder'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            selected=receipt['selected'][0]['target_id']
            if change=='omit':receipt['body_choices'][0]=[selected]
            else:receipt['body_choices'][0].reverse()
            self.assertIn('complete original candidate',self.reject(snapshot))

    def test_root_candidate_and_none_policy_are_recomputed(self):
        game=self.game()
        for change in ('friendly_root','body_none','root_none'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            if change=='friendly_root':receipt['root_choices'].append(receipt['selected'][0]['target_id'])
            elif change=='body_none':receipt['body_choices'][0].append(None)
            else:receipt['root_choices'].append(None)
            self.assertIn('complete original candidate',self.reject(snapshot))

    def test_rehashed_original_facts_cannot_disagree_with_saved_candidates(self):
        game=self.game()
        for change in ('controller','zone','active','health','doomed','stealth'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            target=receipt['selected'][0]['target_id']
            fact=next(e for e in receipt['origin']['entities'] if e['id']==target)
            if change=='controller':fact['controller']=2
            elif change=='zone':fact['zone']='graveyard'
            elif change=='stealth':
                # Use the enemy root, whose selectable protection excludes it.
                fact=next(e for e in receipt['origin']['entities'] if e['id']==receipt['action']['target_id'])
                fact['keywords']=sorted(set(fact['keywords'])|{'stealth'})
            elif change=='health':fact['health']=0
            else:fact[change]=change=='doomed'
            self.rehash_origin(receipt)
            self.reject(snapshot)

    def test_complete_original_universe_includes_hidden_noncandidates(self):
        game=self.game();snapshot=game.snapshot();receipt=self.receipt(snapshot)
        hidden=game.state.players[2].hand[0]
        self.assertTrue(any(e['id']==hidden for e in receipt['origin']['entities']))
        receipt['origin']['entities']=[e for e in receipt['origin']['entities'] if e['id']!=hidden]
        self.rehash_origin(receipt)
        self.assertIn('universe',self.reject(snapshot))

    def test_original_universe_identity_order_duplicates_and_future_extent_reject(self):
        game=self.game()
        for change in ('reorder','duplicate','future'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot);origin=receipt['origin']
            if change=='reorder':origin['entities'].reverse()
            elif change=='duplicate':origin['entities'].append(deepcopy(origin['entities'][-1]))
            else:origin['next_entity_id']=snapshot['state']['next_entity_id']+1
            self.rehash_origin(receipt);self.reject(snapshot)

    def test_original_action_turn_and_attachment_ceiling_are_bound(self):
        game=self.game()
        for field in ('action','turn','next_attachment_id'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            if field=='next_attachment_id':receipt['origin'][field]=snapshot['state']['next_attachment_id']+1
            else:receipt['origin'][field]+=1
            self.rehash_origin(receipt);self.reject(snapshot)

    def test_original_source_zone_controller_epoch_and_kind_cannot_be_borrowed(self):
        game=self.game()
        for field,value in (('zone','board'),('controller',2),('zone_epoch',9),('kind','weapon')):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            source=json.loads(receipt['origin']['source_json']);source[field]=value
            receipt['origin']['source_json']=json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            self.rehash_origin(receipt);self.reject(snapshot)

    def test_original_physical_grant_expiry_consumption_and_origin_recomputed(self):
        game=self.game()
        for field,value in (('consumed',True),('source_id',None),('expires_turn',1),('origin','printed')):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            source=json.loads(receipt['origin']['source_json'])
            ability=next(a for a in source['abilities'] if a['kind']=='battlecry' and a['origin']=='granted')
            ability[field]=value
            receipt['origin']['source_json']=json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            self.rehash_origin(receipt);self.reject(snapshot)

    def test_original_complete_hand_and_outcast_position_are_bound(self):
        game=self.game()
        for change in ('remove','reorder','foreign'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot);hand=receipt['origin']['hand']
            if change=='remove':hand.pop()
            elif change=='reorder':hand.reverse()
            else:hand.append(game.state.players[2].hand[0])
            self.rehash_origin(receipt);self.reject(snapshot)

    def test_source_json_canonical_fields_and_origin_digest_are_strict(self):
        game=self.game()
        for change in ('noncanonical','unknown','digest'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            if change=='digest':receipt['origin_hash']='0'*64
            else:
                source=json.loads(receipt['origin']['source_json'])
                if change=='unknown':source['arbitrary_saved_callback']='unknown'
                receipt['origin']['source_json']=json.dumps(source,sort_keys=True,indent=1) if change=='noncanonical' else json.dumps(source,sort_keys=True,separators=(',',':'))
                self.rehash_origin(receipt)
            self.reject(snapshot)

    def test_receipt_cannot_drop_origin_or_reuse_another_payment_digest(self):
        game=self.game()
        for change in ('drop','state_hash'):
            snapshot=game.snapshot();receipt=self.receipt(snapshot)
            if change=='drop':receipt.pop('origin')
            else:receipt['original_state_hash']='0'*64
            self.reject(snapshot)

    def test_departed_targets_retain_original_candidate_facts(self):
        game=self.game('depart');receipt=game.state.play_history[-1].body_targets
        original=receipt.body_choices[0]
        self.assertEqual(len(original),2)
        self.assertEqual(sum(game.state.entities[i].zone==Zone.GRAVEYARD for i in original),1)
        self.roundtrip(game,lambda:registry('depart'))

    def test_later_created_entities_do_not_expand_original_universe(self):
        game=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('setup','unit','spawn'),board=('friend','friend'),mana=6,max_mana=6),PlayerSetup('hero',board=('enemy',)))),origin_registry())
        fixture=runtime_fixture.PaidBodyTargetRuntimeTests();game.apply(PlayCard(1,game.state.players[1].hand[0]));game.apply(fixture.action(game))
        receipt=game.state.play_history[-1].body_targets
        game.apply(PlayCard(1,game.state.players[1].hand[0]))
        created=game.state.players[1].board[-1]
        self.assertGreaterEqual(created,receipt.origin.next_entity_id)
        self.assertNotIn(created,{e.id for e in receipt.origin.entities})
        self.roundtrip(game,origin_registry)

    def test_terminal_original_authority_survives_current_source_lifecycle(self):
        for operation in ('silence','transform','control','return'):
            with self.subTest(operation=operation):
                game=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('setup','unit',operation),board=('friend','friend'),mana=6,max_mana=6),PlayerSetup('hero',board=('enemy',)))),origin_registry())
                fixture=runtime_fixture.PaidBodyTargetRuntimeTests();game.apply(PlayCard(1,game.state.players[1].hand[0]));game.apply(fixture.action(game))
                receipt=game.state.play_history[-1].body_targets
                game.apply(PlayCard(1,game.state.players[1].hand[0]))
                self.assertEqual(game.state.play_history[-2].body_targets,receipt)
                self.assertEqual(Game.from_snapshot(game.snapshot(),origin_registry()).snapshot(),game.snapshot())

    def test_waiting_restore_clone_and_actual_replay_keep_original_inputs(self):
        game=self.game('wait');self.assertIsNotNone(game.state.pending_choice)
        self.roundtrip(game,lambda:registry('wait'))
        snapshot=game.snapshot();receipt=self.receipt(snapshot)
        receipt['body_choices'][0].append(receipt['action']['target_id'])
        self.reject(snapshot,'wait')

    def test_waiting_real_continuation_cannot_be_cut_or_reordered(self):
        game=self.game('wait');snapshot=game.snapshot()
        queue=snapshot['resolution_frame']['fields']['continuation']['tuple']
        self.assertGreater(len(queue),1)
        for change in ('cut','reorder'):
            altered=deepcopy(snapshot);queue=altered['resolution_frame']['fields']['continuation']['tuple']
            if change=='cut':queue.pop()
            else:queue[0],queue[1]=queue[1],queue[0]
            self.reject(altered,'wait')

    def test_repeat_retained_weapon_and_hero_share_the_original_proof(self):
        for mode,carrier in (('repeat','unit'),('retained','unit'),('normal','weapon'),('normal','hero')):
            with self.subTest(mode=mode,carrier=carrier):
                game=self.game(mode,carrier=carrier)
                self.assertEqual(game.state.players[1].mana,4)
                self.roundtrip(game,lambda:registry(mode,carrier))

    def test_second_independent_paid_play_has_no_recursive_old_history(self):
        game=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('setup','unit','unit'),board=('friend','friend'),mana=6,max_mana=6),PlayerSetup('hero',board=('enemy',)))),registry())
        fixture=runtime_fixture.PaidBodyTargetRuntimeTests();game.apply(PlayCard(1,game.state.players[1].hand[0]));game.apply(fixture.action(game));game.apply(fixture.action(game))
        receipts=[p.body_targets for p in game.state.play_history if p.body_targets is not None]
        self.assertEqual(len(receipts),2)
        for receipt in receipts:
            text=json.dumps(asdict(receipt.origin))
            for forbidden in ('play_history','body_targets','payment_state','GameState','origin_hash'):
                self.assertNotIn(forbidden,text)
        self.roundtrip(game)

    def test_actual_failure_rolls_back_origin_resources_rng_and_player_knowledge(self):
        fixture=runtime_fixture.PaidBodyTargetRuntimeTests();game=fixture.game('fail');snapshot=game.snapshot()
        views=[game.for_player(s).observe() for s in (1,2)]
        with self.assertRaises(ResolutionError):game.apply(fixture.action(game))
        self.assertEqual(game.snapshot(),snapshot)
        self.assertEqual([game.for_player(s).observe() for s in (1,2)],views)

    def test_origin_proof_is_host_only_in_both_player_views_and_events(self):
        game=self.game()
        for seat in (1,2):
            text=json.dumps(game.for_player(seat).observe())
            for field in ('source_json','origin_hash','original_state_hash','body_choices','next_attachment_id'):
                self.assertNotIn(field,text)


if __name__=='__main__':unittest.main()
