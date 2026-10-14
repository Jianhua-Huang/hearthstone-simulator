"""Actual seat-bound commands, lifecycle identities and information isolation."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from test_paid_body_targets_runtime import registry
from hs_sim.engine import BodyReference,CardDefinition,CardType,Game,PlayCard,PlayerSetup,Scenario,SelectChoice,Zone
from hs_sim.engine.body_grants import RemoveGrantedBody
from hs_sim.engine.effects import Draw
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.zones import CardReference,CopyCard,MoveCard
from hs_sim.engine.errors import SnapshotError
from hs_sim.engine.replay import build_replay,replay
from hs_sim.engine.serialization import canonical_hash


def command_registry(mode='normal',carrier='unit'):
    result=registry(mode,carrier)
    def source(context):
        return next(e for e in context.state.entities.values() if e.card_id=='unit' and e.controller==context.player_id and e.zone==Zone.HAND)
    def remove(context):
        entity=source(context)
        ability=next(a for a in entity.abilities if a.kind=='battlecry' and a.origin=='granted')
        return [RemoveGrantedBody(BodyReference.capture(entity),ability.id,'battlecry',context.source_id)]
    result.register_behavior('remove',remove)
    result.register_behavior('copy',lambda c:[CopyCard(CardReference.capture(source(c)),c.player_id,source_id=c.source_id)])
    result.register_behavior('hide',lambda c:[MoveCard(CardReference.capture(source(c)),c.player_id,Zone.DECK,position='top',source_id=c.source_id)])
    result.register_behavior('draw',lambda c:[Draw(c.player_id,1)])
    for name in ('remove','copy','hide','draw'):
        result.register_card(CardDefinition(name,name,CardType.SPELL,on_play=name))
    return result


class PlayerBodyCommandTests(unittest.TestCase):
    def game(self,mode='normal',carrier='unit',*,enemy_card='enemy',limit=4096,board=('friend','friend'),setup=True):
        game=Game.from_scenario(Scenario((PlayerSetup('hero',hand=('setup','unit','tempo','remove','copy','hide','draw'),board=board,mana=6,max_mana=6),
            PlayerSetup('hero',board=('enemy',),hand=(enemy_card,)))),command_registry(mode,carrier),Ruleset(max_choice_combinations=limit))
        if setup:game.apply(PlayCard(1,game.state.players[1].hand[0]))
        return game

    def card(self,game,name='unit',index=0):
        return [c for c in game.for_player(1).observe()['observation']['players'][0]['hand'] if c.get('card_id')==name][index]['ref']

    def submission(self,game,card=None):
        port=game.for_player(1)
        options=port.independent_targets(card or self.card(game))
        self.assertIsNone(options['error'])
        choice=options['choices'][0]
        action={'type':'play_card','card':choice['card'],'target':choice['root_targets'][0],
            'body_targets':[{'body':b['body'],'target':b['targets'][i%len(b['targets'])]} for i,b in enumerate(choice['bodies'])]}
        return {'revision':options['revision'],'action':action}

    def play_spell(self,game,name):
        source=next(i for i in game.state.players[1].hand if game.state.entities[i].card_id==name)
        game.apply(PlayCard(1,source))

    def test_actual_player_json_uses_independent_body_targets_and_single_payment(self):
        game=self.game();command=self.submission(game)
        result=game.for_player(1).submit(command)
        self.assertTrue(result['accepted'],result)
        self.assertEqual(game.state.players[1].mana,4)
        records=(*game.state.battlecry_history,*game.state.combo_history)
        self.assertEqual(len(records),6)
        self.assertEqual(len({r.target_id for r in records}),2)
        self.assertNotIn(game.state.play_history[-1].target_id,{r.target_id for r in records})

    def test_original_player_submission_order_survives_canonical_execution(self):
        game=self.game();command=self.submission(game)
        command['action']['body_targets'].reverse()
        self.assertTrue(game.for_player(1).submit(command)['accepted'])
        receipt=game.state.play_history[-1].body_targets
        self.assertEqual([v.ability_id for v in receipt.action.body_targets],list(reversed([v.ability_id for v in receipt.selected])))

    def test_queries_are_pure_and_private_handle_shape_does_not_expose_engine_ids(self):
        game=self.game();snapshot=game.snapshot()
        first=game.for_player(1).independent_targets(self.card(game))
        self.assertEqual(game.for_player(1).independent_targets(self.card(game)),first)
        self.assertEqual(game.snapshot(),snapshot)
        for forbidden in ('ability_id','behavior_id','grant_source_id','zone_epoch','profile_id','original_state_hash','registry_fingerprint'):
            self.assertNotIn(forbidden,json.dumps(first))
        self.assertTrue(all(b['body'].startswith('b1_') for b in first['choices'][0]['bodies']))

    def test_enemy_hidden_body_identity_does_not_change_my_capabilities_or_options(self):
        first=self.game(enemy_card='enemy');second=self.game(enemy_card='unit')
        self.assertEqual(first.for_player(1).observe(),second.for_player(1).observe())
        self.assertEqual(first.for_player(1).independent_targets(self.card(first)),second.for_player(1).independent_targets(self.card(second)))
        self.assertNotEqual(first._information.players[1].body_refs,second._information.players[1].body_refs)

    def test_missing_duplicate_foreign_and_raw_internal_fields_reject_atomically(self):
        game=self.game();original=self.submission(game);snapshot=game.snapshot()
        mutations=(lambda a:a['body_targets'].pop(),
                   lambda a:a['body_targets'].append(deepcopy(a['body_targets'][0])),
                   lambda a:a['body_targets'][0].update(body='b2_1'),
                   lambda a:a['body_targets'][0].update(ability_id=1),
                   lambda a:a.update(body_target_profile_id='paid'),
                   lambda a:a['body_targets'][0].update(target=99))
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)):
                command=deepcopy(original);mutate(command['action'])
                self.assertFalse(game.for_player(1).submit(command)['accepted'])
                self.assertEqual(game.snapshot(),snapshot)

    def test_old_observation_revision_does_not_authorize_a_new_action(self):
        game=self.game();command=self.submission(game);self.play_spell(game,'tempo');snapshot=game.snapshot()
        result=game.for_player(1).submit(command)
        self.assertFalse(result['accepted']);self.assertEqual(result['error'],'stale_observation')
        self.assertEqual(game.snapshot(),snapshot)

    def test_removed_body_cannot_be_revived_using_a_fresh_revision(self):
        game=self.game();command=self.submission(game);self.play_spell(game,'remove')
        command['revision']=game.for_player(1).observe()['revision'];snapshot=game.snapshot()
        self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(),snapshot)
        self.assertEqual(len(self.submission(game)['action']['body_targets']),5)

    def test_copied_carrier_has_own_handles_and_cannot_borrow_original_bodies(self):
        game=self.game();command=self.submission(game);self.play_spell(game,'copy')
        fresh=self.submission(game,self.card(game,index=1))
        self.assertTrue(set(b['body'] for b in command['action']['body_targets']).isdisjoint(b['body'] for b in fresh['action']['body_targets']))
        borrowed=deepcopy(command);borrowed['revision']=fresh['revision'];borrowed['action']['card']=fresh['action']['card'];snapshot=game.snapshot()
        self.assertFalse(game.for_player(1).submit(borrowed)['accepted']);self.assertEqual(game.snapshot(),snapshot)

    def test_hidden_deck_return_retires_source_and_all_old_body_handles(self):
        game=self.game();command=self.submission(game);old_handles={b['body'] for b in command['action']['body_targets']}
        self.play_spell(game,'hide');self.play_spell(game,'draw')
        fresh=self.submission(game)
        self.assertTrue(old_handles.isdisjoint(b['body'] for b in fresh['action']['body_targets']))
        command['revision']=fresh['revision'];command['action']['card']=fresh['action']['card'];snapshot=game.snapshot()
        self.assertFalse(game.for_player(1).submit(command)['accepted']);self.assertEqual(game.snapshot(),snapshot)

    def test_bounded_enumeration_preserves_direct_complete_submission(self):
        game=self.game(limit=2)
        legal=game.for_player(1).legal_actions()
        self.assertIsNone(legal['actions']);self.assertEqual(legal['error'],'enumeration_limit')
        self.assertTrue(game.for_player(1).submit(self.submission(game))['accepted'])

    def test_enemy_hand_reference_cannot_query_private_bodies(self):
        game=self.game(enemy_card='unit');port=game.for_player(1)
        enemy=port.observe()['observation']['players'][1]['hand'][0]['ref'];snapshot=game.snapshot()
        result=port.independent_targets(enemy)
        self.assertIsNone(result['choices']);self.assertEqual(result['error'],'invalid_action')
        self.assertEqual(game.snapshot(),snapshot)

    def test_inactive_combo_and_empty_pool_have_explicit_none_commands(self):
        game=self.game(board=(),setup=False)
        command=self.submission(game)
        self.assertTrue(all(b['target'] is None for b in command['action']['body_targets']))
        self.assertTrue(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(len(game.state.battlecry_history),1);self.assertFalse(game.state.combo_history)

    def test_completed_snapshot_clone_and_actual_replay_preserve_player_contract(self):
        game=self.game();self.assertTrue(game.for_player(1).submit(self.submission(game))['accepted']);snapshot=game.snapshot()
        for other in (Game.from_snapshot(snapshot,command_registry()),game.clone(),replay(build_replay(game),command_registry())):
            self.assertEqual(other.snapshot(),snapshot)
            for viewer in (1,2):self.assertEqual(other.for_player(viewer).observe(),game.for_player(viewer).observe())

    def test_each_actual_player_wait_restores_clones_and_replays(self):
        game=self.game('wait');self.assertTrue(game.for_player(1).submit(self.submission(game))['accepted']);count=0
        while game.state.pending_choice is not None:
            count+=1;snapshot=game.snapshot()
            for other in (Game.from_snapshot(snapshot,command_registry('wait')),game.clone(),replay(build_replay(game),command_registry('wait'))):
                self.assertEqual(other.snapshot(),snapshot)
                self.assertEqual(other.for_player(1).observe(),game.for_player(1).observe())
            port=game.for_player(1);legal=port.legal_actions()
            self.assertIsNone(legal['error']);self.assertTrue(port.submit({'revision':legal['revision'],'action':legal['actions'][0]})['accepted'])
        self.assertEqual(count,6)

    def test_rehashed_missing_duplicate_and_foreign_private_ledger_rejected(self):
        game=self.game();original=game.snapshot()
        mutations=(lambda k:k['body_refs'].pop(next(iter(k['body_refs']))),
                   lambda k:k['body_refs'].update({next(iter(k['body_refs'])):'b2_1'}),
                   lambda k:k.update(next_body_ref=True),
                   lambda k:k['body_refs'].update(dict.fromkeys(k['body_refs'],'b1_1')))
        for mutate in mutations:
            snapshot=deepcopy(original);mutate(snapshot['information']['players']['1'])
            snapshot['state_hash']=canonical_hash({k:v for k,v in snapshot.items() if k not in ('schema_version','events','events_hash','state_hash')})
            with self.assertRaises(SnapshotError):Game.from_snapshot(snapshot,command_registry())

    def test_actual_body_failure_rolls_back_private_capabilities_and_payment(self):
        game=self.game('fail');command=self.submission(game);snapshot=game.snapshot()
        self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(),snapshot)
