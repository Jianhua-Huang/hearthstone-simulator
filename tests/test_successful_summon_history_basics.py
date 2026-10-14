"""Universal successful entry facts; fixtures use original public operations.

No combination mechanism or card-specific summon executor is introduced.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
import unittest

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    ChangeMinionTribes, EndTurn, Game, Keyword, PlayCard, PlayerSetup, Rarity,
    Registry, ResolutionError, RewindSpec, Scenario, SelectChoice, SnapshotError,
    SuccessfulSummonRecord, TriggerSpec, TribeChangeSpec, TribeState, Zone,
    summoned_minions, summon_count)
from hs_sim.engine.colossal import SummonStoredCard
from hs_sim.engine.continuations import FrameCodec
from hs_sim.engine.effects import (AddToHand, ChangeControl, ChoiceOption, Destroy,
    InvokeBehavior, RequestChoice, ReturnToHand, Summon, Transform)
from hs_sim.engine.model import validate_invariants
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.successful_summons import validate_state
from hs_sim.engine.zones import CardReference
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


def registry():
    r = Registry('successful-summon-basics-v1')
    r.register_card(CardDefinition('hero', 'Fixture hero', CardType.HERO, health=30))
    for name, tribes in (('totem', ('totem',)), ('beast', ('beast',)), ('all', ('all',)),
            ('empty', ()), ('unknown', None)):
        r.register_card(CardDefinition(name, name, CardType.MINION, attack=1, health=3,
            metadata=CardMetadata(False, (CardClass.NEUTRAL,), Rarity.COMMON, tribes=tribes)))

    def first(c):
        return c.state.players[c.player_id].board[0]

    def stored(c, player=None):
        owner = c.player_id if player is None else player
        entity = c.state.entities[c.state.players[owner].deck[0]]
        return (SummonStoredCard(CardReference.capture(entity), c.player_id),)

    def changed_hand(c):
        entity = next(c.state.entities[i] for i in c.state.players[c.player_id].hand
            if c.state.entities[i].card_id == 'totem')
        return (ChangeMinionTribes(CardReference.capture(entity),
            TribeChangeSpec('set', ('beast',)), c.source_id),)

    scripts = {
        'make': lambda c: (Summon(c.player_id, 'totem'),),
        'two': lambda c: (Summon(c.player_id, 'totem'), Summon(c.player_id, 'beast')),
        'enemy': lambda c: (Summon(3-c.player_id, 'totem'),),
        'unknown.make': lambda c: (Summon(c.player_id, 'unknown'),),
        'enemy.unknown': lambda c: (Summon(3-c.player_id, 'unknown'),),
        'kill': lambda c: (Destroy(first(c), c.source_id),),
        'bounce': lambda c: (ReturnToHand(first(c)),),
        'shape': lambda c: (Transform(first(c), 'beast'),),
        'control': lambda c: (ChangeControl(first(c), 3-c.player_id),),
        'acquire': lambda c: (AddToHand(c.player_id, 'totem'),),
        'recruit': stored,
        'cross.recruit': lambda c: stored(c, 3-c.player_id),
        'change.hand': changed_hand,
        'wait': lambda c: (Summon(c.player_id, 'totem'), RequestChoice(c.player_id, (
            ChoiceOption('next', 'Next entry', (Summon(c.player_id, 'beast'),)),
            ChoiceOption('fault', 'Rollback probe', (InvokeBehavior('fail', c.source_id, c.player_id),)),
        ), c.source_id)),
        'fail': lambda c: (Summon(c.player_id, 'totem'),
            AddToHand(c.player_id, 'unsupported.summon.fixture')),
    }
    for name, fn in scripts.items():
        r.register_behavior(name, fn)
        r.register_card(CardDefinition(name, name, CardType.SPELL, on_play=name))
    r.register_behavior('retry', lambda c: (Summon(c.player_id, 'totem'),))
    r.register_card(CardDefinition('retry', 'Original Rewind', CardType.SPELL,
        on_play='retry', keywords=(Keyword.REWIND,), rewind=RewindSpec()))

    def inspect(c):
        row = summoned_minions(c.state, c.event.player_id)[-1]
        if (row.entity_id, row.event_sequence) != (c.event.target_id, c.event.sequence):
            raise ResolutionError('First original listener missed the committed entry')
        return (RequestChoice(c.player_id, (
            ChoiceOption('done', 'Captured fact', ()),
        ), c.source_id),)

    r.register_behavior('inspect', inspect)
    r.register_card(CardDefinition('watch', 'Original listener', CardType.MINION, health=3,
        triggers=(TriggerSpec('minion_summoned', 'inspect'),)))
    return r


def rehash(saved):
    saved['events_hash'] = canonical_hash(saved['events'])
    saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return saved


class SuccessfulSummonHistoryTests(unittest.TestCase):
    def game(self, hand=(), *, enemy_hand=(), board=(), enemy_board=(),
            deck=('empty',)*6, enemy_deck=('empty',)*6):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=hand, board=board, deck=deck, mana=10, max_mana=10),
            PlayerSetup('hero', hand=enemy_hand, board=enemy_board, deck=enemy_deck,
                mana=10, max_mana=10)), seed=43), registry())

    def play(self, g, name):
        player = g.state.active_player
        source = next(i for i in g.state.players[player].hand if g.state.entities[i].card_id == name)
        g.apply(PlayCard(player, source))
        return source

    def rows(self, g, player=1, **kwargs):
        return summoned_minions(g.state, player, **kwargs)

    def count(self, g, player=1, **kwargs):
        return summon_count(g.state, player, **kwargs)

    def check(self, g):
        saved = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(Game.from_snapshot(saved, registry()).snapshot(), saved)
        self.assertEqual(g.clone().snapshot(), saved)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), saved)
        codec = FrameCodec(g.mechanics, registry())
        self.assertEqual(codec.decode(codec.encode(g.state)), g.state)

    def reject(self, g, mutate):
        saved = g.snapshot()
        mutate(saved)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(rehash(saved), registry())

    def test_initial_boards_hands_and_decks_do_not_invent_past_summons(self):
        g = self.game(('totem',), board=('totem',), enemy_board=('all',))
        self.assertEqual((self.count(g), self.count(g, 2), g.state.next_successful_summon_id), (0, 0, 1))
        self.check(g)

    def test_ordinary_minion_play_publishes_exactly_one_original_fact(self):
        g = self.game(('totem',)); entity_id = self.play(g, 'totem')
        row, = self.rows(g)
        self.assertIs(type(row), SuccessfulSummonRecord)
        self.assertEqual((row.id, row.entity_id, row.card_id, row.player_id,
            row.active_player, row.turn, row.action), (1, entity_id, 'totem', 1, 1, 1, 1))
        self.assertEqual(row.tribes, TribeState(('totem',)))
        self.assertEqual(g.state.card_summon_history, [])
        self.check(g)

    def test_plain_effect_summons_are_complete_without_producer_roots(self):
        g = self.game(('two',)); self.play(g, 'two')
        self.assertEqual([r.card_id for r in self.rows(g)], ['totem', 'beast'])
        self.assertEqual([r.id for r in self.rows(g)], [1, 2])
        self.assertEqual((self.count(g), self.count(g, tribes=('totem',))), (2, 1))
        self.assertEqual(g.state.card_summon_history, [])
        self.assertEqual(len([e for e in g.events if e.kind == 'minion_summoned']), 2)
        self.check(g)

    def test_spell_play_does_not_count_as_a_minion_entry(self):
        g = self.game(('acquire',)); self.play(g, 'acquire')
        self.assertEqual((self.count(g), len(g.state.play_history)), (0, 1))
        self.assertEqual(g.state.players[1].board, [])
        self.check(g)

    def test_full_board_plain_attempt_does_not_count_or_allocate(self):
        g = self.game(('two',), board=('empty',)*7); before = g.state.next_entity_id
        self.play(g, 'two')
        self.assertEqual((self.count(g), g.state.next_entity_id), (0, before))
        self.assertEqual(len([e for e in g.events if e.kind == 'summon_failed']), 2)
        self.check(g)

    def test_failed_stored_entry_preserves_deck_and_no_history(self):
        g = self.game(('recruit',), board=('empty',)*7, deck=('totem',))
        before = g.state.players[1].deck
        self.play(g, 'recruit')
        self.assertEqual(g.state.players[1].deck, before)
        self.assertEqual(self.rows(g), ())
        self.check(g)

    def test_successful_stored_entry_records_original_physical_card(self):
        g = self.game(('recruit',), deck=('totem',)); original = g.state.players[1].deck[0]
        self.play(g, 'recruit'); row, = self.rows(g)
        self.assertEqual((row.entity_id, row.minion.owner, row.minion.controller), (original, 1, 1))
        self.assertEqual((self.count(g, tribes=('totem',)), g.state.players[1].deck), (1, []))
        self.check(g)

    def test_receiver_is_distinct_from_active_player(self):
        g = self.game(('enemy',)); self.play(g, 'enemy')
        row, = self.rows(g, 2)
        self.assertEqual((row.player_id, row.active_player, row.minion.owner, row.minion.controller), (2, 1, 2, 2))
        self.assertEqual((self.count(g), self.count(g, 2)), (0, 1))
        self.check(g)

    def test_cross_player_stored_owner_is_preserved(self):
        g = self.game(('cross.recruit',), enemy_deck=('totem',))
        original = g.state.players[2].deck[0]; self.play(g, 'cross.recruit')
        row, = self.rows(g)
        self.assertEqual((row.entity_id, row.player_id, row.minion.owner, row.minion.controller), (original, 1, 2, 1))
        self.check(g)

    def test_death_does_not_erase_the_original_success(self):
        g = self.game(('totem', 'kill')); self.play(g, 'totem'); before = self.rows(g)
        self.play(g, 'kill')
        self.assertEqual((self.rows(g), g.state.players[1].board), (before, []))
        self.assertEqual(g.state.entities[before[0].entity_id].zone, Zone.GRAVEYARD)
        self.check(g)

    def test_bounce_retains_original_board_fact(self):
        g = self.game(('totem', 'bounce')); self.play(g, 'totem'); before = self.rows(g)
        self.play(g, 'bounce')
        self.assertEqual(self.rows(g), before)
        self.assertEqual(g.state.entities[before[0].entity_id].zone, Zone.HAND)
        self.check(g)

    def test_replaying_same_physical_minion_is_a_second_entry(self):
        g = self.game(('totem', 'bounce')); original = self.play(g, 'totem')
        self.play(g, 'bounce'); self.assertEqual(self.play(g, 'totem'), original)
        first, second = self.rows(g)
        self.assertEqual((first.entity_id, second.entity_id, self.count(g)), (original, original, 2))
        self.assertLess(first.minion.zone_epoch, second.minion.zone_epoch)
        self.assertLess(first.minion.entered_order, second.minion.entered_order)
        self.check(g)

    def test_transform_is_not_a_summon_and_cannot_reclassify_the_past(self):
        g = self.game(('totem', 'shape')); self.play(g, 'totem'); before = self.rows(g)
        self.play(g, 'shape')
        self.assertEqual(self.rows(g), before)
        self.assertEqual(g.state.entities[before[0].entity_id].card_id, 'beast')
        self.assertEqual((self.count(g, tribes=('totem',)), self.count(g, tribes=('beast',))), (1, 0))
        self.check(g)

    def test_control_transfer_does_not_change_original_summoner(self):
        g = self.game(('totem', 'control')); self.play(g, 'totem'); before = self.rows(g)
        self.play(g, 'control')
        self.assertEqual((self.rows(g), self.count(g, 2)), (before, 0))
        self.assertEqual(g.state.entities[before[0].entity_id].controller, 2)
        self.check(g)

    def test_acquiring_a_consumer_later_does_not_reset_past_facts(self):
        g = self.game(('make', 'acquire')); self.play(g, 'make'); before = self.rows(g)
        self.play(g, 'acquire')
        self.assertEqual(self.rows(g), before)
        self.assertEqual(self.count(g), 1)
        self.check(g)

    def test_turn_query_is_global_turn_and_not_current_board_size(self):
        g = self.game(('make',), enemy_hand=('make',)); self.play(g, 'make')
        g.apply(EndTurn(1)); self.play(g, 'make')
        self.assertEqual((self.count(g), self.count(g, 2)), (1, 1))
        self.assertEqual((self.count(g, turn=1), self.count(g, turn=2), self.count(g, 2, turn=2)), (1, 0, 1))
        self.assertEqual((self.rows(g, 2)[0].active_player, self.rows(g, 2)[0].turn), (2, 2))
        self.check(g)

    def test_all_tribes_matches_without_inventing_a_finite_universe(self):
        g = self.game(('all',)); self.play(g, 'all')
        self.assertEqual(self.count(g, tribes=('totem',)), 1)
        self.assertEqual(self.count(g, tribes=('future.nonempty.tribe',)), 1)
        self.assertEqual(self.count(g, tribes=('totem', 'beast')), 1)
        self.check(g)

    def test_known_empty_tribes_is_a_nonmatch(self):
        g = self.game(('empty',)); self.play(g, 'empty')
        self.assertEqual((self.count(g), self.count(g, tribes=('totem',))), (1, 0))
        self.assertEqual(self.rows(g)[0].tribes, TribeState(()))
        self.check(g)

    def test_unknown_tribes_are_counted_plainly_and_filtered_query_errors(self):
        g = self.game(('unknown',)); self.play(g, 'unknown')
        self.assertEqual(self.count(g), 1)
        self.assertIsNone(self.rows(g)[0].tribes)
        for basis in ('printed', 'current'):
            with self.subTest(basis=basis), self.assertRaises(UnsupportedDefinitionError):
                self.count(g, tribes=('totem',), basis=basis)
        self.check(g)

    def test_opponent_unknown_tribes_do_not_poison_selected_player_query(self):
        g = self.game(('totem', 'enemy.unknown')); self.play(g, 'totem'); self.play(g, 'enemy.unknown')
        self.assertEqual(self.count(g, tribes=('totem',)), 1)
        with self.assertRaises(UnsupportedDefinitionError): self.count(g, 2, tribes=('totem',))
        self.check(g)

    def test_outside_selected_turn_unknown_facts_are_preserved_but_not_matched(self):
        g = self.game(('unknown', 'totem')); self.play(g, 'unknown')
        g.apply(EndTurn(1)); g.apply(EndTurn(2)); self.play(g, 'totem')
        self.assertEqual(self.count(g, tribes=('totem',), turn=3), 1)
        with self.assertRaises(UnsupportedDefinitionError): self.count(g, tribes=('totem',))
        self.check(g)

    def test_original_current_and_printed_tribes_are_separate_frozen_operands(self):
        g = self.game(('change.hand', 'totem', 'bounce')); self.play(g, 'change.hand')
        self.play(g, 'totem'); row, = self.rows(g)
        self.assertEqual((row.printed_tribes, row.tribes), (TribeState(('totem',)), TribeState(('beast',))))
        self.assertEqual(row.tribe_changes, (TribeChangeSpec('set', ('beast',)),))
        self.assertEqual((self.count(g, tribes=('totem',)),
            self.count(g, tribes=('totem',), basis='printed')), (0, 1))
        self.play(g, 'bounce')
        self.assertEqual(self.rows(g), (row,))
        self.check(g)

    def test_first_original_listener_captures_the_complete_committed_fact(self):
        g = self.game(('make',), board=('watch',)); self.play(g, 'make')
        self.assertEqual(self.count(g), 1)
        self.assertIsNotNone(g.state.pending_choice)
        self.check(g)
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('done',)))
        self.assertEqual(self.count(g), 1)
        self.check(g)

    def test_waiting_restore_clone_replay_and_resume_keep_same_prefix(self):
        g = self.game(('wait',)); self.play(g, 'wait'); self.assertEqual(self.count(g), 1)
        self.check(g)
        saved = g.snapshot()
        copies = (Game.from_snapshot(saved, registry()), g.clone(), replay(build_replay(g), registry()))
        action = SelectChoice(1, g.state.pending_choice.id, ('next',))
        g.apply(action)
        for other in copies:
            other.apply(action)
            self.assertEqual(other.snapshot(), g.snapshot())
        self.assertEqual([r.card_id for r in self.rows(g)], ['totem', 'beast'])
        self.check(g)

    def test_failed_action_rolls_back_event_fact_and_cursor(self):
        g = self.game(('fail',)); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'fail')
        self.assertEqual(g.snapshot(), before)
        self.assertEqual((self.count(g), g.state.next_successful_summon_id), (0, 1))

    def test_failed_selection_preserves_original_wait_and_allocations(self):
        g = self.game(('wait',)); self.play(g, 'wait'); before = g.snapshot()
        with self.assertRaises(ResolutionError):
            g.apply(SelectChoice(1, g.state.pending_choice.id, ('fault',)))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual(self.count(g), 1)
        self.check(g)

    def test_rewind_retires_attempted_suffix_instead_of_counting_it_twice(self):
        g = self.game(('totem', 'retry')); self.play(g, 'totem'); self.play(g, 'retry')
        self.assertEqual(self.count(g), 2); before = self.rows(g)
        self.check(g)
        g.apply(SelectChoice(1, g.state.pending_choice.id, ('retry',)))
        self.assertEqual((self.count(g), [r.id for r in self.rows(g)]), (2, [1, 2]))
        self.assertEqual(self.rows(g)[0], before[0])
        self.assertGreater(self.rows(g)[1].event_sequence, before[1].event_sequence)
        self.assertEqual(len([e for e in g.events if e.kind == 'minion_summoned']), 3)
        self.check(g)

    def test_query_types_are_strict_and_queries_are_pure(self):
        g = self.game(('totem',)); self.play(g, 'totem'); before = g.snapshot()
        for player in (True, 1.0, 0, 3):
            with self.subTest(player=player), self.assertRaises(ValueError): summon_count(g.state, player)
        for kwargs in ({'tribes': ['totem']}, {'tribes': ('totem', 'totem')},
                {'basis': True}, {'basis': 'active'}, {'turn': True}, {'turn': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): self.rows(g, **kwargs)
        for _ in range(3):
            self.assertEqual(self.count(g, tribes=('totem',)), 1)
            self.assertEqual(self.rows(g), tuple(g.state.successful_summon_history))
        self.assertEqual(g.snapshot(), before)

    def test_records_and_nested_physical_facts_are_immutable(self):
        g = self.game(('totem',)); self.play(g, 'totem'); row, = self.rows(g)
        with self.assertRaises(FrozenInstanceError): row.player_id = 2
        with self.assertRaises(FrozenInstanceError): row.minion.owner = 2
        with self.assertRaises(FrozenInstanceError): row.tribes.members = ('beast',)
        self.assertEqual(self.count(g), 1)

    def test_record_numeric_types_and_tribe_derivation_are_strict(self):
        g = self.game(('totem',)); self.play(g, 'totem'); row, = self.rows(g)
        for change in ({'id': True}, {'player_id': True}, {'action': 1.0},
                {'event_sequence': 0}, {'tribe_changes': []}, {'tribes': TribeState(('beast',))}):
            with self.subTest(change=change), self.assertRaises(ValueError): replace(row, **change)

    def test_all_tribe_exclusions_are_preserved_in_the_frozen_derivation(self):
        g = self.game(('all',)); self.play(g, 'all'); row, = self.rows(g)
        excluded = replace(row, tribe_changes=(TribeChangeSpec('remove', ('totem',)),),
            tribes=TribeState(('all',), ('totem',)))
        self.assertFalse(excluded.tribes.matches_any(('totem',)))
        self.assertTrue(excluded.tribes.matches_any(('beast',)))
        with self.assertRaises(ValueError): replace(excluded, tribes=TribeState(('all',)))

    def test_saved_history_cannot_be_omitted_even_with_recomputed_hashes(self):
        g = self.game(('totem',)); self.play(g, 'totem')
        self.reject(g, lambda s: s['state'].update(successful_summon_history=[], next_successful_summon_id=1))
        for field in ('successful_summon_history', 'next_successful_summon_id'):
            self.reject(g, lambda s, field=field: s['state'].pop(field))

    def test_saved_rows_cannot_change_original_identity_or_tribe_basis(self):
        g = self.game(('totem',)); self.play(g, 'totem')
        def row(s): return s['state']['successful_summon_history'][0]
        for field, value in (('id', True), ('turn', 2), ('event_sequence', 999), ('extra', 0)):
            self.reject(g, lambda s, field=field, value=value: row(s).__setitem__(field, value))
        for field, value in (('entity_id', 999), ('owner', 2), ('controller', 2),
                ('zone', 'hand'), ('next_entity_id', 999), ('zone_epoch', 999)):
            self.reject(g, lambda s, field=field, value=value: row(s)['minion'].__setitem__(field, value))
        self.reject(g, lambda s: row(s)['printed_tribes'].__setitem__('members', ['beast']))
        self.reject(g, lambda s: row(s)['tribes'].__setitem__('members', ['beast']))

    def test_duplicate_reordered_and_truncated_history_is_rejected(self):
        g = self.game(('two',)); self.play(g, 'two')
        self.reject(g, lambda s: s['state']['successful_summon_history'].reverse())
        self.reject(g, lambda s: s['state']['successful_summon_history'].pop())
        self.reject(g, lambda s: s['state'].__setitem__('next_successful_summon_id', True))
        bad = g.state; first = bad.successful_summon_history[0]
        bad.successful_summon_history.append(replace(first, id=3, event_sequence=100))
        bad.next_successful_summon_id = 4
        with self.assertRaises(ValueError): validate_state(bad, registry())

    def test_original_event_inventory_cannot_be_changed_or_omitted(self):
        g = self.game(('totem',)); self.play(g, 'totem')
        def event(s): return next(e for e in s['events'] if e['kind'] == 'minion_summoned')
        for field, value in (('source_id', True), ('target_id', 1), ('player_id', 2),
                ('amount', 1), ('kind', 'summon_failed')):
            self.reject(g, lambda s, field=field, value=value: event(s).__setitem__(field, value))

    def test_typed_state_requires_exact_immutable_record_types(self):
        g = self.game(('totem',)); self.play(g, 'totem')
        bad = g.state; bad.successful_summon_history[0] = {'id': 1}
        with self.assertRaises(ValueError): validate_invariants(bad, registry())
        codec = FrameCodec(g.mechanics, registry())
        with self.assertRaises(ValueError): codec.encode(bad)

    def test_schema_rejects_old_future_bool_and_old_mechanics(self):
        g = self.game(('totem',)); self.play(g, 'totem')
        self.assertEqual((g.ruleset.id, g.mechanics.version, g.snapshot()['schema_version']),
            ('prototype-v302', CORE_EFFECTS_VERSION, 265))
        for value in (1, 204, 217, True, 205.0):
            self.reject(g, lambda s, value=value: s.update(schema_version=value))
        self.reject(g, lambda s: s['ruleset'].update(id='prototype-v219'))
        self.reject(g, lambda s: s['mechanics_version'].update(version='core-effects-v213'))

    def test_player_views_and_action_envelopes_do_not_expose_private_history(self):
        g = self.game(('totem',)); self.play(g, 'totem'); before = g.snapshot()
        for player in (1, 2):
            for dto in (g.observe(player), g.for_player(player).observe(), g.for_player(player).legal_actions()):
                text = json.dumps(dto)
                self.assertNotIn('successful_summon_history', text)
                self.assertNotIn('next_successful_summon_id', text)
                self.assertNotIn('printed_tribes', text)
        event = next(e for e in g.events if e.kind == 'minion_summoned')
        self.assertEqual(event.data, ())
        self.assertEqual(g.snapshot(), before)
