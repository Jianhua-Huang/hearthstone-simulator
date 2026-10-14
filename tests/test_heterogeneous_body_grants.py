"""Actual public grants, complete paid targets and combination boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import examples.heterogeneous_grants as fixture
from hs_sim.engine import (BodyReference, BodyTargetBinding, BodyTargetProfile,
    Game, GrantBattlecry, IllegalAction, PlayCard, PlayerSetup, Scenario,
    SelectChoice, Zone, paid_body_root_target_plan)
from hs_sim.engine.actions import EndTurn
from hs_sim.engine.body_grant_authority import authorize_grant
from hs_sim.engine.body_target_authority import body_target_authorities
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import AbilityInstance
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


class HeterogeneousBodyGrantTests(unittest.TestCase):
    def game(self, mode='normal', carrier='minion', variant='complete', *, setup=True,
             hand=None, **kwargs):
        scenario = fixture.scenario(mode, **kwargs)
        if hand is not None:
            scenario = replace(scenario, players=(replace(scenario.players[0], hand=hand), scenario.players[1]))
        game = Game.from_scenario(scenario, fixture.registry(mode, carrier, variant))
        if setup: self.spell(game, 'setup')
        return game

    def source(self, game, zone=Zone.HAND, index=0):
        return [e for e in game.state.entities.values() if e.card_id == 'unit' and e.zone == zone][index]

    def spell(self, game, name, target=None):
        source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == name)
        game.apply(PlayCard(1, source, target))

    def paid(self, game, *, card=None, position=None, optional_none=False):
        command = fixture.command(game, card, position, optional_none=optional_none)
        result = game.for_player(1).submit(command)
        self.assertTrue(result['accepted'], result)
        return command

    def roundtrip(self, game, mode='normal', carrier='minion'):
        snapshot = game.snapshot()
        for other in (Game.from_snapshot(snapshot, fixture.registry(mode, carrier)),
                      game.clone(), replay(build_replay(game), fixture.registry(mode, carrier))):
            self.assertEqual(other.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(other.for_player(player).observe(), game.for_player(player).observe())

    def body_ids(self, game, zone=Zone.HAND, index=0):
        return [a.id for a in self.source(game, zone, index).abilities if a.kind in ('battlecry', 'combo') and not a.consumed]

    def test_real_public_grants_and_four_distinct_domains_pay_once(self):
        game = self.game(); source = self.source(game)
        self.assertEqual(len(self.body_ids(game)), 11)
        self.assertEqual(len([e for e in game.events if e.kind == 'ability_granted']), 9)
        friend = game.state.players[1].board[0]; enemy = game.state.players[2].board[0]
        hand = game.state.players[1].hand[0]
        self.paid(game); play = game.state.play_history[-1]
        self.assertEqual(game.state.players[1].mana, 4)
        self.assertEqual(play.source_id, source.id)
        self.assertEqual(game.state.entities[enemy].damage, 2)
        self.assertEqual([game.state.entities[i].attack for i in (friend, enemy, hand)], [3, 4, 3])
        records = (*game.state.battlecry_history, *game.state.combo_history)
        self.assertEqual(len(records), 11)
        self.assertEqual([r.target_id for r in records], [v.target_id for v in play.body_targets.selected])
        self.assertEqual(set(r.target_id for r in records), {friend, enemy, hand, None})
        self.assertIsNotNone(play.paid_hand_close)

    def test_authority_checks_complete_prospective_vector_without_allocating_or_querying(self):
        game = self.game(setup=False); source = self.source(game)
        ability = AbilityInstance(game.state.next_attachment_id, 'battlecry', behavior_id='body',
            source_id=source.id, battlecry_card_id='enemy_body')
        snapshot = game.snapshot(); rng = game._rng.getstate()
        with (patch('hs_sim.engine.costs.quote_cost', side_effect=AssertionError('unexpected quote')),
              patch('hs_sim.engine.targeting.target_choices', side_effect=AssertionError('unexpected target query'))):
            self.assertEqual(authorize_grant(game._state, game.registry, game._state.entities[source.id], ability), 'paid')
        self.assertEqual(game.snapshot(), snapshot); self.assertEqual(game._rng.getstate(), rng)

    def test_incomplete_profile_root_existing_new_origin_kind_and_card_refuse_atomically(self):
        for variant in ('missing_root', 'profile_only', 'missing_printed', 'missing_new',
                        'wrong_origin', 'wrong_kind', 'wrong_card', 'different_profile'):
            with self.subTest(variant=variant):
                game = self.game(variant=variant, setup=False); snapshot = game.snapshot(); history = game.history
                with self.assertRaises(ResolutionError): self.spell(game, 'setup')
                self.assertEqual(game.snapshot(), snapshot); self.assertEqual(game.history, history)

    def test_custom_body_and_root_predicate_are_rejected_before_the_callback(self):
        game = self.game(variant='custom_body', setup=False); snapshot = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'complete connected origin target policy'): self.spell(game, 'setup')
        self.assertEqual(game.snapshot(), snapshot)
        # Root selection is independent of body storage. Its unsupported paid
        # consumer must reject before the callback, but grants can be stored.
        game = self.game(variant='custom_root')
        self.assertEqual(len(self.body_ids(game)), 11)
        snapshot = game.snapshot()
        result = game.for_player(1).independent_targets(fixture.card_ref(game))
        self.assertEqual(result['error'], 'unsupported_rule')
        self.assertEqual(game.snapshot(), snapshot)

    def test_overlapping_other_profile_cannot_authorize_same_physical_origin(self):
        registry = fixture.registry()
        with self.assertRaisesRegex(ValueError, 'Ambiguous body target profiles'):
            registry.register_body_target_binding(BodyTargetBinding('enemy_body', 'battlecry', 'other'))

    def test_target_conditions_and_distinct_thresholds_keep_explicit_none(self):
        game = self.game(); source = self.source(game)
        plan = paid_body_root_target_plan(game, PlayCard(1, source.id, game.state.players[2].board[0]), 'paid')
        by_name = {r.declaration.reference.declaration_card_id: r for r in plan.bodies.requirements}
        self.assertEqual(by_name['conditional'].target_choices, (None,))
        self.assertEqual(by_name['high'].target_choices, (None,))
        self.assertTrue(by_name['low'].target_active)
        self.assertNotIn(None, by_name['low'].target_choices)
        self.paid(game)
        selected = {v.declaration_card_id: v.target_id for v in game.state.play_history[-1].body_targets.selected}
        self.assertIsNone(selected['conditional']); self.assertIsNone(selected['high'])
        self.assertIsNotNone(selected['low'])

    def test_original_outcast_activates_its_own_enemy_requirement(self):
        game = self.game(outcast=True); self.paid(game)
        receipt = game.state.play_history[-1].body_targets
        slot = next(v for v in receipt.selected if v.declaration_card_id == 'conditional')
        self.assertIn(slot.target_id, game.state.players[2].board)
        self.assertTrue(receipt.body_target_active[receipt.selected.index(slot)])

    def test_optional_hand_none_is_valid_but_required_enemy_none_refuses_whole_root(self):
        game = self.game(); command = fixture.command(game, optional_none=True)
        snapshot = game.snapshot(); bad = deepcopy(command)
        bad['action']['body_targets'][1]['target'] = None
        self.assertFalse(game.for_player(1).submit(bad)['accepted']); self.assertEqual(game.snapshot(), snapshot)
        self.assertTrue(game.for_player(1).submit(command)['accepted'])
        slot = next(v for v in game.state.play_history[-1].body_targets.selected if v.declaration_card_id == 'hand_body')
        self.assertIsNone(slot.target_id)

    def test_empty_if_available_friendly_does_not_join_source_after_entry(self):
        game = self.game(empty_friend=True); self.paid(game)
        selected = [v for v in game.state.play_history[-1].body_targets.selected if v.declaration_card_id == 'unit']
        self.assertEqual([v.target_id for v in selected], [None, None])
        self.assertEqual(self.source(game, Zone.BOARD).attack, 1)

    def test_grant_does_not_require_candidates_but_real_payment_cannot_ignore_empty_required(self):
        game = self.game(enemy_board=()); snapshot = game.snapshot()
        options = game.for_player(1).independent_targets(fixture.card_ref(game))
        self.assertIsNone(options['error']); self.assertEqual(options['choices'], [])
        self.assertEqual(game.snapshot(), snapshot); self.assertEqual(len(self.body_ids(game)), 11)

    def test_disabled_combo_requires_all_none_after_a_real_turn_boundary(self):
        game = self.game(); game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.paid(game)
        receipt = game.state.play_history[-1].body_targets
        self.assertTrue(all(v.target_id is None for v in receipt.selected if v.family == 'combo'))
        self.assertFalse(game.state.combo_history); self.assertEqual(len(game.state.battlecry_history), 7)

    def test_two_same_declarations_keep_independent_physical_targets(self):
        game = self.game(hand=('setup', 'unit', 'fodder', 'duplicate'))
        self.spell(game, 'duplicate'); command = fixture.command(game)
        option = game.for_player(1).independent_targets(fixture.card_ref(game))['choices'][0]
        # Last Battlecry slot is the second independently granted enemy body.
        command['action']['body_targets'][7]['target'] = option['bodies'][7]['targets'][-1]
        self.assertTrue(game.for_player(1).submit(command)['accepted'])
        rows = [r for r in game.state.battlecry_history if r.payload.card_id == 'enemy_body']
        self.assertEqual(len(rows), 2); self.assertNotEqual(rows[0].payload.ability_id, rows[1].payload.ability_id)
        self.assertEqual([r.target_id for r in rows], game.state.players[2].board)

    def test_repeat_reuses_each_body_target_and_each_family_budget(self):
        game = self.game('repeat'); self.paid(game)
        self.assertEqual(len(game.state.battlecry_history), 14); self.assertEqual(len(game.state.combo_history), 12)
        self.assertEqual(game.state.players[1].mana, 4)
        receipt = game.state.play_history[-1].body_targets
        for r in (*game.state.battlecry_history, *game.state.combo_history):
            slot = next(v for v in receipt.selected if v.ability_id == r.payload.ability_id)
            self.assertEqual(r.target_id, slot.target_id)

    def test_retained_results_keep_one_paid_original_heterogeneous_vector(self):
        game = self.game('retained'); self.paid(game)
        self.assertEqual(len(game.state.battlecry_history), 14); self.assertEqual(len(game.state.combo_history), 8)
        self.assertEqual(game.state.players[1].mana, 4)
        self.assertEqual(game.state.rewind_outcomes[-1].completed, 2)

    def test_second_family_failure_rolls_back_first_family_rng_payment_and_player_handles(self):
        game = self.game('fail'); command = fixture.command(game); snapshot = game.snapshot(); history = game.history
        self.assertFalse(game.for_player(1).submit(command)['accepted'])
        self.assertEqual(game.snapshot(), snapshot); self.assertEqual(game.history, history)

    def test_weapon_and_hero_carriers_keep_independent_domains(self):
        for carrier, count in (('weapon', 10), ('hero', 11)):
            game = self.game(carrier=carrier); self.paid(game)
            records = (*game.state.battlecry_history, *game.state.combo_history)
            self.assertEqual(len(records), count); self.assertEqual(game.state.players[1].mana, 4)
            self.assertEqual([r.target_id for r in records], [v.target_id for v in game.state.play_history[-1].body_targets.selected])

    def test_current_copy_owns_new_body_handles_and_base_copy_keeps_printed_only(self):
        game = self.game(hand=('setup', 'unit', 'fodder', 'copy', 'base_copy'))
        original = fixture.command(game); ids = self.body_ids(game)
        self.spell(game, 'copy'); self.spell(game, 'base_copy')
        self.assertEqual([len(self.body_ids(game, index=i)) for i in range(3)], [11, 11, 2])
        self.assertTrue(set(ids).isdisjoint(self.body_ids(game, index=1)))
        fresh = fixture.command(game, fixture.card_ref(game, index=1))
        stale = deepcopy(original); stale['revision'] = fresh['revision']; stale['action']['card'] = fresh['action']['card']
        snapshot = game.snapshot(); self.assertFalse(game.for_player(1).submit(stale)['accepted'])
        self.assertEqual(game.snapshot(), snapshot); self.paid(game, card=fresh['action']['card'])

    def test_deck_grants_draw_and_real_payment_keep_attachment_identity(self):
        game = self.game(zone='deck'); ids = self.body_ids(game, Zone.DECK)
        self.spell(game, 'draw'); self.assertEqual(self.body_ids(game), ids); self.paid(game)
        self.assertEqual([v.ability_id for v in game.state.play_history[-1].body_targets.selected],
            [a.declaration.reference.ability_id for a in body_target_authorities(
                game._state, game.registry, BodyReference.capture(game._state.entities[self.source(game, Zone.BOARD).id]), 'paid')])

    def test_cross_zone_roundtrip_retires_old_source_and_body_handles(self):
        game = self.game(); original = fixture.command(game); ids = self.body_ids(game)
        self.spell(game, 'hide'); self.spell(game, 'draw'); fresh = fixture.command(game)
        self.assertEqual(self.body_ids(game), ids)
        old = {v['body'] for v in original['action']['body_targets']}
        self.assertTrue(old.isdisjoint(v['body'] for v in fresh['action']['body_targets']))
        original['revision'] = fresh['revision']; original['action']['card'] = fresh['action']['card']
        snapshot = game.snapshot(); self.assertFalse(game.for_player(1).submit(original)['accepted'])
        self.assertEqual(game.snapshot(), snapshot); self.paid(game)

    def test_remove_and_consume_retire_only_exact_bodies_before_new_payment(self):
        game = self.game(); original = fixture.command(game)
        self.spell(game, 'consume'); self.spell(game, 'remove')
        self.assertEqual(len(self.body_ids(game)), 9)
        original['revision'] = game.for_player(1).observe()['revision']; snapshot = game.snapshot()
        self.assertFalse(game.for_player(1).submit(original)['accepted']); self.assertEqual(game.snapshot(), snapshot)
        self.paid(game); self.assertEqual(len(game.state.battlecry_history), 5)

    def test_expiry_retires_heterogeneous_grants_in_hand_deck_and_board(self):
        for zone in ('hand', 'deck', 'board'):
            game = self.game('expiry', zone=zone); source = self.source(game, Zone(zone))
            self.assertEqual(len(self.body_ids(game, Zone(zone))), 11)
            game.apply(EndTurn(1))
            self.assertEqual(len(self.body_ids(game, Zone(zone))), 2)
            self.assertEqual(source.id, self.source(game, Zone(zone)).id)

    def test_board_storage_copy_control_silence_transform_and_return_use_common_lifecycle(self):
        for operation, target_zone, expected in (('board_copy', Zone.BOARD, 11), ('control', Zone.BOARD, 11),
                ('silence', Zone.BOARD, 0), ('transform', Zone.BOARD, 0), ('return', Zone.HAND, 2)):
            with self.subTest(operation=operation):
                game = self.game(zone='board', hand=('setup', operation, 'fodder'))
                source = self.source(game, Zone.BOARD); self.spell(game, operation, source.id)
                current = game.state.entities[source.id]
                self.assertEqual(current.zone, target_zone)
                self.assertEqual(len([a for a in current.abilities if a.kind in ('battlecry', 'combo')]), expected)
                self.assertFalse(game.state.battlecry_history); self.assertFalse(game.state.combo_history)
                if operation == 'control': self.assertEqual(current.controller, 2)
                if operation == 'board_copy':
                    copy = self.source(game, Zone.BOARD, index=1)
                    self.assertEqual(len(self.body_ids(game, Zone.BOARD, index=1)), 11)
                    self.assertTrue(set(a.id for a in current.abilities).isdisjoint(a.id for a in copy.abilities))

    def test_player_queries_and_events_hide_origin_profile_and_enemy_hand_identity(self):
        first = self.game(enemy_card='enemy'); second = self.game(enemy_card='unit')
        self.assertEqual(first.for_player(1).observe(), second.for_player(1).observe())
        options = first.for_player(1).independent_targets(fixture.card_ref(first))
        self.assertEqual(options, second.for_player(1).independent_targets(fixture.card_ref(second)))
        self.paid(first)
        for player in (1, 2):
            raw = json.dumps(first.for_player(player).observe()) + json.dumps(first.for_player(player).events())
            for private in ('origin_hash', 'source_entity_json', 'grant_source_id', 'body_target_profile_id', 'registry_fingerprint'):
                self.assertNotIn(private, raw)

    def test_completed_original_domains_restore_clone_and_action_replay(self):
        game = self.game('compact'); self.paid(game); self.roundtrip(game, 'compact')

    def test_each_real_wait_restores_clone_and_action_replay_before_resume(self):
        game = self.game('wait'); self.paid(game); count = 0
        while game.state.pending_choice is not None:
            count += 1; self.roundtrip(game, 'wait')
            choice = game.state.pending_choice
            game.apply(SelectChoice(choice.player_id, choice.id, ('go',)))
        self.assertEqual(count, 5); self.roundtrip(game, 'wait')

    def test_fresh_rewind_retry_remains_an_explicit_unconnected_dependency(self):
        game = self.game('retry'); snapshot = game.snapshot()
        self.assertFalse(game.for_player(1).submit(fixture.command(game))['accepted'])
        self.assertEqual(game.snapshot(), snapshot)

