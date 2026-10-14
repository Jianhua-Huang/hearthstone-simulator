"""Actual whole generated bodies, common entries, waiting and semantic rejection."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import unittest

from hs_sim.engine import (AppendageSpec, CardDefinition, CardType, Game, Keyword, PlayCard,
    PlayerSetup, Registry, Scenario, SelectChoice, SummonQuantitySpec, TargetSpec, TriggerSpec, Zone)
from hs_sim.engine.effects import ChoiceOption, Damage, Destroy, Effect, GainArmor, RequestChoice
from hs_sim.engine.errors import ResolutionError, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import default_mechanics
from hs_sim.engine.serialization import canonical_hash
from hs_sim.engine.whole_card_history import WholeCardHistoryQuery
from hs_sim.engine.whole_card_physical import PROFILE
from hs_sim.engine.whole_card_replays import ReplayWholeCards


@dataclass(frozen=True)
class PhysicalDeliberateFailure(Effect):
    source_id: int


def mechanics():
    m = default_mechanics('physical-runtime-tests-v1')
    def fail(r, e): raise ResolutionError('deliberate physical body failure')
    m.register(PhysicalDeliberateFailure, fail)
    return m


def registry():
    r = Registry('physical-runtime-tests-v1')
    r.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
    r.register_behavior('power', lambda c: (GainArmor(c.player_id, 1),))
    r.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER, on_use='power'))
    r.register_card(CardDefinition('plain', 'Plain', CardType.MINION, health=5))
    r.register_card(CardDefinition('limb', 'Limb', CardType.MINION, health=2))
    r.register_card(CardDefinition('quantity', 'Quantity', CardType.MINION, health=5,
        summon_quantities=(SummonQuantitySpec(),)))
    r.register_behavior('mark', lambda c: (GainArmor(c.player_id, 1),))
    r.register_behavior('bc', lambda c: (GainArmor(c.player_id, 2),))
    r.register_behavior('combo', lambda c: (GainArmor(c.player_id, 4),))
    def wait(c):
        if c.physical is None: return (GainArmor(c.player_id, 1),)
        return (RequestChoice(c.player_id, (ChoiceOption('a', 'A', (GainArmor(c.player_id, 8),)),
            ChoiceOption('b', 'B', (GainArmor(c.player_id, 9),))), source_id=c.source_id),)
    r.register_behavior('wait', wait)
    r.register_behavior('bcwait', lambda c: wait(c) if c.battlecry.origin == 'effect' else (GainArmor(c.player_id, 2),))
    r.register_behavior('fail', lambda c: (GainArmor(c.player_id, 1), PhysicalDeliberateFailure(c.source_id))
        if c.physical is not None else ())
    r.register_behavior('lethal', lambda c: (Damage(c.state.players[2].hero_id, 100, c.source_id),)
        if c.physical is not None else ())
    r.register_behavior('target', lambda c: (Damage(c.target_id, 1, c.source_id),)
        if c.physical is not None else ())
    for name, kind in (('minion', CardType.MINION), ('weapon', CardType.WEAPON),
            ('location', CardType.LOCATION), ('herocard', CardType.HERO)):
        args = dict(health=4) if kind == CardType.MINION else dict(attack=2, durability=3) if kind == CardType.WEAPON else (
            dict(durability=3, on_use='power') if kind == CardType.LOCATION else
            dict(health=30, hero_card=True, initial_hero_power='power', hero_armor=5))
        physical = dict(battlecry='bc', combo='combo', keywords=(Keyword.COMBO,)) if kind != CardType.LOCATION else {}
        for suffix, body in (('', 'mark'), ('_wait', 'wait')):
            r.register_card(CardDefinition(name + suffix, name + suffix, kind,
                on_play=body if kind != CardType.LOCATION else None, **physical, **args))
    for name, body in (('minion_fail', 'fail'), ('minion_lethal', 'lethal')):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=4, on_play=body))
    r.register_card(CardDefinition('minion_bcwait', 'BC wait', CardType.MINION, health=4, on_play='mark', battlecry='bcwait'))
    r.register_card(CardDefinition('targeted', 'Targeted', CardType.MINION, health=4, on_play='target',
        targeting=TargetSpec(zones=(Zone.BOARD,), kinds=(CardType.MINION,), relation='enemy')))
    r.register_card(CardDefinition('giant', 'Giant', CardType.MINION, health=4, on_play='mark', battlecry='bc',
        keywords=(Keyword.COLOSSAL,), colossal=(AppendageSpec('limb'), AppendageSpec('limb'))))
    def watch(c):
        if c.event.kind == 'location_placed':
            if not c.state.whole_card_replay_ledger.stack: return ()
        elif not c.state.card_summon_history or c.state.entities[c.event.target_id].card_id.startswith('limb'): return ()
        if c.source.card_id == 'killer': return (Destroy(c.event.target_id, c.source_id),)
        return (RequestChoice(c.player_id, (ChoiceOption('a', 'Continue', ()),), source_id=c.source_id),)
    r.register_behavior('watch', watch)
    def origin_watch(c):
        if not c.state.card_summon_history: return ()
        root = c.state.card_summon_history[-1]
        if c.state.entities[c.event.target_id].origin_entity_id != root.request.cause.source.entity_id:
            return ()
        return (GainArmor(c.player_id, 32),)
    r.register_behavior('origin_watch', origin_watch)
    r.register_card(CardDefinition('origin_watcher', 'Origin watcher', CardType.MINION, health=5,
        triggers=(TriggerSpec('minion_summoned', 'origin_watch'),)))
    for name in ('watcher', 'killer'):
        r.register_card(CardDefinition(name, name, CardType.MINION, health=5,
            triggers=(TriggerSpec('minion_summoned', 'watch'), TriggerSpec('location_placed', 'watch'))))
    def request(c, player=None, choices='player'):
        return (ReplayWholeCards(c.player_id if player is None else player, c.source_id,
            WholeCardHistoryQuery(c.player_id, len(c.state.play_history) + 1, kinds=()),
            choices=choices, physical_profile=PROFILE),)
    r.register_behavior('rerun', request)
    r.register_behavior('other', lambda c: request(c, player=2))
    r.register_behavior('random', lambda c: request(c, choices='random'))
    for name in ('rerun', 'other', 'random'):
        r.register_card(CardDefinition(name, name, CardType.SPELL, cost=2, on_play=name))
    return r


class WholeCardPhysicalRuntimeTests(unittest.TestCase):
    def game(self, hand=('minion', 'rerun'), board=(), enemy=()):
        return Game.from_scenario(Scenario((PlayerSetup('hero', hand=hand, board=board, deck=('plain',) * 8,
            max_mana=10, mana=10, hero_power_card_id='power'), PlayerSetup('hero', board=enemy, deck=('plain',) * 8,
            max_mana=10, mana=10, hero_power_card_id='power')), seed=233), registry(), mechanics=mechanics())

    def play(self, g, name, target=None):
        source = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, source, target_id=target))

    def populated(self, name='minion', **kw):
        g = self.game((name, 'rerun'), **kw); self.play(g, name); self.play(g, 'rerun'); return g

    def progress(self, g, index=0):
        return g.state.whole_card_replay_ledger.children[index].physical

    def portable(self, g, label='boundary'):
        snapshot = json.loads(json.dumps(g.snapshot())); payload = build_replay(g)
        branches = (Game.from_snapshot(snapshot, registry(), mechanics()), g.clone(), replay(payload, registry(), mechanics()))
        for branch in branches:
            self.assertEqual(branch.snapshot(), snapshot)
            for player in (1, 2):
                self.assertEqual(branch.observe(player), g.observe(player))
                self.assertEqual(branch.player_events(player), g.player_events(player))
                self.assertEqual(branch.for_player(player).legal_actions(), g.for_player(player).legal_actions())
        directory = os.environ.get('PHYSICAL_RUNTIME_INPUT_DIR')
        if directory:
            self.serial = getattr(self, 'serial', 0) + 1
            p = Path(directory) / self.id() / f'{self.serial:03d}-{label}.json'; p.parent.mkdir(parents=True, exist_ok=True)
            with p.open('x', encoding='utf-8') as f:
                json.dump({'host_privileged_input': True, 'method_id': self.id(), 'snapshot': snapshot,
                    'replay': payload, 'actual_whole_card_physical_runtime': True}, f, ensure_ascii=False)
        return branches

    def completed(self, name):
        g = self.populated(name); p = self.progress(g)
        self.assertEqual(p.phase, 'completed'); self.assertIsNone(p.failure)
        self.assertEqual(p.cursor, 0 if name.startswith('location') else 3)
        self.assertEqual(len(g.state.play_history), 2); self.assertEqual(g.state.players[1].mana, 8)
        self.assertNotEqual(p.source.entity_id, g.state.play_history[0].source_id)
        self.portable(g); return g

    def waiting_body(self, name):
        g = self.populated(name + '_wait', board=('watcher',) if name == 'location' else ())
        self.assertIsNotNone(g.state.pending_choice)
        branches = self.portable(g, 'actual-body-waiting')
        for branch in (g, *branches):
            choice = branch.state.pending_choice; branch.apply(SelectChoice(choice.player_id, choice.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(self.progress(g).phase, 'completed'); self.portable(g, 'body-resumed'); return g

    @staticmethod
    def rehash(snapshot):
        payload = {k: v for k, v in snapshot.items() if k not in ('schema_version', 'events', 'events_hash', 'state_hash')}
        snapshot['state_hash'] = canonical_hash(payload)

    def negative(self, mutate, name='minion_wait', board=()):
        g = self.populated(name, board=board); bad = deepcopy(g.snapshot()); mutate(bad); self.rehash(bad)
        with self.assertRaises(SnapshotError) as result: Game.from_snapshot(bad, registry(), mechanics())
        self.assertNotIn('digest mismatch', str(result.exception)); self.portable(g, 'negative-valid-origin')

    def test_minion_full_on_play_battlecry_and_combo(self): self.completed('minion')
    def test_weapon_full_body_and_actual_equipped_primary(self):
        g = self.completed('weapon'); self.assertEqual(g.state.players[1].weapon_id, self.progress(g).source.entity_id)
    def test_location_full_on_play_without_activating_uses(self):
        g = self.completed('location'); e = g.state.entities[self.progress(g).source.entity_id]
        self.assertEqual(e.durability, 3); self.assertEqual(e.uses_this_turn, 0)
    def test_hero_full_body_and_power_replacement(self):
        g = self.completed('herocard'); self.assertEqual(g.state.players[1].hero_id, self.progress(g).source.entity_id)
        self.assertEqual(g.state.entities[g.state.players[1].hero_power_id].card_id, 'power')
    def test_mixed_physical_batch_keeps_original_order(self):
        g = self.game(('minion', 'weapon', 'location', 'herocard', 'rerun'))
        for name in ('minion', 'weapon', 'location', 'herocard', 'rerun'): self.play(g, name)
        self.assertEqual(tuple(c.card_id for c in g.state.whole_card_replay_ledger.children), ('minion', 'weapon', 'location', 'herocard'))
        self.assertTrue(all(c.physical.phase == 'completed' for c in g.state.whole_card_replay_ledger.children)); self.portable(g)
    def test_duplicate_submissions_have_independent_primary_bodies(self):
        g = self.game(('minion', 'minion', 'rerun'))
        for name in ('minion', 'minion', 'rerun'): self.play(g, name)
        ids = [c.physical.source.entity_id for c in g.state.whole_card_replay_ledger.children]
        self.assertEqual(len(set(ids)), 2); self.assertEqual(len(g.state.play_history), 3); self.portable(g)
    def test_summon_quantity_extra_is_not_a_second_whole_body(self):
        g = self.populated('minion', board=('quantity',)); p = self.progress(g)
        root = g.state.card_summon_history[p.summon_root_id - 1]
        self.assertEqual(root.plan.total, 2); self.assertEqual(len(root.deliveries), 2)
        self.assertEqual(p.source, root.deliveries[0].entity); self.assertEqual(len(p.battlecry_ids), 1); self.portable(g)
    def test_colossal_entry_completes_before_primary_body(self):
        g = self.populated('giant'); p = self.progress(g)
        self.assertEqual(p.cursor, 2); self.assertEqual(len(g.state.colossal_history), 2)
        self.assertTrue(g.state.colossal_history[-1].completed); self.portable(g)
    def test_minion_body_wait_restore_clone_replay(self): self.waiting_body('minion')
    def test_weapon_body_wait_restore_clone_replay(self): self.waiting_body('weapon')
    def test_location_body_wait_restore_clone_replay(self): self.waiting_body('location')
    def test_hero_body_wait_restore_clone_replay(self): self.waiting_body('herocard')
    def test_actual_battlecry_wait_keeps_original_completion(self):
        g = self.populated('minion_bcwait'); self.assertIsNotNone(self.progress(g).active_battlecry_id)
        branches = self.portable(g, 'actual-battlecry-waiting')
        for branch in (g, *branches):
            c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(self.progress(g).phase, 'completed'); self.portable(g, 'battlecry-resumed')
    def test_random_body_choices_use_actual_shared_rng_without_waiting(self):
        g = self.game(('minion_wait', 'random')); self.play(g, 'minion_wait'); self.play(g, 'random')
        self.assertIsNone(g.state.pending_choice); self.assertEqual(self.progress(g).phase, 'completed'); self.portable(g)
    def test_full_board_minion_is_explicit_failed_attempt(self):
        g = self.populated('minion', board=('plain',) * 6)
        self.assertEqual(self.progress(g).failure, 'board_full'); self.assertIsNone(self.progress(g).source); self.portable(g)
    def test_full_board_location_is_explicit_failed_attempt(self):
        g = self.populated('location', board=('plain',) * 6)
        self.assertEqual(self.progress(g).failure, 'board_full'); self.portable(g)
    def test_executor_two_installs_its_own_primary_carrier(self):
        g = self.game(('minion', 'other')); self.play(g, 'minion'); self.play(g, 'other')
        p = self.progress(g); self.assertEqual(p.source.controller, 2); self.assertEqual(p.source.owner, 2)
        self.assertFalse(p.combo); self.assertEqual(p.combos, ())
        self.assertEqual(g.state.players[2].mana, 10); self.portable(g)
    def test_physical_body_exception_rolls_back_installation_and_payment(self):
        g = self.game(('minion_fail', 'rerun')); self.play(g, 'minion_fail'); before = g.snapshot()
        with self.assertRaises(ResolutionError): self.play(g, 'rerun')
        self.assertEqual(g.snapshot(), before); self.portable(g, 'actual-rolled-back-origin')
    def test_real_lethal_interrupts_primary_and_remaining_batch(self):
        g = self.game(('minion_lethal', 'minion', 'rerun'))
        for name in ('minion_lethal', 'minion', 'rerun'): self.play(g, name)
        self.assertEqual(g.state.status, 'finished'); ledger = g.state.whole_card_replay_ledger
        self.assertEqual(len(ledger.children), 1); self.assertEqual(ledger.children[0].status.value, 'interrupted')
        self.assertTrue(g.state.play_history[-1].interrupted); self.portable(g, 'actual-lethal')
    def test_both_players_do_not_receive_private_physical_progress(self):
        g = self.populated('minion_wait')
        for player in (1, 2):
            text = json.dumps((g.observe(player), g.player_events(player), g.for_player(player).legal_actions()))
            for key in ('PhysicalReplayProgress', 'whole_card_replay_ledger', 'summon_root_id', 'rng_before', 'before_state'):
                self.assertNotIn(key, text)
        self.portable(g)
    def test_rehashed_erased_actual_physical_binding_is_rejected(self):
        self.negative(lambda s: s['state']['whole_card_replay_ledger']['children'][0].update(physical=None))
    def test_rehashed_removed_full_body_finish_is_rejected(self):
        def mutate(s):
            work = s['resolution_frame']['fields']['continuation']['tuple']
            work[:] = [w for w in work if not w.get('type', '').endswith('.FinishPhysicalBody')]
        self.negative(mutate)
    def test_rehashed_actual_battlecry_binding_erasure_is_rejected(self):
        self.negative(lambda s: s['state']['whole_card_replay_ledger']['children'][0]['physical'].update(battlecry_ids=[]), name='minion_bcwait')
    def test_old_schema113_is_explicitly_rejected(self):
        g = self.populated(); bad = g.snapshot(); bad['schema_version'] = 113
        with self.assertRaisesRegex(SnapshotError, 'Unsupported snapshot schema version'): Game.from_snapshot(bad, registry(), mechanics())
        self.portable(g)
    def test_unknown_physical_profile_fails_explicitly(self):
        with self.assertRaises(ValueError): ReplayWholeCards(1, 1, WholeCardHistoryQuery(1, 1), physical_profile='unknown')
    def test_rehashed_original_payload_replacement_is_rejected(self):
        self.negative(lambda s: s['state']['whole_card_replay_ledger']['children'][0]['physical'].update(on_play=['bc']))
    def test_waiting_preserves_real_owner_clock_and_paid_parent(self):
        g = self.populated('minion_wait'); p = g.state.play_history[-1]
        self.assertEqual(len(g.state.owner_turn_history), 1); self.assertFalse(p.completed)
        self.assertEqual(g.state.players[1].mana, 8); self.portable(g)
    def test_targeted_physical_body_has_original_complete_selection(self):
        g = self.game(('targeted', 'rerun'), enemy=('plain',)); enemy = g.state.players[2].board[0]
        self.play(g, 'targeted', enemy); self.play(g, 'rerun')
        self.assertEqual(self.progress(g).selection.target_id, enemy)
        self.assertEqual(g.state.entities[enemy].damage, 1); self.portable(g)
    def test_entry_reaction_stale_installation_fails_without_whiteboard_body(self):
        g = self.populated('minion', board=('killer',))
        self.assertEqual(self.progress(g).failure, 'stale_installation'); self.assertEqual(self.progress(g).cursor, 0); self.portable(g)
    def test_entry_reaction_choice_restores_before_body_preparation(self):
        g = self.populated('minion', board=('watcher',)); self.assertEqual(self.progress(g).phase, 'installing')
        branches = self.portable(g, 'entry-reaction-waiting')
        for branch in (g, *branches):
            c = branch.state.pending_choice; branch.apply(SelectChoice(c.player_id, c.id, ('a',)))
        for branch in branches: self.assertEqual(branch.snapshot(), g.snapshot())
        self.assertEqual(self.progress(g).phase, 'completed'); self.portable(g, 'entry-reaction-resumed')
    def test_colossal_quantity_primary_remains_distinct_from_appendages(self):
        g = self.populated('giant', board=('quantity',)); p = self.progress(g)
        root = g.state.card_summon_history[p.summon_root_id - 1]
        self.assertEqual(root.plan.total, 2); self.assertEqual(root.deliveries[1].outcome, 'board_full')
        self.assertEqual(p.source, root.deliveries[0].entity); self.assertEqual(len(p.battlecry_ids), 1); self.portable(g)
    def test_rehashed_primary_material_borrowed_child_is_rejected(self):
        def mutate(s):
            material = s['state']['card_summon_history'][0]['request']['materials'][0]
            material['child_id'] = 999
        self.negative(mutate)
    def test_primary_origin_exists_at_the_actual_entry_reaction_window(self):
        g = self.populated('minion', board=('origin_watcher',))
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 42)
        self.portable(g)
