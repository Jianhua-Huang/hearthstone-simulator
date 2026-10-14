"""Actual per-occurrence inheritance through both historical spell producers."""
from copy import deepcopy
from dataclasses import replace
import json
from random import Random
import unittest

from hs_sim.engine import (AddChooseBothModifier, CardDefinition, CardType,
    ChooseBranch, ChooseOneSpec, Game, Keyword, PlayCard, PlayerSetup,
    RecastFromHistory, Registry, RewindSpec, Scenario, SelectChoice, TargetSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, Damage, Destroy, GainArmor, RandomDamage,
    RequestChoice, Summon)
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.pools import PoolQuery
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.spell_history import SpellHistoryQuery
from hs_sim.engine.whole_card_history import (HistorySelectionMode, HistorySelectionPolicy, WholeCardHistoryQuery)
from hs_sim.engine.whole_card_replays import ReplayWholeCards
from hs_sim.engine.generated_combo_repeats import PROFILES


def registry(route='batch', policy='inherit', mode='normal', count=None, selection='oldest',
             distinct='cast', replacement=False, profile=None, player=1):
    r = Registry('history-branches-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, health=8))
    r.register_card(CardDefinition('both_source', 'Both', CardType.MINION, health=8, choose_both=True))
    r.register_card(CardDefinition('retainer', 'Retainer', CardType.MINION, health=8, retain_rewind_outcomes=True))
    origin = 'cast_history' if route == 'batch' else 'cast_effect'
    def body(c, amount):
        work = [GainArmor(c.player_id, amount)]
        indirect = c.cast.origin != 'hand' if c.cast is not None else c.physical is not None
        if mode in ('targets', 'targets_original', 'empty_targets') and c.target_id is not None:
            work.append(Damage(c.target_id, 1, c.source_id))
        if indirect and mode in ('wait', 'grant_wait'):
            option_work = (AddChooseBothModifier(c.player_id, uses=1, kinds=(CardType.SPELL,), origins=(origin,)),) if mode == 'grant_wait' else ()
            work.append(RequestChoice(c.player_id, (ChoiceOption('go', 'Go', option_work),), c.source_id))
        if indirect and mode == 'fail':
            work.extend((RandomDamage(tuple(c.state.players[2].board), 1), Summon(c.player_id, 'unknown.history.branch')))
        if indirect and mode == 'terminal': work.append(Damage(c.state.players[2].hero_id, 90))
        if indirect and mode == 'grant_body':
            work.append(AddChooseBothModifier(c.player_id, uses=1, kinds=(CardType.SPELL,), origins=(origin,)))
        return tuple(work)
    for name, amount in (('left', 2), ('right', 4), ('both', 7)):
        r.register_behavior(name, lambda c, n=amount: body(c, n))
    enemy = TargetSpec(kinds=(CardType.MINION,), zones=(Zone.BOARD,), relation='enemy') if mode in ('targets', 'targets_original', 'empty_targets') else None
    friendly = TargetSpec(kinds=(CardType.HERO,), zones=(Zone.HERO,), relation='friendly') if mode in ('targets', 'targets_original', 'empty_targets') else None
    spec = ChooseOneSpec((ChooseBranch('left', 'Left', 'left', enemy),
                          ChooseBranch('right', 'Right', 'right', friendly)),
                         ChooseBranch('both', 'Both', 'both'))
    r.register_card(CardDefinition('spell', 'Spell', CardType.SPELL, cost=1, choose_one=spec,
        **(dict(keywords=(Keyword.REWIND,), rewind=RewindSpec(1,'spell_done')) if mode == 'original_rewind' else {})))
    if mode == 'original_rewind': r.register_card(CardDefinition('spell_done', 'Done', CardType.SPELL, cost=1, choose_one=spec))
    r.register_card(CardDefinition('minion', 'Minion', CardType.MINION, cost=0, health=8, choose_one=spec))
    r.register_behavior('plain_spell', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('plain_spell', 'Plain spell', CardType.SPELL, on_play='plain_spell'))
    def runner(c):
        prefix = []
        if mode == 'policy': prefix.append(AddChooseBothModifier(player, uses=1, kinds=(CardType.SPELL,), origins=(origin,)))
        if mode == 'wrong_origin': prefix.append(AddChooseBothModifier(player, uses=1, kinds=(CardType.SPELL,), origins=('cast_draw',)))
        if mode == 'drop_both': prefix.extend(Destroy(i) for i in c.state.players[1].board)
        if mode == 'empty_targets': prefix.extend(Destroy(i) for i in c.state.players[2].board)
        if route == 'batch':
            work = RecastFromHistory(player, SpellHistoryQuery(side='friendly' if player == 1 else 'enemy', cards=PoolQuery(exclude_card_ids=('runner',)), origins=('hand',)),
                count=count, distinct=distinct, selection=selection, replacement=replacement, source_id=c.source_id,
                choices='player', branch_policy=policy, targeting='original' if mode == 'targets_original' else 'random')
        else:
            sampling = HistorySelectionPolicy() if count is None else HistorySelectionPolicy(HistorySelectionMode.RANDOM_COUNT, count, replacement)
            work = ReplayWholeCards(player, c.source_id, WholeCardHistoryQuery(1, len(c.state.play_history)+1,
                kinds=(CardType.SPELL, CardType.MINION) if profile else (CardType.SPELL,), exclude_card_ids=('runner',)),
                sampling, choices='player', spell_branch_policy=policy,
                physical_profile=profile, physical_branch_policy='inherit' if profile else 'current')
        return (*prefix, work)
    r.register_behavior('runner', runner)
    r.register_card(CardDefinition('runner', 'Runner', CardType.SPELL, cost=2, on_play='runner',
        **(dict(keywords=(Keyword.REWIND,), rewind=RewindSpec(2)) if mode == 'rewind' else {})))
    return r


def game(hand=('spell', 'spell', 'runner'), board=(), enemy=('plain',), seed=42, **cfg):
    return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=('plain',)*8,
        mana=10, max_mana=10), PlayerSetup('hero', hand=('spell',), board=enemy, deck=('plain',)*8,
        mana=10, max_mana=10)), seed=seed), registry(**cfg))


