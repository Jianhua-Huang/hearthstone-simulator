"""Real Game persistence tests for the U65 state/codec integration phase.

StoreLedgerFixture is an explicit trusted data-layer test adapter. It settles
the immutable component ledger without executing any historical card body;
these tests cannot prove the pending replay interpreter or Finish obligations.
"""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from dataclasses import dataclass, FrozenInstanceError
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import CardDefinition, CardType, EndTurn, Game, PlayCard, PlayerSetup, Registry, Scenario, SelectChoice
from hs_sim.engine.effects import ChoiceOption, Damage, Effect, GainArmor, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CardClass, CardMetadata, Rarity
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.whole_card_history import (
    HistorySelectionPolicy, WholeCardHistoryQuery, capture_history_frontier, select_history_occurrences)
from hs_sim.engine.whole_card_replay_ledger import (
    ReplayAncestorPolicy, ReplayRootStatus, WholeCardReplayLedger,
    accept_replay_root, begin_replay_child, finish_replay_child, finish_replay_root)


@dataclass(frozen=True)
class StoreLedgerFixture(Effect):
    player_id: int
    source_id: int
    settle: bool = True


def store_fixture(r, effect):
    query = WholeCardHistoryQuery(effect.player_id, len(r.state.play_history) + 1)
    frontier = capture_history_frontier(r.state, r.registry, query)
    selection = select_history_occurrences(frontier, HistorySelectionPolicy(), r.game._rng)
    ledger, root_id = accept_replay_root(r.state.whole_card_replay_ledger,
        r.state, r.registry, selection, effect.player_id, effect.source_id,
        ReplayAncestorPolicy.ALLOW, shared_rng_state=r.game._rng.getstate())
    if effect.settle:
        # A trusted persistence fixture, not actual root/body/child execution.
        for _ in selection.selected_ids:
            ledger, child_id = begin_replay_child(ledger, root_id)
            ledger = finish_replay_child(ledger, child_id)
        ledger = finish_replay_root(ledger, root_id)
    r.state.whole_card_replay_ledger = ledger
    return ()


def make_mechanics():
    value = default_mechanics('whole-card-state-fixtures-v1')
    value.register(StoreLedgerFixture, store_fixture)
    return value


