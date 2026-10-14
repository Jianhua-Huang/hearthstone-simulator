"""Actual Game.apply whole-card spell bodies; no direct ledger settlement."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, Effect, GainArmor, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.model import CardClass, CardMetadata, Rarity, TargetSpec, Zone
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.rules import Ruleset
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import (HistorySelectionMode,
    HistorySelectionPolicy, WholeCardHistoryQuery)
from hs_sim.engine.whole_card_replay_ledger import ReplayChildStatus, ReplayRootStatus
from hs_sim.engine.whole_card_replays import ReplayWholeCards


@dataclass(frozen=True)
class DeliberateFailure(Effect):
    source_id: int


def make_mechanics():
    mechanics = default_mechanics('whole-card-spell-runtime-tests-v1')
    def fail(r, e): raise ResolutionError('deliberate runtime failure')
    mechanics.register(DeliberateFailure, fail)
    return mechanics


def make_registry():
    registry = Registry('whole-card-spell-runtime-tests-v1')
    meta = CardMetadata(False, (CardClass.MAGE,), Rarity.COMMON)
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, metadata=meta))
    registry.register_card(CardDefinition('plain', 'Minion', CardType.MINION, health=2))
    registry.register_behavior('mark', lambda c: (GainArmor(c.player_id, 1),))
    registry.register_behavior('wait', lambda c: (RequestChoice(c.player_id,
        (ChoiceOption('a', 'A', (GainArmor(c.player_id, 2),)),
         ChoiceOption('b', 'B', (GainArmor(c.player_id, 3),))), source_id=c.source_id),)
        if c.cast.origin == 'effect' else (GainArmor(c.player_id, 1),))
    registry.register_behavior('kill', lambda c: (Destroy(c.target_id),))
    registry.register_behavior('lethal', lambda c: (Damage(c.state.players[2].hero_id, 100, c.source_id),)
        if c.cast.origin == 'effect' else ())
    registry.register_behavior('fail', lambda c: (DeliberateFailure(c.source_id),)
        if c.cast.origin == 'effect' else ())
    def request(c, *, player=None, random_count=None, empty=False, kinds=(CardType.SPELL,)):
        policy = HistorySelectionPolicy() if random_count is None else HistorySelectionPolicy(
            HistorySelectionMode.RANDOM_COUNT, random_count, True)
        return (ReplayWholeCards(player or c.player_id, c.source_id,
            WholeCardHistoryQuery(c.player_id, 1 if empty else len(c.state.play_history) + 1, kinds=kinds),
            policy, choices='player'),)
    registry.register_behavior('nested', lambda c: request(c) if c.cast.origin == 'effect' else ())
    registry.register_behavior('rerun', request)
    registry.register_behavior('random', lambda c: request(c, random_count=6))
    registry.register_behavior('other', lambda c: request(c, player=2))
    registry.register_behavior('empty', lambda c: request(c, empty=True))
    registry.register_behavior('unsupported', lambda c: request(c, kinds=()))
    for name in ('mark', 'wait', 'lethal', 'fail', 'nested', 'rerun', 'random', 'other', 'empty', 'unsupported'):
        registry.register_card(CardDefinition(name, name, CardType.SPELL, cost=3 if name in
            ('rerun', 'random', 'other', 'empty', 'unsupported') else 0, on_play=name, metadata=meta))
    registry.register_card(CardDefinition('kill', 'Kill', CardType.SPELL, on_play='kill',
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy'), metadata=meta))
    return registry


class WholeCardSpellRuntimeTests(unittest.TestCase):
    def game(self, hand=('mark', 'mark', 'rerun'), **kwargs):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, deck=('plain',) * 6,
            mana=10, max_mana=10), PlayerSetup('hero', deck=('plain',) * 6, mana=10,
            max_mana=10, board=kwargs.pop('enemy_board', ()))), seed=231),
            make_registry(), mechanics=make_mechanics(), **kwargs)

    def play(self, game, name, target=None):
        source = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == name)
        return game.apply(PlayCard(1, source, target_id=target))

    def populated(self, names=('mark', 'mark', 'rerun')):
        game = self.game(names)
        for name in names: self.play(game, name)
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
        directory = os.environ.get('WHOLE_CARD_RUNTIME_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(),
                    'snapshot': snapshot, 'replay': payload, 'actual_whole_card_spell_runtime': True},
                    f, ensure_ascii=False, indent=2); f.write('\n')
        return branches

    def waiting(self, nested=False):
        return self.populated(('nested', 'wait', 'rerun') if nested else ('wait', 'rerun'))

    def settle(self, game):
        while game.state.pending_choice is not None:
            choice = game.state.pending_choice
            game.apply(SelectChoice(choice.player_id, choice.id, ('a',)))

    def negative(self, mutate, nested=False):
        game = self.waiting(nested); original = game.snapshot(); bad = deepcopy(original)
        mutate(bad)
        self.rehash(bad)
        with self.assertRaises(SnapshotError) as rejected: Game.from_snapshot(bad, make_registry(), make_mechanics())
        self.assertNotIn('digest mismatch', str(rejected.exception))
        self.assertEqual(game.snapshot(), original)
        self.portable(game, 'negative-input-valid-origin')

    @staticmethod
    def encoded_work(snapshot):
        return snapshot['resolution_frame']['fields']['continuation']['tuple']

    @staticmethod
    def rehash(snapshot):
        payload = {k: v for k, v in snapshot.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')}
        snapshot['state_hash'] = canonical_hash(payload)

    @staticmethod
    def named(work, name):
        return next(w for w in work if w.get('type', '').endswith('.' + name))

    def test_duplicate_paid_occurrences_execute_real_bodies_with_one_parent_payment(self):
        game = self.populated(); state = game.state; ledger = state.whole_card_replay_ledger
        self.assertEqual(state.entities[state.players[1].hero_id].armor, 4)
        self.assertEqual(state.players[1].mana, 7)
        self.assertEqual(len(state.play_history), 3)
        self.assertEqual(len(state.cast_history), 5)
        self.assertEqual(ledger.roots[0].selection.selected_ids, (1, 2))
        self.assertEqual(tuple(c.spell_cast_id for c in ledger.children), (4, 5))
        self.assertEqual(tuple(c.status for c in ledger.children), (ReplayChildStatus.FINISHED,) * 2)
        self.assertEqual(len({c.source_id for c in state.cast_history}), 5)
        self.assertTrue(all(c.origin == 'effect' and c.play_id is None for c in state.cast_history[3:]))
        self.assertEqual(sum(e.kind == 'card_committed' for e in game.events), 3)
        self.portable(game, 'duplicate-actual-bodies')

    def test_random_replacement_keeps_six_independent_physical_invocations(self):
        game = self.populated(('mark', 'mark', 'random')); state = game.state
        ledger = state.whole_card_replay_ledger
        self.assertEqual(len(ledger.roots[0].selection.selected_ids), 6)
        self.assertEqual(len(ledger.children), 6)
        self.assertEqual(len({c.spell_cast_id for c in ledger.children}), 6)
        self.assertEqual(state.entities[state.players[1].hero_id].armor, 8)
        self.portable(game, 'replacement')

    def test_empty_original_pool_finishes_without_rng_or_cast_attempt(self):
        game = self.game(('empty',)); before_rng = game.snapshot()['rng_state']
        self.play(game, 'empty'); ledger = game.state.whole_card_replay_ledger
        self.assertEqual(game.snapshot()['rng_state'], before_rng)
        self.assertEqual(ledger.roots[0].selection.selected_ids, ())
        self.assertEqual(ledger.children, ())
        self.assertEqual(ledger.roots[0].status, ReplayRootStatus.FINISHED)
        self.assertEqual(len(game.state.cast_history), 1)
        self.portable(game, 'empty')

    def test_executor_is_explicit_and_does_not_borrow_original_submission_owner(self):
        game = self.populated(('mark', 'other')); state = game.state
        cast = state.cast_history[-1]
        self.assertEqual(state.entities[state.players[1].hero_id].armor, 1)
        self.assertEqual(state.entities[state.players[2].hero_id].armor, 1)
        self.assertEqual(cast.player_id, 2)
        self.assertEqual(state.entities[cast.source_id].controller, 2)
        self.assertEqual(state.whole_card_replay_ledger.roots[0].selection.frontier.query.player_id, 1)
        self.portable(game, 'separate-executor')

    def test_no_legal_target_records_failed_attempt_and_continues_next_card(self):
        game = self.game(('kill', 'mark', 'rerun'), enemy_board=('plain',))
        target = game.state.players[2].board[0]
        self.play(game, 'kill', target); self.play(game, 'mark'); self.play(game, 'rerun')
        children = game.state.whole_card_replay_ledger.children
        self.assertEqual(tuple(c.status for c in children), (ReplayChildStatus.FAILED, ReplayChildStatus.FINISHED))
        self.assertEqual(children[0].failure, 'no_target')
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 2)
        self.portable(game, 'failed-target-and-continue')

    def test_actual_waiting_child_retains_cast_and_paid_parent_completion(self):
        game = self.waiting(); state = game.state
        self.assertEqual(state.whole_card_replay_ledger.stack, (1,))
        self.assertEqual(state.whole_card_replay_ledger.children[0].status, ReplayChildStatus.RUNNING)
        self.assertTrue(state.cast_history[-1].payload_started)
        self.assertFalse(state.play_history[-1].completed)
        self.assertEqual(state.players[1].mana, 7)
        branches = (game, *self.portable(game, 'actual-body-waiting'))
        for branch in branches: self.settle(branch)
        for branch in branches: self.assertEqual(branch.snapshot(), game.snapshot())
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.assertTrue(game.state.play_history[-1].completed)
        self.portable(game, 'actual-body-resumed')

    def test_nested_root_excludes_only_actual_active_occurrence_and_runs_sibling(self):
        game = self.populated(('nested', 'mark', 'rerun')); ledger = game.state.whole_card_replay_ledger
        self.assertEqual(len(ledger.roots), 2)
        self.assertEqual(ledger.roots[1].parent_child_id, 1)
        self.assertEqual(tuple(c.occurrence_id for c in ledger.children), (1, 1, 2, 2))
        self.assertEqual(ledger.children[1].failure, 'ancestor_excluded')
        self.assertIsNone(ledger.children[1].spell_cast_id)
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 3)
        self.assertEqual(ledger.stack, ())
        self.portable(game, 'nested')

    def test_nested_waits_restore_both_roots_then_resume_each_real_body(self):
        game = self.waiting(True)
        self.assertEqual(game.state.whole_card_replay_ledger.stack, (1, 2))
        branches = (game, *self.portable(game, 'nested-waiting'))
        for branch in branches: self.settle(branch)
        for branch in branches: self.assertEqual(branch.snapshot(), game.snapshot())
        self.assertEqual(game.state.entities[game.state.players[1].hero_id].armor, 5)
        self.assertEqual(game.state.whole_card_replay_ledger.stack, ())
        self.portable(game, 'nested-complete')

    def test_genuine_lethal_interrupts_actual_root_child_cast_and_paid_parent(self):
        game = self.populated(('lethal', 'mark', 'rerun')); state = game.state
        ledger = state.whole_card_replay_ledger
        self.assertEqual(state.status, 'finished')
        self.assertEqual(ledger.roots[0].status, ReplayRootStatus.INTERRUPTED)
        self.assertEqual(len(ledger.children), 1)
        self.assertEqual(ledger.children[0].status, ReplayChildStatus.INTERRUPTED)
        self.assertTrue(state.cast_history[-1].interrupted)
        self.assertTrue(state.play_history[-1].interrupted)
        self.assertEqual(state.entities[state.players[1].hero_id].armor, 1)
        self.portable(game, 'actual-terminal-interruption')

    def test_runtime_body_exception_rolls_back_paid_parent_entities_roots_and_rng(self):
        game = self.game(('fail', 'random')); self.play(game, 'fail'); before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate runtime failure'): self.play(game, 'random')
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'body-exception-rollback')

    def test_resolution_budget_exhaustion_rolls_back_instead_of_becoming_game_end(self):
        game = self.game(('mark', 'mark', 'random'), ruleset=Ruleset(max_resolution_steps=25))
        self.play(game, 'mark'); self.play(game, 'mark'); before = game.snapshot()
        with self.assertRaises(ResolutionError): self.play(game, 'random')
        self.assertEqual(game.snapshot(), before)
        self.assertEqual(game.state.status, 'playing')
        self.portable(game, 'budget-rollback')

    def test_unsupported_selected_physical_type_is_not_filtered_or_run_as_blank(self):
        game = self.game(('plain', 'unsupported')); self.play(game, 'plain'); before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'physical full-body routes are not installed'):
            self.play(game, 'unsupported')
        self.assertEqual(game.snapshot(), before)
        self.portable(game, 'explicit-unsupported-type')

    def test_later_natural_turns_preserve_completed_actual_replay_history(self):
        game = self.populated(); ledger = game.state.whole_card_replay_ledger
        game.apply(EndTurn(1)); game.apply(EndTurn(2))
        self.assertEqual(game.state.whole_card_replay_ledger, ledger)
        self.portable(game, 'later-turns')

    def test_private_root_proofs_rng_and_history_do_not_enter_either_player_port(self):
        game = self.waiting(True)
        for viewer in (1, 2):
            p = game.for_player(viewer)
            value = json.dumps({'view': p.observe(), 'events': p.events(), 'actions': p.legal_actions()})
            for name in ('whole_card_replay_ledger', 'ReplayAcceptanceProof', 'rng_before', 'selected_ids', 'before_state'):
                self.assertNotIn(name, value)
        self.portable(game, 'player-isolation')

    def test_waiting_root_finish_cannot_be_removed(self):
        def mutate(s):
            q = self.encoded_work(s); q.remove(self.named(q, 'FinishReplayRoot'))
        self.negative(mutate)

    def test_waiting_ordered_advance_cannot_be_removed(self):
        def mutate(s):
            q = self.encoded_work(s); q.remove(self.named(q, 'AdvanceReplayRoot'))
        self.negative(mutate)

    def test_waiting_actual_child_finish_cannot_be_removed(self):
        def mutate(s):
            q = self.encoded_work(s); q.remove(self.named(q, 'FinishReplaySpell'))
        self.negative(mutate)

    def test_waiting_finish_cannot_borrow_another_actual_cast(self):
        self.negative(lambda s: s['state']['whole_card_replay_ledger']['children'][0].__setitem__('spell_cast_id', 1))

    def test_waiting_original_acceptance_frontier_cannot_be_trimmed(self):
        def mutate(s):
            q = self.encoded_work(s); root = self.named(q, 'FinishReplayRoot')['fields']['proof']['fields']['root']['fields']
            root['selection']['fields']['frontier']['fields']['rows']['tuple'].pop()
        self.negative(mutate)

    def test_nested_parent_child_finish_cannot_precede_inner_root_completion(self):
        def mutate(s):
            q = self.encoded_work(s)
            finishers = [w for w in q if w.get('type', '').endswith('.FinishReplaySpell')]
            parent = finishers[-1]; q.remove(parent); q.insert(0, parent)
        self.negative(mutate, True)

    def test_choice_branch_cannot_inject_replay_root_finish(self):
        def mutate(s):
            q = self.encoded_work(s); injected = deepcopy(self.named(q, 'FinishReplayRoot'))
            option = s['resolution_frame']['fields']['options']['tuple'][0]
            option['fields']['effects']['tuple'].append(injected)
        self.negative(mutate)

    def test_completed_replay_child_cannot_erase_its_actual_cast_binding(self):
        game = self.populated(); bad = game.snapshot()
        bad['state']['whole_card_replay_ledger']['children'][0]['spell_cast_id'] = 999
        self.rehash(bad)
        with self.assertRaises(SnapshotError): Game.from_snapshot(bad, make_registry(), make_mechanics())
        self.portable(game, 'completed-binding-negative')

    def test_completed_actual_body_binding_cannot_be_downgraded_to_component_fixture(self):
        game = self.populated(); bad = game.snapshot()
        bad['state']['whole_card_replay_ledger']['children'][0]['spell_cast_id'] = None
        self.rehash(bad)
        with self.assertRaisesRegex(SnapshotError, 'cannot erase its allocated spell body'):
            Game.from_snapshot(bad, make_registry(), make_mechanics())
        self.portable(game, 'binding-removed-negative')