def play(g, name='spell', branch=None, target=None):
    source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
    g.apply(PlayCard(1, source, branch_id=branch, target_id=target))
    return source


class HistoryBranchReplayTests(unittest.TestCase):
    def roots(self, g): return [c for c in g.state.cast_history if c.card_id in ('spell','spell_done') and c.origin != 'hand']
    def check(self, g, **cfg):
        snapshot = json.loads(json.dumps(g.snapshot()))
        branches = (Game.from_snapshot(snapshot, registry(**cfg)), g.clone(), replay(build_replay(g), registry(**cfg)))
        for clone in branches:
            self.assertEqual(clone.snapshot(), snapshot)
            for viewer in (1, 2):
                self.assertEqual(clone.observe(viewer), g.observe(viewer))
                self.assertEqual(clone.player_events(viewer), g.player_events(viewer))
                self.assertEqual(clone.for_player(viewer).legal_actions(), g.for_player(viewer).legal_actions())
        return branches[0]
    def choose(self, g, option='go'):
        pending = g.state.pending_choice
        g.apply(SelectChoice(pending.player_id, pending.id, (option,)))
    def populated(self, **cfg):
        g = game(**cfg); play(g, branch='left'); play(g, branch='right'); return g
    def negative(self, g, mutate, **cfg):
        bad = deepcopy(g.snapshot()); mutate(bad)
        payload = {k:v for k,v in bad.items() if k not in ('schema_version','events','events_hash','state_hash')}
        bad['state_hash'] = canonical_hash(payload)
        with self.assertRaises(SnapshotError) as raised: Game.from_snapshot(bad, registry(**cfg))
        self.assertNotIn('digest mismatch', str(raised.exception))

    def test_batch_inherits_each_cast_occurrence_and_never_repays(self):
        g = self.populated(); before = g.snapshot()['rng_state']; play(g, 'runner')
        self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right'])
        self.assertEqual([c.recast_id for c in self.roots(g)], [1,2])
        self.assertEqual(g.state.players[1].mana, 6); self.assertEqual(g.snapshot()['rng_state'], before)
        self.assertEqual(len(g.state.play_history), 3); self.check(g)
    def test_batch_current_reselects_at_each_new_window(self):
        cfg = dict(policy='current'); g = self.populated(**cfg)
        rng = Random(); rng.setstate(g._rng.getstate()); expected = [rng.choice(('left','right')) for _ in range(2)]
        play(g, 'runner'); self.assertEqual([c.branch_id for c in self.roots(g)], expected)
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.check(g, **cfg)
    def test_batch_newest_and_distinct_card_use_selected_original(self):
        cfg = dict(selection='newest', distinct='card'); g = self.populated(**cfg); play(g, 'runner')
        self.assertEqual([(c.branch_id,c.recast_id) for c in self.roots(g)], [('right',2)]); self.check(g, **cfg)
    def test_batch_random_replacement_keeps_each_actual_cast_branch(self):
        cfg = dict(count=5, selection='random', replacement=True); g = self.populated(**cfg); play(g, 'runner')
        self.assertEqual(len(self.roots(g)), 5)
        for c in self.roots(g): self.assertEqual(c.branch_id, g.state.cast_history[c.recast_id-1].branch_id)
        self.check(g, **cfg)
    def test_batch_combines_once_then_inherits_next_original(self):
        cfg = dict(mode='policy'); g = self.populated(**cfg); play(g, 'runner')
        self.assertEqual([c.branch_id for c in self.roots(g)], ['both','right'])
        self.assertEqual(len(g.state.choose_policy_receipts), 1); self.assertFalse(g.state.players[1].choose_both_modifiers)
        self.check(g, **cfg)
    def test_batch_wrong_origin_does_not_consume_or_combine(self):
        cfg = dict(mode='wrong_origin'); g = self.populated(**cfg); play(g, 'runner')
        self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right'])
        self.assertEqual(g.state.players[1].choose_both_modifiers[0].uses_remaining, 1); self.check(g, **cfg)
    def test_batch_waiting_restores_each_branch_and_remaining_spec(self):
        cfg = dict(mode='wait'); g = self.populated(**cfg); play(g, 'runner')
        for expected in ('left','right'):
            self.assertEqual(self.roots(g)[-1].branch_id, expected); g = self.check(g, **cfg); self.choose(g)
        self.assertIsNone(g.state.pending_choice); self.check(g, **cfg)
    def test_batch_next_window_reads_policy_granted_during_prior_wait(self):
        cfg = dict(mode='grant_wait'); g = self.populated(**cfg); play(g, 'runner'); self.choose(g)
        self.assertEqual([c.branch_id for c in self.roots(g)], ['left','both']); g = self.check(g, **cfg); self.choose(g); self.check(g, **cfg)
    def test_whole_inherits_actual_plays_and_saves_each_branch_receipt(self):
        cfg = dict(route='whole'); g = self.populated(**cfg); before = g.snapshot()['rng_state']; play(g, 'runner')
        self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right']); self.assertEqual(g.snapshot()['rng_state'], before)
        rows = g.state.whole_card_replay_ledger.children
        self.assertEqual([(c.occurrence_id,c.spell_branch.inherited_branch_id) for c in rows], [(1,'left'),(2,'right')])
        self.assertEqual(g.state.players[1].mana, 6); self.check(g, **cfg)
    def test_whole_current_proves_branch_rng_then_target_rng(self):
        cfg = dict(route='whole', policy='current'); g = self.populated(**cfg)
        rng = Random(); rng.setstate(g._rng.getstate()); expected = [rng.choice(('left','right')) for _ in range(2)]
        play(g, 'runner'); self.assertEqual([c.branch_id for c in self.roots(g)], expected)
        for child in g.state.whole_card_replay_ledger.children:
            receipt = child.spell_branch; cast = g.state.cast_history[child.spell_cast_id-1]
            self.assertEqual(receipt.options, ('left','right')); self.assertEqual(receipt.rng_after, cast.target_selection.rng_before)
        self.assertEqual(g._rng.getstate(), rng.getstate()); self.check(g, **cfg)
    def test_whole_new_roots_consume_one_combined_policy_then_inherit(self):
        cfg = dict(route='whole', mode='policy'); g = self.populated(**cfg); play(g, 'runner')
        self.assertEqual([c.branch_id for c in self.roots(g)], ['both','right'])
        self.assertEqual(g.state.whole_card_replay_ledger.children[0].spell_branch.inherited_branch_id, 'left')
        self.assertEqual(len(g.state.choose_policy_receipts), 1); self.check(g, **cfg)
    def test_whole_waiting_keeps_original_receipt_and_advances_independently(self):
        cfg = dict(route='whole', mode='wait'); g = self.populated(**cfg); play(g, 'runner')
        for expected in ('left','right'):
            self.assertEqual(self.roots(g)[-1].branch_id, expected); g = self.check(g, **cfg); self.choose(g)
        self.assertIsNone(g.state.pending_choice); self.check(g, **cfg)
    def test_whole_next_child_rechecks_policy_after_actual_wait(self):
        cfg = dict(route='whole', mode='grant_wait'); g = self.populated(**cfg); play(g, 'runner'); self.choose(g)
        self.assertEqual([c.branch_id for c in self.roots(g)], ['left','both']); g = self.check(g, **cfg); self.choose(g); self.check(g, **cfg)
    def test_whole_replacement_preserves_separate_children_for_same_original(self):
        cfg = dict(route='whole', count=5, replacement=True); g = self.populated(**cfg); play(g, 'runner')
        rows = g.state.whole_card_replay_ledger.children; self.assertEqual(len(rows), 5)
        self.assertEqual(len({c.spell_cast_id for c in rows}), 5)
        for child in rows: self.assertEqual(child.spell_branch.inherited_branch_id, g.state.play_history[child.occurrence_id-1].branch_id)
        self.check(g, **cfg)
    def test_whole_inherited_combined_survives_original_source_death(self):
        cfg = dict(route='whole', mode='drop_both'); g = game(hand=('spell','runner'), board=('both_source',), **cfg)
        play(g, branch='both'); before = g.snapshot()['rng_state']; play(g, 'runner')
        self.assertEqual(self.roots(g)[0].branch_id, 'both'); self.assertFalse(g.state.players[1].board)
        self.assertEqual(g.snapshot()['rng_state'], before); self.check(g, **cfg)
    def test_whole_target_domains_follow_inherited_branch(self):
        cfg = dict(route='whole', mode='targets'); g = game(**cfg)
        enemy = g.state.players[2].board[0]; hero = g.state.players[1].hero_id
        play(g, branch='left', target=enemy); play(g, branch='right', target=hero); play(g, 'runner')
        self.assertEqual([(c.branch_id,c.target_id) for c in self.roots(g)], [('left',enemy),('right',hero)])
        self.check(g, **cfg)
    def test_whole_required_empty_target_keeps_selected_branch_and_failed_child(self):
        cfg = dict(route='whole', mode='empty_targets'); g = game(hand=('spell','runner'), **cfg)
        play(g, branch='left', target=g.state.players[2].board[0]); before = g.snapshot()['rng_state']; play(g, 'runner')
        cast = self.roots(g)[0]; child = g.state.whole_card_replay_ledger.children[0]
        self.assertEqual((cast.branch_id,cast.failure,child.failure), ('left','no_target','no_target'))
        self.assertEqual(g.snapshot()['rng_state'], before); self.check(g, **cfg)
    def test_unbranched_history_is_ordinary_and_has_no_fabricated_receipt(self):
        for route in ('batch','whole'):
            cfg = dict(route=route); g = game(hand=('plain_spell','runner'), **cfg); play(g,'plain_spell'); play(g,'runner')
            self.assertIsNone(g.state.cast_history[-1].branch_id)
            if route == 'whole': self.assertIsNone(g.state.whole_card_replay_ledger.children[0].spell_branch)
            self.check(g, **cfg)
    def test_whole_mixed_profiles_keep_spell_and_physical_branch_policies_separate(self):
        for profile in PROFILES:
            cfg = dict(route='whole', profile=profile); g = game(hand=('spell','minion','runner'), **cfg)
            play(g, branch='left'); play(g, 'minion', 'right'); play(g,'runner')
            children = g.state.whole_card_replay_ledger.children
            self.assertEqual(children[0].spell_branch.branch_id, 'left')
            self.assertIsNone(children[1].spell_branch)
            self.assertEqual(children[1].physical.choose_one.branch_id, 'right')
            self.check(g, **cfg)
    def test_exception_rolls_back_parent_payment_rng_policy_and_new_receipts(self):
        for route in ('batch','whole'):
            cfg = dict(route=route, mode='fail'); g = self.populated(**cfg); before = g.snapshot()
            with self.assertRaises(ResolutionError): play(g,'runner')
            self.assertEqual(g.snapshot(), before); self.check(g, **cfg)
    def test_terminal_interrupt_retains_actual_selected_branch(self):
        for route in ('batch','whole'):
            cfg = dict(route=route, mode='terminal'); g = self.populated(**cfg); play(g,'runner')
            self.assertEqual(g.state.status, 'finished'); self.assertEqual([c.branch_id for c in self.roots(g)], ['left'])
            self.assertEqual(g.state.players[1].mana, 6); self.check(g, **cfg)
    def test_invalid_policies_fail_without_silent_fallback(self):
        for policy in ('original', None, True, 1):
            with self.assertRaises(ValueError): RecastFromHistory(1, branch_policy=policy)
            with self.assertRaises(ValueError): ReplayWholeCards(1,1,WholeCardHistoryQuery(1,1),spell_branch_policy=policy)
    def test_whole_closed_receipt_cannot_borrow_another_original_branch(self):
        cfg = dict(route='whole'); g = self.populated(**cfg); play(g,'runner')
        self.negative(g, lambda b: b['state']['whole_card_replay_ledger']['children'][0]['spell_branch'].update(inherited_branch_id='right'), **cfg)
    def test_whole_waiting_cannot_erase_or_replace_its_branch_receipt(self):
        cfg = dict(route='whole', mode='wait'); g = self.populated(**cfg); play(g,'runner')
        self.negative(g, lambda b: b['state']['whole_card_replay_ledger']['children'][0].update(spell_branch=None), **cfg)
        self.negative(g, lambda b: b['state']['whole_card_replay_ledger']['roots'][0].update(spell_branch_policy='current'), **cfg)
        self.check(g, **cfg)
    def test_receipts_and_rng_do_not_enter_either_player_port(self):
        cfg = dict(route='whole', mode='wait'); g = self.populated(**cfg); play(g,'runner')
        for viewer in (1,2):
            text = json.dumps({'view':g.observe(viewer),'events':g.player_events(viewer)}, ensure_ascii=False)
            for private in ('rng_before','rng_after','SpellReplayBranchReceipt','whole_card_replay_ledger','inherited_branch_id'):
                self.assertNotIn(private,text)
        self.check(g, **cfg)

    def test_batch_original_target_policy_uses_its_inherited_branch(self):
        cfg = dict(mode='targets_original'); g = game(**cfg)
        enemy = g.state.players[2].board[0]; hero = g.state.players[1].hero_id
        play(g, branch='left', target=enemy); play(g, branch='right', target=hero); play(g, 'runner')
        self.assertEqual([(c.branch_id,c.target_id) for c in self.roots(g)], [('left',enemy),('right',hero)])
        self.check(g, **cfg)
    def test_other_executor_inherits_original_branch_without_original_payment_owner(self):
        for route in ('batch','whole'):
            cfg = dict(route=route, player=2); g = self.populated(**cfg)
            play(g, 'runner')
            self.assertEqual([c.player_id for c in self.roots(g)], [2,2])
            self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right'])
            self.assertEqual((g.state.players[1].mana,g.state.players[2].mana), (6,10))
            self.assertEqual(g.state.entities[g.state.players[2].hero_id].armor, 6); self.check(g, **cfg)
    def test_real_parent_retry_recreates_child_windows_without_repayment(self):
        for route in ('batch','whole'):
            cfg = dict(route=route, mode='rewind'); g = self.populated(**cfg); play(g,'runner'); g = self.check(g, **cfg)
            original_sources = [c.source_id for c in self.roots(g)]
            self.choose(g,'retry'); g = self.check(g, **cfg)
            self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right'])
            self.assertTrue(all(c.source_id > max(original_sources) for c in self.roots(g)))
            self.choose(g,'keep'); self.assertEqual((g.state.players[1].mana,len(g.state.play_history)), (6,3)); self.check(g, **cfg)
    def test_retained_parent_results_keep_independent_children_and_single_payment(self):
        for route in ('batch','whole'):
            cfg = dict(route=route, mode='rewind'); g = self.populated(board=('retainer',), **cfg); play(g,'runner')
            self.assertEqual([c.branch_id for c in self.roots(g)], ['left','right']*3)
            self.assertEqual(len({c.source_id for c in self.roots(g)}), 6)
            self.assertEqual((g.state.players[1].mana,len(g.state.play_history)), (6,3))
            if route == 'whole': self.assertEqual(len(g.state.whole_card_replay_ledger.roots),3)
            self.check(g, **cfg)
    def test_batch_waiting_cannot_change_remaining_branch_policy(self):
        cfg = dict(mode='wait'); g = self.populated(**cfg); play(g,'runner')
        def mutate(b):
            work = b['resolution_frame']['fields']['continuation']['tuple']
            pending = next(w for w in work if w.get('type','').endswith('.ContinueHistoryCasts'))
            pending['fields']['spec']['fields']['branch_policy'] = 'current'
        self.negative(g, mutate, **cfg); self.check(g, **cfg)
    def test_whole_closed_receipt_cannot_expand_or_reorder_branch_options(self):
        cfg = dict(route='whole', policy='current'); g = self.populated(**cfg); play(g,'runner')
        self.negative(g, lambda b: b['state']['whole_card_replay_ledger']['children'][0]['spell_branch'].update(options=['right','left','both']), **cfg)
        self.check(g, **cfg)
    def test_whole_inheritance_is_not_a_permanent_physical_preselection(self):
        cfg = dict(route='whole', mode='wait'); g = self.populated(**cfg); play(g,'runner')
        for cast in self.roots(g): self.assertIsNone(g.state.entities[cast.source_id].choose_branch)
        g = self.check(g, **cfg); self.choose(g); self.choose(g)
        for cast in self.roots(g): self.assertIsNone(g.state.entities[cast.source_id].choose_branch)
        self.check(g, **cfg)
    def test_whole_inherits_branch_of_submitted_face_after_original_rewind(self):
        cfg = dict(route='whole',mode='original_rewind'); g = game(hand=('spell','runner'), **cfg)
        play(g,branch='left'); self.choose(g,'retry')
        original = g.state.play_history[0]
        self.assertEqual((original.card_id,original.played_face.card_id), ('spell_done','spell_done'))
        play(g,'runner'); self.assertEqual([(c.card_id,c.branch_id) for c in self.roots(g)], [('spell_done','left')])
        self.assertEqual(g.state.players[1].mana,7); self.check(g, **cfg)
    def test_empty_batches_inherit_nothing_and_consume_no_rng(self):
        for route in ('batch','whole'):
            cfg = dict(route=route); g = game(hand=('runner',), **cfg); before=g.snapshot()['rng_state']; play(g,'runner')
            self.assertFalse(self.roots(g)); self.assertEqual(g.snapshot()['rng_state'],before); self.check(g, **cfg)


if __name__ == '__main__': unittest.main()
