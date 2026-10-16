"""Independent match concession at stable host and player boundaries."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from unittest.mock import patch
import json
import unittest

from hs_sim.engine import (Concede, CardDefinition, CardType, DamageKind, EndTurn,
    Game, PlayCard, PlayerSetup, Registry, ResolutionError, Ruleset, Scenario,
    SelectChoice, SnapshotError, IllegalAction, RecoverHero)
from hs_sim.engine.actions import action_from_dict, action_to_dict
from hs_sim.engine.effects import (ChoiceOption, Damage, DamageBatch, GainArmor, RequestChoice)
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash


def registry():
    r = Registry('independent-concession-fixture-v1')
    def forbidden(c):
        raise AssertionError('Concession executed a pending gameplay callback')
    def wait(c):
        return [RequestChoice(c.player_id, (ChoiceOption('ok', 'OK', (GainArmor(c.player_id, 7),)),),
                              c.source_id, on_select='cc.never'), GainArmor(c.player_id, 100)]
    def enemy(c):
        return [RequestChoice(3 - c.player_id, (ChoiceOption('ok', 'OK', (GainArmor(c.player_id, 7),)),),
                              c.source_id), GainArmor(c.player_id, 100)]
    def save(c):
        return [RequestChoice(c.player_id, (ChoiceOption('save', 'Save', (RecoverHero(c.hero_lethal, 5),)),),
                              c.source_id)]
    for name, fn in (
            ('cc.never', forbidden), ('cc.wait', wait), ('cc.enemy', enemy), ('cc.save', save),
            ('cc.fatal', lambda c: [Damage(c.state.players[1].hero_id, 99, c.source_id)]),
            ('cc.both', lambda c: [DamageBatch(tuple(Damage(c.state.players[p].hero_id, 99, c.source_id) for p in (1, 2)))])):
        r.register_behavior(name, fn)
    for card in (
            CardDefinition('cc.hero', 'Hero', CardType.HERO, health=30),
            CardDefinition('cc.hero_never', 'Hero', CardType.HERO, health=30, deathrattle='cc.never'),
            CardDefinition('cc.hero_save', 'Hero', CardType.HERO, health=30, deathrattle='cc.save'),
            CardDefinition('cc.plain', 'Plain', CardType.MINION, attack=1, health=1),
            *(CardDefinition(n, n, CardType.SPELL, cost=2, on_play=n)
              for n in ('cc.wait', 'cc.enemy', 'cc.fatal', 'cc.both')),
            *(CardDefinition(n, 'Secret', CardType.SPELL, cost=2, on_play='cc.never')
              for n in ('cc.secretA', 'cc.secretB'))):
        r.register_card(card)
    return r


class ConcessionTests(unittest.TestCase):
    def game(self, hand=(), *, hero='cc.hero', enemy='cc.hero', enemy_hand=(), rules=None):
        return Game.from_scenario(Scenario((
            PlayerSetup(hero, hand=hand, deck=('cc.plain',) * 3, max_mana=5, mana=5, armor=3, corpses=4),
            PlayerSetup(enemy, hand=enemy_hand, deck=('cc.plain',) * 3, max_mana=4, mana=4, armor=2, corpses=6)
        ), seed=101), registry(), ruleset=rules)

    def cast(self, g):
        g.apply(PlayCard(1, g.state.players[1].hand[0]))

    def send(self, port, raw):
        return port.submit({'revision': port.observe()['revision'], 'action': raw})

    def portable(self, g):
        snap = json.loads(json.dumps(g.snapshot()))
        self.assertEqual(g.clone().snapshot(), snap)
        self.assertEqual(Game.from_snapshot(deepcopy(snap), registry()).snapshot(), snap)
        self.assertEqual(replay(build_replay(g), registry()).snapshot(), snap)
        return snap

    def rehash(self, snap):
        snap['events_hash'] = canonical_hash(snap['events'])
        snap['state_hash'] = canonical_hash({k: v for k, v in snap.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return snap

    def test_typed_action_strict_codec_and_json_roundtrip(self):
        for p in (1, 2):
            a = Concede(p)
            self.assertEqual(action_from_dict(json.loads(json.dumps(action_to_dict(a)))), a)
            self.assertEqual(action_to_dict(a), {'type': 'concede', 'player_id': p})
        for p in (True, False, 0, 3, -1, '1', None, 1.0):
            with self.subTest(p=p), self.assertRaises(ValueError):
                Concede(p)
        for raw in ({'type': 'concede'}, {'type': 'concede', 'player_id': 1, 'target': 2},
                    {'type': 'concede', 'player_id': True}):
            with self.assertRaises(ValueError):
                action_from_dict(raw)

    def test_both_seats_concede_without_health_resource_rng_or_turn_changes(self):
        for p in (1, 2):
            with self.subTest(p=p):
                g = self.game()
                before = g.snapshot()
                result = g.apply(Concede(p))
                after = g.snapshot()
                self.assertEqual((g.state.status, g.state.winner), ('finished', 3 - p))
                self.assertEqual(after['state']['players'], before['state']['players'])
                self.assertEqual(after['state']['entities'], before['state']['entities'])
                self.assertEqual(after['rng_state'], before['rng_state'])
                self.assertEqual(g.state.turn, before['state']['turn'])
                self.assertEqual(g.state.active_player, before['state']['active_player'])
                self.assertEqual([e.kind for e in result.events], ['game_ended'])
                self.assertEqual(dict(result.events[0].data)['reason'], 'concede')
                self.portable(g)

    def test_inactive_player_lists_and_submits_only_own_concession(self):
        g = self.game()
        port = g.for_player(2)
        self.assertEqual(port.legal_actions()['actions'], [{'type': 'concede'}])
        self.assertFalse(self.send(port, {'type': 'end_turn'})['accepted'])
        self.assertTrue(self.send(port, {'type': 'concede'})['accepted'])
        self.assertEqual(g.state.winner, 1)

    def test_host_and_active_port_enumeration_include_only_authorized_seats(self):
        g = self.game()
        self.assertEqual(tuple(a for a in g.legal_actions() if type(a) is Concede), (Concede(1), Concede(2)))
        actions = g.for_player(1).legal_actions()['actions']
        self.assertEqual(actions.count({'type': 'concede'}), 1)
        self.assertIn({'type': 'end_turn'}, actions)

    def test_finished_match_rejects_all_later_commands_without_mutation(self):
        g = self.game()
        g.apply(Concede(1))
        before = g.snapshot()
        for p in (1, 2):
            with self.assertRaises(IllegalAction):
                g.apply(Concede(p))
            self.assertEqual(g.for_player(p).legal_actions()['actions'], [])
            self.assertFalse(self.send(g.for_player(p), {'type': 'concede'})['accepted'])
        self.assertEqual(g.legal_actions(), ())
        self.assertEqual(g.snapshot(), before)

    def test_paid_choice_concession_preserves_spent_prefix_and_interrupts_real_tails(self):
        g = self.game(('cc.wait',))
        self.cast(g)
        before = g.snapshot()
        g.apply(Concede(2))
        self.assertEqual(g.state.players[1].mana, 3)
        self.assertEqual(g.state.entities[g.state.players[1].hero_id].armor, 3)
        self.assertIsNone(g.state.pending_choice)
        self.assertIsNone(g.snapshot()['resolution_frame'])
        self.assertEqual(g.snapshot()['rng_state'], before['rng_state'])
        self.assertTrue(g.state.play_history[-1].interrupted)
        self.assertFalse(g.state.play_history[-1].completed)
        self.assertTrue(g.state.cast_history[-1].interrupted)
        self.assertFalse(any(e.kind == 'choice_selected' for e in g.events))
        self.portable(g)

    def test_choice_owned_by_other_seat_can_be_conceded_by_either_seat(self):
        for p in (1, 2):
            g = self.game(('cc.enemy',))
            self.cast(g)
            self.assertEqual(g.state.pending_choice.player_id, 2)
            self.assertTrue(self.send(g.for_player(p), {'type': 'concede'})['accepted'])
            self.assertEqual((g.state.winner, g.state.entities[g.state.players[1].hero_id].armor), (3 - p, 3))
            self.portable(g)

    def test_restored_waiting_branch_and_clone_have_identical_concession(self):
        g = self.game(('cc.wait',))
        self.cast(g)
        before = self.portable(g)
        branches = (g, g.clone(), Game.from_snapshot(before, registry()), replay(build_replay(g), registry()))
        for branch in branches:
            branch.apply(Concede(1))
        self.assertTrue(all(b.snapshot() == g.snapshot() for b in branches))
        self.portable(g)

    def test_mulligan_boundary_can_end_without_selecting_or_finishing_opening(self):
        from opening_fixtures import registry as opening_registry, setup
        r = opening_registry()
        g = Game.from_decks(setup(r, 1, 71), r)
        before = g.snapshot()
        chooser = g.state.pending_choice.player_id
        loser = 3 - chooser
        g.apply(Concede(loser))
        self.assertEqual(g.state.winner, chooser)
        self.assertEqual(g.state.opening, Game.from_snapshot(before, r).state.opening)
        self.assertIsNone(g.state.pending_choice)
        self.assertEqual(Game.from_snapshot(g.snapshot(), r).snapshot(), g.snapshot())
        self.assertEqual(replay(build_replay(g), r).snapshot(), g.snapshot())

    def test_concession_is_not_blocked_by_gameplay_resolution_budget(self):
        g = self.game(rules=Ruleset(max_resolution_steps=1))
        g.apply(Concede(2))
        self.assertEqual(g.state.winner, 1)
        self.portable(g)

    def test_handler_failure_rolls_back_concession_and_private_observation(self):
        g = self.game(('cc.wait',))
        self.cast(g)
        before = g.snapshot()
        views = [g.for_player(p).observe() for p in (1, 2)]
        def bad(r, player_id):
            r.state.status = 'finished'
            r.game._rng.random()
            raise RuntimeError('broken trusted handler')
        with patch('hs_sim.engine.concession.concede', bad), self.assertRaises(ResolutionError):
            g.apply(Concede(2))
        self.assertEqual(g.snapshot(), before)
        self.assertEqual([g.for_player(p).observe() for p in (1, 2)], views)

    def test_rehashed_terminal_winner_cannot_disagree_with_actual_conceding_seat(self):
        g = self.game()
        g.apply(Concede(1))
        snap = g.snapshot()
        snap['state']['winner'] = 1
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(self.rehash(snap), registry())

    def test_duplicate_rehashed_concession_terminal_event_is_rejected(self):
        g = self.game()
        g.apply(Concede(1))
        snap = g.snapshot()
        duplicate = deepcopy(snap['events'][-1])
        duplicate['sequence'] += 1
        snap['events'].append(duplicate)
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(self.rehash(snap), registry())

    def test_fatal_wait_preserves_unfinished_episode_and_real_interruption_clocks(self):
        g = self.game(('cc.fatal',), hero='cc.hero_save')
        self.cast(g)
        original = g.state.hero_lethal_roots[-1]
        episodes = deepcopy(g.state.hero_lethal_history)
        g.apply(Concede(2))
        root = g.state.hero_lethal_roots[-1]
        event = g.events[-1]
        self.assertEqual(g.state.winner, 1)
        self.assertFalse(root.completed)
        self.assertEqual(root.stack, original.stack)
        self.assertEqual(root.parked_hashes, original.parked_hashes)
        self.assertEqual(g.state.hero_lethal_history, episodes)
        self.assertEqual((root.interrupted_action, root.interrupted_event), (event.action, event.sequence))
        self.assertIsNone(g.state.active_hero_lethal_root_id)
        self.assertLessEqual(g.state.entities[g.state.players[1].hero_id].health, 0)
        for p in (1, 2):
            public = json.dumps(g.for_player(p).observe()) + json.dumps(g.player_events(p))
            for private in ('hero_lethal_roots', 'hero_lethal_history', 'parked_hashes',
                            'interrupted_action', 'interrupted_event', 'resolution_frame'):
                self.assertNotIn(private, public)
        self.portable(g)

    def test_both_fatal_hero_siblings_can_concede_without_fake_completion_or_recovery(self):
        for p in (1, 2):
            g = self.game(('cc.both',), hero='cc.hero_save', enemy='cc.hero_save')
            self.cast(g)
            g.apply(Concede(p))
            self.assertEqual(g.state.winner, 3 - p)
            self.assertFalse(g.state.hero_lethal_roots[-1].completed)
            self.assertTrue(any(e.phase != 'finished' for e in g.state.hero_lethal_history))
            self.portable(g)

    def test_rehashed_hero_interruption_cannot_borrow_or_remove_terminal_receipt(self):
        g = self.game(('cc.fatal',), hero='cc.hero_save')
        self.cast(g)
        g.apply(Concede(1))
        for field, value in (('interrupted_event', 1), ('interrupted_action', 1),
                             ('interrupted_event', None), ('completed', True)):
            snap = g.snapshot()
            snap['state']['hero_lethal_roots'][-1][field] = value
            with self.subTest(field=field), self.assertRaises(SnapshotError):
                Game.from_snapshot(self.rehash(snap), registry())

    def test_living_hero_deathrattle_is_never_run_for_concession(self):
        g = self.game(hero='cc.hero_never', enemy='cc.hero_never')
        g.apply(Concede(1))
        self.assertEqual(g.state.death_history, [])
        self.assertEqual(g.state.hero_lethal_history, [])
        self.portable(g)

    def test_hidden_opponent_cards_do_not_change_concession_command_revision_or_events(self):
        a, b = (self.game(enemy_hand=(n,)) for n in ('cc.secretA', 'cc.secretB'))
        self.assertEqual(a.for_player(1).observe(), b.for_player(1).observe())
        self.assertEqual(a.for_player(1).legal_actions(), b.for_player(1).legal_actions())
        for g in (a, b):
            self.assertTrue(self.send(g.for_player(1), {'type': 'concede'})['accepted'])
            public = json.dumps(g.for_player(1).observe()) + json.dumps(g.player_events(1))
            for private in ('cc.secretA', 'cc.secretB', 'hero_lethal_roots', 'parked_hashes', 'interrupted_event'):
                self.assertNotIn(private, public)
        self.assertEqual(a.for_player(1).observe(), b.for_player(1).observe())
        self.assertEqual(a.player_events(1), b.player_events(1))

    def test_prior_schema_and_rules_context_are_explicitly_rejected(self):
        g = self.game()
        snap = g.snapshot()
        snap['schema_version'] = 219
        with self.assertRaisesRegex(SnapshotError, f'1 through {SNAPSHOT_SCHEMA_VERSION-1}'):
            Game.from_snapshot(snap, registry())
        snap = g.snapshot()
        snap['ruleset']['id'] = 'prototype-v249'
        with self.assertRaisesRegex(SnapshotError, 'Unsupported ruleset'):
            Game.from_snapshot(snap, registry())

    def test_stale_or_forged_player_and_old_selection_cannot_change_concession(self):
        g = self.game(('cc.wait',))
        self.cast(g)
        port = g.for_player(1)
        old = port.observe()['revision']
        choice = g.state.pending_choice
        before = g.snapshot()
        self.assertFalse(self.send(port, {'type': 'concede', 'player_id': 2})['accepted'])
        self.assertEqual(g.snapshot(), before)
        self.assertTrue(self.send(g.for_player(2), {'type': 'concede'})['accepted'])
        after = g.snapshot()
        self.assertEqual(port.submit({'revision': old, 'action': {'type': 'concede'}})['error'], 'stale_observation')
        with self.assertRaises(IllegalAction):
            g.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))
        self.assertEqual(g.snapshot(), after)

