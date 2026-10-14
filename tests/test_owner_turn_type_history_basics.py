"""Pure complete own-interval relations over the original frozen play history."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

import test_m5_owner_turn_history as fixtures
import test_m5_owner_turn_opening as opening_fixtures
import test_m5_owner_turn_startup as startup_fixtures
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    IllegalAction, OwnerTurnTypeHistory, OwnerTurnTypeMatch, PlayedTypeQuery, QueueTurns,
    Rarity, ResolutionError, Ruleset, SkipTurns, SpellSchool, TriggerSpec, UseHeroPower,
    query_for_definition, query_owner_turn_history, query_previous_owner_turn)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, Destroy, InvokeBehavior,
    RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.model import OwnerTurnMatchRow
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import PlayFromHand
from hs_sim.targets import canonical_digest
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION

SUPPORT = Path(__file__).resolve().parents[1]/'data/support/owner-turn-type-history-basics.json'
PIN = 'b492c6115b29f02a9afd9eda9ad9d12a0200095846ed6676f82120f7f0a3f563'
NATIVE = 'CS2_118'
ELEMENTAL = PlayedTypeQuery(CardType.MINION, ('elemental',))


def evidence():
    support = json.loads(SUPPORT.read_bytes())
    if canonical_digest(support) != PIN:
        raise ValueError('Complete owner-type source evidence changed')
    records = {}
    for row in support['records']:
        if canonical_digest(row['data']) != row['data_sha256']:
            raise ValueError('Complete original card changed')
        records[row['id']] = row['data']
    return records


def native_definition():
    raw = evidence()[NATIVE]
    return CardDefinition(NATIVE, raw['name'], CardType.MINION,
        cost=raw['cost'], attack=raw['attack'], health=raw['health'],
        metadata=CardMetadata(True, (CardClass.NEUTRAL,), Rarity.FREE, tribes=('elemental',)))


class OwnerTurnTypeHistoryTests(unittest.TestCase):
    game = fixtures.OwnerTurnActionTests.game
    play = fixtures.OwnerTurnActionTests.play
    end = fixtures.OwnerTurnActionTests.end
    choose = fixtures.OwnerTurnActionTests.choose
    script = fixtures.OwnerTurnActionTests.script
    fresh_registry = fixtures.OwnerTurnActionTests.fresh_registry

    def setUp(self):
        fixtures.OwnerTurnActionTests.setUp(self)
        self.r.register_card(native_definition())

    def relation(self, game, player=1, query=ELEMENTAL):
        return query_owner_turn_history(game.state, player, query)

    def flags(self, game, player=1, query=ELEMENTAL):
        return [r.matched for r in self.relation(game, player, query).intervals]

    def next_own(self, game):
        self.end(game); self.end(game)

    def portable_relation(self, game, player=1, query=ELEMENTAL):
        original = self.relation(game, player, query)
        snapshot = json.loads(json.dumps(game.snapshot()))
        clones = (Game.from_snapshot(snapshot, self.fresh_registry(), mechanics=game.mechanics),
            game.clone(), replay(build_replay(game), self.fresh_registry(), mechanics=game.mechanics))
        for clone in clones:
            self.assertEqual(clone.snapshot(), snapshot)
            self.assertEqual(self.relation(clone, player, query), original)
        return clones

    def test_complete_raw_pin_and_necessary_vanilla_elemental_definition(self):
        rows = evidence(); definition = self.r.card(NATIVE)
        self.assertEqual(set(rows), {NATIVE, 'WW_025', 'TRL_313'})
        self.assertEqual((rows[NATIVE]['dbf_id'], definition.cost, definition.attack, definition.health), (1653, 3, 5, 1))
        self.assertEqual(rows[NATIVE]['text'], '')
        self.assertEqual(definition.metadata.tribes, ('elemental',))
        self.assertEqual(definition.metadata.rarity, Rarity.FREE)
        self.assertIsNone(definition.on_play)
        self.assertIsNone(definition.battlecry)
        self.assertNotIn('WW_025', self.r.cards)
        self.assertNotIn('TRL_313', self.r.cards)
        self.assertEqual(query_for_definition(definition), ELEMENTAL)

    def test_initial_scenario_preserves_one_conceptual_empty_interval(self):
        for player in (1, 2):
            game = self.game(board=(NATIVE,), active=player)
            relation = self.relation(game, player)
            self.assertEqual(len(relation.intervals), 1)
            row = relation.intervals[0]
            self.assertEqual((row.owner_turn.origin, row.owner_turn.owner_index, row.matched), ('scenario', 1, False))
            self.assertFalse(row.owner_turn.closed)
            self.assertEqual(row.rows, ())
            self.assertEqual(relation.outside_owner_turn_faces, ())
            self.assertEqual(self.relation(game, 3-player).intervals, ())

    def test_current_true_relation_does_not_change_latest_closed_query(self):
        game = self.game((NATIVE,)); self.play(game, NATIVE)
        relation = self.relation(game)
        self.assertEqual([r.matched for r in relation.intervals], [True])
        self.assertEqual(relation.intervals[0].rows[0].face.card_id, NATIVE)
        previous = query_previous_owner_turn(game.state, 1, ELEMENTAL)
        self.assertIsNone(previous.owner_turn)
        self.assertFalse(previous.matched)

    def test_complete_true_false_true_rows_keep_original_submission_order(self):
        game = self.game((NATIVE, 'empty', NATIVE))
        for card in (NATIVE, 'empty', NATIVE): self.play(game, card)
        row, = self.relation(game).intervals
        self.assertEqual([r.matched for r in row.rows], [True, False, True])
        self.assertEqual([r.face.play_id for r in row.rows], [1, 2, 3])
        self.assertTrue(row.matched)

    def test_multiple_elementals_in_one_interval_are_one_matched_interval(self):
        game = self.game((NATIVE, NATIVE))
        self.play(game, NATIVE); self.play(game, NATIVE)
        relation = self.relation(game)
        self.assertEqual(len(relation.intervals), 1)
        self.assertEqual(len(relation.intervals[0].rows), 2)
        self.assertEqual([r.owner_turn.owner_index for r in relation.intervals if r.matched], [1])

    def test_all_ordered_closed_empty_and_current_intervals_are_retained(self):
        game = self.game((NATIVE, NATIVE))
        self.play(game, NATIVE); self.next_own(game)
        self.next_own(game)
        self.play(game, NATIVE); self.next_own(game)
        relation = self.relation(game)
        self.assertEqual([r.owner_turn.id for r in relation.intervals], [1, 3, 5, 7])
        self.assertEqual([r.owner_turn.owner_index for r in relation.intervals], [1, 2, 3, 4])
        self.assertEqual([r.matched for r in relation.intervals], [True, False, True, False])
        self.assertEqual([r.owner_turn.closed for r in relation.intervals], [True, True, True, False])

    def test_inactive_players_history_uses_actual_owned_intervals(self):
        game = self.game((NATIVE,), enemy_hand=(NATIVE,))
        self.play(game, NATIVE); self.end(game); self.play(game, NATIVE, player=2)
        self.assertEqual(self.flags(game, 1), [True])
        self.assertEqual(self.flags(game, 2), [True])
        self.assertTrue(self.relation(game, 1).intervals[0].owner_turn.closed)
        self.assertEqual(self.relation(game, 2).intervals[0].owner_turn.id, 2)

    def test_queued_same_player_turns_use_owner_chain_without_global_parity(self):
        self.script('one-extra', lambda c: [QueueTurns((1,), c.source_id)])
        game = self.game((NATIVE, 'one-extra', NATIVE))
        self.play(game, NATIVE); self.play(game, 'one-extra'); self.end(game)
        self.assertEqual((game.state.turn, game.state.active_player), (2, 1))
        self.play(game, NATIVE)
        self.assertEqual([r.owner_turn.turn for r in self.relation(game).intervals], [1, 2])
        self.assertEqual(self.flags(game), [True, True])

    def test_skipped_opportunity_does_not_create_an_empty_owned_interval(self):
        self.script('skip-opponent', lambda c: [SkipTurns(2, source_id=c.source_id)])
        game = self.game((NATIVE, 'skip-opponent', NATIVE))
        self.play(game, NATIVE); self.play(game, 'skip-opponent'); self.end(game)
        self.assertEqual(game.state.active_player, 1)
        self.play(game, NATIVE)
        self.assertEqual([r.owner_turn.owner_index for r in self.relation(game).intervals], [1, 2])
        self.assertEqual(self.relation(game, 2).intervals, ())

    def test_tribe_all_matches_nonempty_but_explicit_empty_never_matches(self):
        game = self.game((NATIVE, 'empty', 'all'))
        for card in (NATIVE, 'empty', 'all'): self.play(game, card)
        self.assertEqual([r.matched for r in self.relation(game).intervals[0].rows], [True, False, True])
        all_query = PlayedTypeQuery(CardType.MINION, ('all',))
        self.assertEqual([r.matched for r in self.relation(game, query=all_query).intervals[0].rows], [True, False, True])
        self.assertEqual(self.flags(game, query=PlayedTypeQuery(CardType.MINION, ())), [False])

    def test_native_printed_identity_survives_later_transform(self):
        self.script('mutate', lambda c: [Transform(c.state.players[1].board[0], 'beast')])
        game = self.game((NATIVE, 'mutate')); source = self.play(game, NATIVE)
        self.play(game, 'mutate')
        self.assertEqual(game.state.entities[source].card_id, 'beast')
        self.assertEqual(self.flags(game), [True])
        self.assertEqual(self.relation(game).intervals[0].rows[0].face.card_id, NATIVE)

    def test_native_printed_identity_survives_death_and_control_transfer(self):
        for mode in ('death', 'control'):
            self.setUp()
            effect = (lambda c: [Destroy(c.state.players[1].board[0])]) if mode == 'death' else (lambda c: [ChangeControl(c.state.players[1].board[0], 2)])
            self.script('move', effect)
            game = self.game((NATIVE, 'move')); self.play(game, NATIVE); self.play(game, 'move')
            self.assertEqual(self.flags(game), [True])
            self.assertEqual(self.relation(game).intervals[0].rows[0].face.player_id, 1)

    def test_same_physical_bounce_and_replay_keeps_two_submissions(self):
        self.script('bounce', lambda c: [ReturnToHand(c.state.players[1].board[0])])
        game = self.game((NATIVE, 'bounce')); source = self.play(game, NATIVE)
        self.play(game, 'bounce'); self.play(game, NATIVE)
        rows = self.relation(game).intervals[0].rows
        self.assertEqual(len(rows), 2)
        self.assertEqual([r.face.source_id for r in rows], [source, source])
        self.assertEqual([r.face.play_id for r in rows], [1, 3])

    def test_effect_summon_does_not_invent_a_hand_submission(self):
        self.script('summon-native', lambda c: [Summon(c.player_id, NATIVE)])
        game = self.game(('summon-native',)); self.play(game, 'summon-native')
        self.assertEqual(self.flags(game), [False])
        self.assertEqual(self.relation(game).intervals[0].rows, ())
        self.assertEqual(len(game.state.successful_summon_history), 1)

    def test_unknown_after_true_current_row_is_not_hidden_by_aggregate(self):
        game = self.game((NATIVE, 'unknown')); self.play(game, NATIVE); self.play(game, 'unknown')
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'): self.relation(game)
        self.assertFalse(query_previous_owner_turn(game.state, 1, ELEMENTAL).matched)

    def test_full_history_checks_old_unknown_even_after_latest_empty_interval(self):
        game = self.game(('unknown',)); self.play(game, 'unknown')
        self.next_own(game); self.next_own(game)
        self.assertFalse(query_previous_owner_turn(game.state, 1, ELEMENTAL).matched)
        with self.assertRaisesRegex(ValueError, 'known Minion tribes'): self.relation(game)

    def test_other_players_unknown_face_does_not_poison_selected_owner(self):
        game = self.game((NATIVE,), enemy_hand=('unknown',)); self.play(game, NATIVE)
        self.end(game); self.play(game, 'unknown', player=2)
        self.assertEqual(self.flags(game), [True])
        with self.assertRaises(ValueError): self.relation(game, 2)

    def test_unknown_query_is_rejected_even_without_a_matching_owner_interval(self):
        game = self.game()
        with self.assertRaisesRegex(ValueError, 'unknown Minion tribes'):
            self.relation(game, 2, PlayedTypeQuery(CardType.MINION, None))

    def test_foreign_owner_hand_play_is_retained_outside_without_fabricating_turn(self):
        self.r.register_behavior('offturn-elemental', lambda c: [PlayFromHand(fixtures.PlayCard(2,
            c.state.players[2].hand[0], position=len(c.state.players[2].board)))])
        self.r.register_card(CardDefinition('offturn-power', 'offturn-power', CardType.HERO_POWER,
            on_use='offturn-elemental', metadata=fixtures.metadata(card_class=CardClass.MAGE, collectible=False)))
        game = self.game(enemy_hand=(NATIVE,), power='offturn-power')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        relation = self.relation(game, 2)
        self.assertEqual(relation.intervals, ())
        face, = relation.outside_owner_turn_faces
        self.assertEqual((face.card_id, face.player_id, face.owner_turn_id), (NATIVE, 2, 1))
        self.end(game)
        relation = self.relation(game, 2)
        self.assertEqual([r.matched for r in relation.intervals], [False])
        self.assertEqual(relation.outside_owner_turn_faces, (face,))

    def test_foreign_owner_unknown_face_is_preserved_without_own_type_matching(self):
        self.r.register_behavior('offturn-unknown', lambda c: [PlayFromHand(fixtures.PlayCard(2,
            c.state.players[2].hand[0], position=0))])
        self.r.register_card(CardDefinition('offturn-power', 'offturn-power', CardType.HERO_POWER,
            on_use='offturn-unknown', metadata=fixtures.metadata(card_class=CardClass.MAGE, collectible=False)))
        game = self.game(enemy_hand=('unknown',), power='offturn-power')
        game.apply(UseHeroPower(1, game.state.players[1].hero_power_id))
        relation = self.relation(game, 2)
        self.assertEqual(relation.intervals, ())
        self.assertIsNone(relation.outside_owner_turn_faces[0].metadata.tribes)

    def test_spell_school_complete_true_false_and_unschooled_relations(self):
        game = self.game(('arcane', 'frost', 'unschooled'))
        for card in ('arcane', 'frost', 'unschooled'): self.play(game, card)
        arcane = PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE)
        self.assertEqual([r.matched for r in self.relation(game, query=arcane).intervals[0].rows], [True, False, False])
        self.assertEqual(self.flags(game, query=PlayedTypeQuery(CardType.SPELL)), [False])
        self.assertEqual(self.relation(game).intervals[0].rows, ())

    def test_pre_first_paid_face_is_retained_outside_current_real_interval(self):
        fixture = opening_fixtures.OpeningPaidPhaseTests(); fixture.setUp()
        game = fixture.opening()
        query = PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE)
        relation = self.relation(game, query=query)
        self.assertEqual(len(relation.intervals), 1)
        self.assertEqual(relation.intervals[0].owner_turn.origin, 'actual')
        self.assertFalse(relation.intervals[0].matched)
        face, = relation.outside_owner_turn_faces
        self.assertEqual((face.owner_turn_id, face.opening_stage), (None, 'starting'))

    def test_pre_first_paid_body_wait_has_no_fabricated_owner_interval(self):
        fixture = opening_fixtures.OpeningPaidPhaseTests(); fixture.setUp()
        game = fixture.opening(payload_choice=True)
        query = PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE)
        before = self.relation(game, query=query)
        self.assertEqual(before.intervals, ())
        self.assertEqual(len(before.outside_owner_turn_faces), 1)
        fixture.choose(game)
        after = self.relation(game, query=query)
        self.assertEqual(after.outside_owner_turn_faces, before.outside_owner_turn_faces)
        self.assertFalse(after.intervals[0].matched)

    def test_unpublished_actual_start_wait_preserves_pending_original_interval(self):
        fixture = startup_fixtures.StartExpiryIntervalTests(); fixture.setUp()
        game = fixture.startup_paid_game('choice')
        relation = self.relation(game)
        self.assertEqual([r.owner_turn.owner_index for r in relation.intervals], [1, 2])
        current = relation.intervals[-1].owner_turn
        self.assertEqual((current.origin, current.closed, current.publication_event), ('actual', False, None))
        fixture.choose(game)
        relation = self.relation(game)
        self.assertIsNone(relation.intervals[-1].owner_turn.publication_event)
        self.assertIsNotNone(game.state.pending_choice)
        fixture.choose(game)
        self.assertIsNotNone(self.relation(game).intervals[-1].owner_turn.publication_event)

    def test_startup_terminal_interruption_keeps_open_actual_interval(self):
        fixture = startup_fixtures.StartExpiryIntervalTests(); fixture.setUp()
        from hs_sim.engine.effects import Damage
        game = fixture.startup_game(lambda c: [Damage(c.state.players[2].hero_id, 50)])
        relation = self.relation(game)
        self.assertEqual(len(relation.intervals), 2)
        current = relation.intervals[-1].owner_turn
        self.assertFalse(current.closed)
        self.assertIsNone(current.publication_event)
        self.assertIsNotNone(current.start_interruption)

    def test_midturn_terminal_spell_keeps_open_interval_and_frozen_true_face(self):
        game = self.game(('terminal',)); self.play(game, 'terminal')
        relation = self.relation(game, query=PlayedTypeQuery(CardType.SPELL, spell_school=SpellSchool.ARCANE))
        self.assertEqual(game.state.status, 'finished')
        self.assertFalse(relation.intervals[0].owner_turn.closed)
        self.assertTrue(relation.intervals[0].matched)

    def test_configured_natural_end_draw_retains_closed_interval_without_new_one(self):
        game = self.game((NATIVE,), rules=Ruleset(draw_after_turn=1))
        self.play(game, NATIVE); self.end(game)
        relation = self.relation(game)
        self.assertEqual((game.state.status, len(relation.intervals)), ('draw', 1))
        self.assertTrue(relation.intervals[0].owner_turn.closed)
        self.assertTrue(relation.intervals[0].matched)

    def test_complete_relation_snapshot_clone_independent_registry_replay(self):
        game = self.game((NATIVE, 'empty')); self.play(game, NATIVE)
        self.next_own(game); self.play(game, 'empty')
        self.portable_relation(game)

    def waiting_native(self, event):
        def hold(c):
            if c.play is None or c.play.card_id != NATIVE: return []
            return [RequestChoice(c.player_id, (ChoiceOption('ok', 'continue', ()),
                ChoiceOption('fault', 'rollback', (InvokeBehavior('failure', c.source_id, c.player_id),))), source_id=c.source_id)]
        self.r.register_behavior('hold-native', hold)
        self.r.register_card(CardDefinition('native-watcher', 'native-watcher', CardType.MINION,
            health=8, metadata=fixtures.metadata(), triggers=(TriggerSpec(event, 'hold-native'),)))
        game = self.game((NATIVE,), board=('native-watcher',)); self.play(game, NATIVE)
        return game

    def test_committed_wait_retains_face_and_resumes_without_new_submission(self):
        game = self.waiting_native('card_committed')
        before = self.relation(game)
        self.assertTrue(before.intervals[0].matched)
        self.assertFalse(game.state.play_history[0].completed)
        clones = self.portable_relation(game)
        self.choose(game)
        for clone in clones: self.choose(clone); self.assertEqual(clone.snapshot(), game.snapshot())
        self.assertEqual(self.relation(game), before)
        self.assertEqual(len(game.state.play_history), 1)

    def test_completed_wait_retains_original_face_and_payment(self):
        game = self.waiting_native('card_played')
        self.assertTrue(game.state.play_history[0].completed)
        before = self.relation(game); self.portable_relation(game); self.choose(game)
        self.assertEqual(self.relation(game), before)
        play = game.state.play_history[0]
        self.assertEqual((play.cost, play.submitted_cost.quote.amount), (3, 3))

    def test_failed_selection_restores_pending_relation_and_private_mapping(self):
        game = self.waiting_native('card_committed')
        before, relation = game.snapshot(), self.relation(game)
        with self.assertRaises(ResolutionError): self.choose(game, 'fault')
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(self.relation(game), relation)
        self.choose(game)
        self.assertEqual(self.relation(game), relation)

    def test_illegal_public_action_does_not_add_a_query_face(self):
        game = self.game((NATIVE,)); before = self.relation(game)
        source = game.state.players[1].hand[0]
        with self.assertRaises(IllegalAction): game.apply(fixtures.PlayCard(2, source, position=0))
        self.assertEqual(self.relation(game), before)

    def test_query_does_not_mutate_state_rng_allocations_or_events(self):
        game = self.game((NATIVE, 'empty')); self.play(game, NATIVE); self.play(game, 'empty')
        before, state = game.snapshot(), game.state
        state_before = deepcopy(state)
        for _ in range(3): query_owner_turn_history(state, 1, ELEMENTAL)
        self.assertEqual(state, state_before)
        self.assertEqual(game.snapshot(), before)

    def test_typed_relation_and_original_face_are_immutable(self):
        game = self.game((NATIVE,)); self.play(game, NATIVE); relation = self.relation(game)
        self.assertIs(type(relation), OwnerTurnTypeHistory)
        self.assertIs(type(relation.intervals[0]), OwnerTurnTypeMatch)
        for obj, name, value in ((relation, 'player_id', 2), (relation.intervals[0], 'matched', False),
                (relation.intervals[0].rows[0].face, 'card_id', 'empty')):
            with self.assertRaises(FrozenInstanceError): setattr(obj, name, value)

    def test_typed_relation_rejects_missing_middle_reorder_and_wrong_false_row(self):
        game = self.game((NATIVE,)); self.play(game, NATIVE); self.next_own(game); self.next_own(game)
        relation = self.relation(game)
        bad_first = replace(relation.intervals[0], rows=(OwnerTurnMatchRow(relation.intervals[0].rows[0].face, False),), matched=False)
        for intervals in ((relation.intervals[0], relation.intervals[2]), tuple(reversed(relation.intervals)),
                (bad_first, *relation.intervals[1:])):
            with self.assertRaises(ValueError): replace(relation, intervals=intervals)

    def test_typed_relation_rejects_loose_fields_wrong_query_and_own_face_outside(self):
        game = self.game((NATIVE,)); self.play(game, NATIVE); relation = self.relation(game)
        face = relation.intervals[0].rows[0].face
        for changes in ({'player_id': True}, {'intervals': list(relation.intervals)},
                {'outside_owner_turn_faces': [face]}, {'outside_owner_turn_faces': (face,)},
                {'profile_id': 'invented'}, {'query': PlayedTypeQuery(CardType.MINION, ('beast',))}):
            with self.assertRaises(ValueError): replace(relation, **changes)
        with self.assertRaises(ValueError): replace(relation.intervals[0], matched=1)

    def test_public_query_rejects_wrong_player_state_and_query_types(self):
        game = self.game()
        for player in (True, 0, 3, '1'):
            with self.assertRaises(ValueError): query_owner_turn_history(game.state, player, ELEMENTAL)
        with self.assertRaises(ValueError): query_owner_turn_history(game.state, 1, {})
        with self.assertRaises(ValueError): query_owner_turn_history(None, 1, ELEMENTAL)

    def test_query_details_do_not_enter_player_views_actions_events_or_saved_wire(self):
        game = self.game((NATIVE,)); self.play(game, NATIVE); self.relation(game)
        values = [game.snapshot(), game.observe(1), game.observe(2),
            game.for_player(1).legal_actions(), game.for_player(2).legal_actions()]
        for value in values:
            text = json.dumps(value)
            self.assertNotIn('OwnerTurnTypeHistory', text)
            self.assertNotIn('outside_owner_turn_faces', text)
        for player in (1, 2):
            self.assertNotIn('owner_turn_history', json.dumps(game.observe(player)))
            self.assertNotIn('play_history', json.dumps(game.observe(player)))
        self.assertEqual((game.snapshot()['schema_version'], game.ruleset.id, game.mechanics.version),
            (265, 'prototype-v302', CORE_EFFECTS_VERSION))


if __name__ == '__main__':
    unittest.main()