def make_registry():
    registry = Registry('whole-card-state-fixtures-v1')
    meta = CardMetadata(False, (CardClass.MAGE,), Rarity.COMMON)
    registry.register_card(CardDefinition('hero', 'Fixture hero', CardType.HERO, health=30, metadata=meta))
    registry.register_card(CardDefinition('plain', 'Fixture minion', CardType.MINION, health=2))
    registry.register_behavior('mark', lambda c: (GainArmor(c.player_id, 1),))
    for card in ('mage_spell', 'mage_spell_alternate'):
        registry.register_card(CardDefinition(card, card, CardType.SPELL, on_play='mark', metadata=meta))
    registry.register_behavior('store', lambda c: (StoreLedgerFixture(c.player_id, c.source_id),))
    registry.register_behavior('wait', lambda c: (StoreLedgerFixture(c.player_id, c.source_id),
        RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', (GainArmor(c.player_id, 2),)),), source_id=c.source_id)))
    registry.register_behavior('unsupported-running', lambda c: (StoreLedgerFixture(c.player_id, c.source_id, False),))
    registry.register_behavior('unsupported-running-wait', lambda c: (StoreLedgerFixture(c.player_id, c.source_id, False),
        RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', ()),), source_id=c.source_id)))
    registry.register_behavior('lethal', lambda c: (Damage(c.state.players[2].hero_id, 100, c.source_id),))
    for card in ('store', 'wait', 'unsupported-running', 'unsupported-running-wait', 'lethal'):
        registry.register_card(CardDefinition(card, card, CardType.SPELL, on_play=card, metadata=meta))
    return registry


class WholeCardStateFoundationTests(unittest.TestCase):
    def game(self, last='store'):
        return Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=('mage_spell', 'mage_spell', last, 'lethal'),
                deck=('plain',) * 6, mana=10, max_mana=10),
            PlayerSetup('hero', deck=('plain',) * 6, mana=10, max_mana=10)), seed=230),
            make_registry(), mechanics=make_mechanics())

    def play(self, game, card):
        state = game.state
        source = next(i for i in state.players[1].hand if state.entities[i].card_id == card)
        return game.apply(PlayCard(1, source))

    def populated(self, last='store'):
        game = self.game(last)
        for card in ('mage_spell', 'mage_spell', last):
            self.play(game, card)
        return game

    def portable(self, game, label):
        snapshot = json.loads(json.dumps(game.snapshot()))
        payload = build_replay(game)
        branches = (Game.from_snapshot(snapshot, make_registry(), make_mechanics()),
                    game.clone(), replay(payload, make_registry(), make_mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            for viewer in (1, 2):
                self.assertEqual(branch.observe(viewer), game.observe(viewer))
                self.assertEqual(branch.player_events(viewer), game.player_events(viewer))
                self.assertEqual(branch.for_player(viewer).legal_actions(), game.for_player(viewer).legal_actions())
        directory = os.environ.get('WHOLE_CARD_STATE_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(),
                    'snapshot': snapshot, 'replay': payload,
                    'whole_card_body_executed_by_fixture': False}, f, ensure_ascii=False, indent=2)
                f.write('\n')
        return branches

    def invalid(self, mutate):
        game = self.populated()
        before = game.snapshot()
        changed = deepcopy(before)
        mutate(changed['state']['whole_card_replay_ledger'])
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(changed, make_registry(), make_mechanics())
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'valid-origin-for-negative-input')

    def test_default_state_has_a_concrete_empty_ledger_and_new_strict_schema(self):
        game = self.game()
        self.assertIs(type(game.state.whole_card_replay_ledger), WholeCardReplayLedger)
        self.assertEqual(game.state.whole_card_replay_ledger, WholeCardReplayLedger())
        self.assertEqual(game.snapshot()['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(game.ruleset.id, 'prototype-v302')
        self.portable(game, 'empty')

    def test_duplicate_real_submissions_keep_distinct_stored_child_identities(self):
        game = self.populated()
        ledger = game.state.whole_card_replay_ledger
        self.assertEqual(len(ledger.roots), 1)
        self.assertEqual(ledger.roots[0].status, ReplayRootStatus.FINISHED)
        self.assertEqual(ledger.roots[0].selection.selected_ids, (1, 2))
        self.assertEqual(tuple(c.id for c in ledger.children), (1, 2))
        self.assertEqual(tuple(c.occurrence_id for c in ledger.children), (1, 2))
        self.assertEqual(tuple(c.card_id for c in ledger.children), ('mage_spell', 'mage_spell'))
        self.portable(game, 'duplicates')

    def test_state_reads_are_detached_and_the_embedded_ledger_is_immutable(self):
        game = self.populated()
        before = game.snapshot()
        view = game.state
        with self.assertRaises(FrozenInstanceError):
            view.whole_card_replay_ledger.stack = (1,)
        view.whole_card_replay_ledger = WholeCardReplayLedger()
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'detached-state')

    def test_later_real_owner_turns_keep_the_accepted_prefix_and_ledger_unchanged(self):
        game = self.populated()
        original = game.state.whole_card_replay_ledger
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertEqual(game.state.whole_card_replay_ledger, original)
        self.assertEqual(len(game.state.owner_turn_history), 3)
        self.portable(game, 'later-owner-turns')

    def test_pending_real_choice_roundtrips_live_and_captured_ledger_then_resumes(self):
        game = self.populated('wait')
        branches = (game, *self.portable(game, 'waiting'))
        for branch in branches:
            choice = branch.state.pending_choice
            branch.apply(SelectChoice(choice.player_id, choice.id, ('continue',)))
        expected = branches[0].snapshot()
        for branch in branches:
            self.assertEqual(branch.snapshot(), expected)
        self.portable(game, 'resumed')

    def test_later_genuine_terminal_keeps_already_settled_history_without_false_interruption(self):
        game = self.populated()
        original = game.state.whole_card_replay_ledger
        self.play(game, 'lethal')
        self.assertEqual(game.state.status, 'finished')
        self.assertEqual(game.state.whole_card_replay_ledger, original)
        self.portable(game, 'terminal')

    def test_running_fixture_without_runtime_finish_proof_rejects_and_rolls_back(self):
        game = self.game('unsupported-running')
        self.play(game, 'mage_spell')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'queue/Finish integration is not installed'):
            self.play(game, 'unsupported-running')
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'unsupported-running-rollback')

    def test_waiting_does_not_make_an_unowned_running_root_valid(self):
        game = self.game('unsupported-running-wait')
        self.play(game, 'mage_spell')
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'queue/Finish integration is not installed'):
            self.play(game, 'unsupported-running-wait')
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'unsupported-waiting-rollback')

    def test_player_ports_never_expose_ledger_selection_or_original_rng(self):
        game = self.populated('wait')
        for viewer in (1, 2):
            p = game.for_player(viewer)
            encoded = json.dumps({'view': p.observe(), 'events': p.events(), 'actions': p.legal_actions()})
            for private in ('whole_card_replay_ledger', 'selected_ids', 'rng_before', 'ancestor_policy'):
                self.assertNotIn(private, encoded)
        self.portable(game, 'privacy')

    def test_schema111_is_rejected_instead_of_defaulting_a_missing_new_field(self):
        game = self.populated()
        snapshot = game.snapshot()
        snapshot['schema_version'] = 111
        del snapshot['state']['whole_card_replay_ledger']
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, make_registry(), make_mechanics())

    def test_schema112_requires_the_explicit_ledger_field_even_when_empty(self):
        game = self.game()
        snapshot = game.snapshot()
        del snapshot['state']['whole_card_replay_ledger']
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(snapshot, make_registry(), make_mechanics())

    def test_codec_rejects_unknown_ledger_field(self):
        self.invalid(lambda d: d.update(unknown=1))

    def test_codec_rejects_trimmed_child_history(self):
        self.invalid(lambda d: d['children'].pop())

    def test_true_and_false_accepted_rows_cannot_be_trimmed(self):
        self.invalid(lambda d: d['roots'][0]['selection']['frontier']['rows'].pop())

    def test_registry_valid_alternate_face_cannot_replace_a_real_submitted_prefix(self):
        def mutate(d):
            d['roots'][0]['selection']['frontier']['rows'][0]['occurrence']['face']['card_id'] = 'mage_spell_alternate'
            d['children'][0]['card_id'] = 'mage_spell_alternate'
        self.invalid(mutate)

    def test_accepted_future_action_clock_is_rejected(self):
        def mutate(d):
            d['roots'][0]['accepted_action'] += 1
            d['roots'][0]['selection']['frontier']['captured_action'] += 1
        self.invalid(mutate)

    def test_accepted_future_history_size_is_rejected(self):
        self.invalid(lambda d: d['roots'][0]['selection']['frontier'].__setitem__('history_size', 999))

    def test_selected_rng_receipt_is_checked_after_persistence(self):
        def mutate(d):
            d['roots'][0]['selection']['rng_after'][1][0] ^= 1
        self.invalid(mutate)
