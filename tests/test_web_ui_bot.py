"""DTO-only local opponent: routing, bounded stepping and player isolation."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import random
import unittest
from unittest.mock import patch

from hs_sim.engine import CardDefinition, CardType, Game, PlayerSetup, Registry, Scenario
from hs_sim.engine.effects import ChoiceOption, RequestChoice
from hs_sim.engine.player_api import PlayerPort
from hs_sim.engine.replay import build_replay, replay
from web_ui.bot import BotError, choose_action
from web_ui.server import Host


class WebUIBot(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.token = ''

    def request(self, path, body=None, token=None):
        return self.host.route('/api/' + path, body or {}, self.token if token is None else token)

    def create(self, preset='practice', opponent='ai'):
        status, created = self.request('create', {'preset': preset, 'opponent': opponent}, token='')
        self.assertEqual(status, 200)
        self.token = created['token']
        self.session = self.host.sessions[self.token]
        return self.request('view')[1]

    def controls(self, message):
        return {'revision': message['revision'], 'ticket': message['opponent']['ticket']}

    def step(self, message):
        status, result = self.request('opponent/step', self.controls(message))
        self.assertEqual(status, 200, result)
        return result

    def command(self, message, action):
        status, result = self.request('action', {'revision': message['revision'], 'action': action})
        self.assertEqual(status, 200)
        self.assertTrue(result['accepted'], result.get('command_error'))
        return result

    def configure(self, message, mode):
        status, result = self.request('opponent', {**self.controls(message), 'mode': mode})
        self.assertEqual(status, 200, result)
        return result

    def install_choice_fixture(self, *, count=2, actor=1, options=2, minimum=1):
        self.create()
        registry = Registry('web-ui-bot-private-choices-v1')
        registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30))
        choices = tuple(ChoiceOption('private-' + str(i), 'Private option ' + str(i), ()) for i in range(options))
        registry.register_behavior('choices', lambda c: [
            RequestChoice(3 - c.player_id, choices, source_id=c.source_id, min_count=minimum, max_count=minimum)
            for _ in range(count)])
        registry.register_card(CardDefinition('choices', 'Choices', CardType.SPELL, on_play='choices'))
        registry.register_card(CardDefinition('secret-hand', 'Unknown hand card', CardType.MINION, attack=1, health=1))
        players = tuple(PlayerSetup('hero', hand=('choices', 'secret-hand') if seat == actor else ('secret-hand',))
                        for seat in (1, 2))
        game = Game.from_scenario(Scenario(players, active_player=actor), registry)
        self.session.registry = registry
        self.session.game = self.host.game = game
        return self.request('view')[1]

    def assert_portable(self):
        game = self.session.game
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), self.session.registry)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(replay(build_replay(game), self.session.registry).snapshot(), game.snapshot())
        for seat in (1, 2):
            self.assertEqual(restored.for_player(seat).observe(), game.for_player(seat).observe())

    def test_policy_prefers_ordinary_excludes_concede_and_uses_supplied_rng(self):
        message = {'error': None, 'actions': [{'type': 'concede'}, {'type': 'end_turn'},
                   {'type': 'attack', 'attacker': 'e1', 'defender': 'e2'}],
                   'observation': {'status': 'playing', 'viewer': 2, 'active_player': 2, 'pending_choice': None}}
        original = deepcopy(message)
        rng = random.Random(4)
        self.assertEqual(choose_action(message, rng)['type'], 'attack')
        self.assertEqual(choose_action(message, rng, force_end=True), {'type': 'end_turn'})
        message['actions'] = [{'type': 'concede'}]
        with self.assertRaisesRegex(BotError, 'no_legal_actions'): choose_action(message, rng)
        with self.assertRaisesRegex(BotError, 'action_budget_exhausted'): choose_action(message, rng, force_end=True)
        message = deepcopy(original)
        message['error'] = 'unsupported-private-rule-detail'
        with self.assertRaisesRegex(BotError, '^enumeration_failed$'): choose_action(message, rng)
        message = deepcopy(original)
        message['observation']['pending_choice'] = {'player_id': 1}
        with self.assertRaisesRegex(BotError, 'opponent_not_acting'): choose_action(message, rng)
        self.assertEqual(original['actions'][0], {'type': 'concede'})

    def test_mode_changes_tickets_handoff_and_read_only_views(self):
        message = self.create()
        before = self.session.game.snapshot(); rng = self.session.opponent_rng.getstate()
        self.assertEqual(message['opponent']['seat'], 2)
        self.assertFalse(message['opponent']['can_step'])
        self.assertEqual(self.request('view')[1], message)
        self.assertEqual(self.session.game.snapshot(), before)
        self.assertEqual(self.session.opponent_rng.getstate(), rng)
        self.assertEqual(self.request('handoff'), (409, {'error': 'opponent_controls_seat'}))
        stale = {**self.controls(message), 'mode': 'ai'}
        message = self.configure(message, 'human')
        self.assertEqual(message['revision'], stale['revision'])
        self.assertEqual(self.request('opponent', stale), (409, {'error': 'stale_opponent_step'}))
        self.assertEqual(self.session.opponent_mode, 'human')
        self.assertEqual(self.request('opponent/step', self.controls(message)), (409, {'error': 'opponent_disabled'}))
        status, handoff = self.request('handoff'); self.assertEqual(status, 200)
        self.token = handoff['token']
        self.assertEqual(self.request('opponent', {**self.controls(message), 'mode': 'ai'}), (409, {'error': 'handoff_pending'}))
        message = self.request('ready')[1]
        message = self.configure(message, 'ai')
        self.assertEqual((message['seat'], message['opponent']['seat']), (2, 1))
        self.assertTrue(message['opponent']['can_step'])
        for mode in ('bad', True, [], None):
            self.assertEqual(self.request('opponent', {**self.controls(message), 'mode': mode}), (400, {'error': 'invalid_opponent'}))
        self.assertEqual(self.request('opponent', {**self.controls(message), 'mode': 'ai', 'seat': 2}), (400, {'error': 'invalid_request'}))
        for ticket in ('非ASCII票据', '', 'a' * 31, 'a' * 33, '!' * 32, None):
            self.assertEqual(self.request('opponent/step', {**self.controls(message), 'ticket': ticket}), (400, {'error': 'invalid_request'}))
            self.assertEqual(self.request('opponent', {**self.controls(message), 'ticket': ticket, 'mode': 'human'}), (400, {'error': 'invalid_request'}))
        self.assertEqual(self.session.opponent_mode, 'ai')
        self.assertEqual(self.request('opponent/step', self.controls(message), token='wrong')[0], 403)
        self.assertEqual(self.request('create', {'preset': 'practice', 'opponent': 'bad'})[0], 400)

    def test_constructed_mulligan_stops_for_human_and_completes_ai_choice(self):
        message = self.create('constructed')
        human_choices = bot_choices = 0
        for _ in range(12):
            observation = message['observation']
            if observation['opening_stage'] == 'complete': break
            pending = observation['pending_choice']
            self.assertIsNotNone(pending)
            if pending['player_id'] == 1:
                before = self.session.game.snapshot()
                self.assertFalse(message['opponent']['can_step'])
                self.assertEqual(self.request('opponent/step', self.controls(message)), (409, {'error': 'opponent_not_acting'}))
                self.assertEqual(before, self.session.game.snapshot())
                message = self.command(message, {'type': 'select_choice', 'choice': pending['ref'], 'options': []})
                human_choices += 1
            else:
                self.assertEqual(pending, {'player_id': 2})
                message = self.step(message)
                self.assertTrue(message['opponent_acted']); bot_choices += 1
        self.assertEqual(message['observation']['opening_stage'], 'complete')
        self.assertEqual((human_choices, bot_choices), (1, 1))
        self.assert_portable()

    def test_practice_multiple_turns_privacy_replay_and_duplicate_step(self):
        message = self.create()
        kinds = set(); ai_actions = 0
        for _ in range(3):
            message = self.command(message, {'type': 'end_turn'})
            self.assertTrue(message['opponent']['can_step'])
            for _ in range(35):
                if not message['opponent']['can_step']: break
                old = self.controls(message)
                message = self.step(message)
                self.assertTrue(message['opponent_acted'], message['opponent'])
                ai_actions += 1
                action = self.session.game.history[-1]['action']
                self.assertEqual(action['player_id'], 2)
                self.assertNotEqual(action['type'], 'concede'); kinds.add(action['type'])
                before = self.session.game.snapshot()
                status, error = self.request('opponent/step', old)
                self.assertEqual(status, 409)
                self.assertIn(error['error'], ('stale_observation', 'stale_opponent_step'))
                self.assertEqual(before, self.session.game.snapshot())
                self.assertEqual(message['seat'], 1)
                self.assertNotIn('action', message); self.assertNotIn('snapshot', message)
                self.assertTrue(all(c['card_id'] is None for c in message['observation']['players'][1]['hand']))
            self.assertIsNone(message['opponent']['error'])
            self.assertFalse(message['opponent']['can_step'])
            if message['observation']['status'] != 'playing': break
            self.assertEqual(message['observation']['active_player'], 1)
        self.assertGreater(ai_actions, 6)
        self.assertTrue({'end_turn', 'play_card', 'attack', 'use_hero_power'} <= kinds, kinds)
        self.assert_portable()

    def test_private_consecutive_choices_redact_options_and_require_new_ticket(self):
        message = self.install_choice_fixture()
        action = next(a for a in message['actions'] if a['type'] == 'play_card'
                      and a['card'] == message['observation']['players'][0]['hand'][0]['ref'])
        message = self.command(message, action)
        self.assertEqual(message['observation']['active_player'], 1)
        self.assertEqual(message['observation']['pending_choice'], {'player_id': 2})
        self.assertTrue(message['opponent']['can_step'])
        old = self.controls(message)
        message = self.step(message)
        self.assertTrue(message['opponent_acted'])
        self.assertNotEqual(message['opponent']['ticket'], old['ticket'])
        before = self.session.game.snapshot()
        # The engine currently publishes redacted choice event placeholders, so
        # its human cursor advances. The host ticket is separately mandatory
        # even if a caller obtains the current public observation revision.
        self.assertEqual(self.request('opponent/step', old), (409, {'error': 'stale_observation'}))
        self.assertEqual(self.request('opponent/step', {**old, 'revision': message['revision']}),
                         (409, {'error': 'stale_opponent_step'}))
        self.assertEqual(before, self.session.game.snapshot())
        self.assertEqual(message['observation']['pending_choice'], {'player_id': 2})
        self.assertNotIn('Private option', json.dumps(message))
        self.assertNotIn('private-', json.dumps(message))
        self.assert_portable()
        message = self.step(message)
        self.assertIsNone(message['observation']['pending_choice'])
        self.assertFalse(message['opponent']['can_step'])
        self.assert_portable()

    def test_human_choice_during_ai_turn_and_ended_game_never_automated(self):
        message = self.install_choice_fixture(actor=2, count=1)
        # Only the choice spell has a legal play: no mana for the other hand card.
        legal = self.session.game.for_player(2).legal_actions()
        spell = legal['observation']['players'][1]['hand'][0]['ref']
        selected = next(a for a in legal['actions'] if a['type'] == 'play_card' and a['card'] == spell)
        with patch('web_ui.server.choose_action', return_value=selected): message = self.step(message)
        self.assertEqual(message['observation']['active_player'], 2)
        self.assertEqual(message['observation']['pending_choice']['player_id'], 1)
        self.assertFalse(message['opponent']['can_step'])
        before = self.session.game.snapshot()
        self.assertEqual(self.request('opponent/step', self.controls(message)), (409, {'error': 'opponent_not_acting'}))
        self.assertEqual(before, self.session.game.snapshot())
        pending = message['observation']['pending_choice']
        message = self.command(message, {'type': 'select_choice', 'choice': pending['ref'], 'options': [pending['options'][0]['ref']]})
        self.assertTrue(message['opponent']['can_step'])
        message = self.command(message, {'type': 'concede'})
        self.assertFalse(message['opponent']['can_step'])
        before = self.session.game.snapshot()
        self.assertEqual(self.request('opponent/step', self.controls(message)), (409, {'error': 'opponent_not_acting'}))
        self.assertEqual(before, self.session.game.snapshot())

    def test_action_budget_ends_turn_and_choice_budget_pauses_without_mutation(self):
        message = self.create()
        message = self.command(message, {'type': 'end_turn'})
        with patch('web_ui.server.BOT_ACTION_BUDGET', 0): message = self.step(message)
        self.assertTrue(message['opponent_acted'])
        self.assertEqual(self.session.game.history[-1]['action']['type'], 'end_turn')
        self.assertEqual(message['observation']['active_player'], 1)
        choice_limit = 3
        message = self.install_choice_fixture(count=choice_limit + 1)
        spell = message['observation']['players'][0]['hand'][0]['ref']
        message = self.command(message, next(a for a in message['actions'] if a['type'] == 'play_card' and a['card'] == spell))
        with patch('web_ui.server.BOT_STEP_LIMIT', choice_limit), patch('web_ui.server.BOT_ACTION_BUDGET', 0):
            for _ in range(choice_limit):
                message = self.step(message)
                self.assertTrue(message['opponent_acted'])
        self.assertEqual(self.session.opponent_steps, 0)
        self.assertEqual(self.session.opponent_choice_steps, choice_limit)
        before = self.session.game.snapshot(); rng = self.session.opponent_rng.getstate()
        with patch('web_ui.server.BOT_STEP_LIMIT', choice_limit): message = self.step(message)
        self.assertFalse(message['opponent_acted'])
        self.assertEqual(message['opponent']['error'], 'action_budget_exhausted')
        self.assertFalse(message['opponent']['can_step'])
        self.assertEqual(before, self.session.game.snapshot())
        self.assertEqual(rng, self.session.opponent_rng.getstate())
        self.assertEqual(self.request('opponent/step', self.controls(message)), (409, {'error': 'opponent_paused'}))
        message = self.configure(message, 'ai')
        message = self.step(message)
        self.assertTrue(message['opponent_acted'])
        self.assertIsNone(message['observation']['pending_choice'])

    def test_enumeration_limit_choice_fallback_and_errors_pause(self):
        message = self.install_choice_fixture(count=1, options=8, minimum=4)
        spell = message['observation']['players'][0]['hand'][0]['ref']
        message = self.command(message, next(a for a in message['actions'] if a['type'] == 'play_card' and a['card'] == spell))
        original = PlayerPort.legal_actions
        def limited(port):
            result = original(port)
            if port.viewer == 2: result.update(actions=None, error='enumeration_limit')
            return result
        with patch.object(PlayerPort, 'legal_actions', limited): message = self.step(message)
        self.assertTrue(message['opponent_acted'])
        selected = self.session.game.history[-1]['action']['option_ids']
        self.assertEqual(len(selected), 4)
        self.assertEqual(len(set(selected)), 4)
        self.assertEqual(list(selected), sorted(selected))
        self.assert_portable()
        message = self.create(); message = self.command(message, {'type': 'end_turn'})
        before = self.session.game.snapshot(); rng = self.session.opponent_rng.getstate()
        def broken(port):
            result = original(port)
            if port.viewer == 2: result.update(actions=None, error='private-rule-details')
            return result
        with patch.object(PlayerPort, 'legal_actions', broken): message = self.step(message)
        self.assertFalse(message['opponent_acted'])
        self.assertEqual(message['opponent']['error'], 'enumeration_failed')
        self.assertNotIn('private-rule-details', json.dumps(message))
        self.assertFalse(message['opponent']['can_step'])
        self.assertEqual(before, self.session.game.snapshot())
        self.assertEqual(rng, self.session.opponent_rng.getstate())
        message = self.configure(message, 'ai')
        with patch('web_ui.server.choose_action', return_value={'type': 'play_card', 'card': 'e999999'}):
            message = self.step(message)
        self.assertEqual(message['opponent']['error'], 'command_rejected')
        self.assertEqual(before, self.session.game.snapshot())

    def test_concurrent_duplicate_ticket_executes_exactly_one_action(self):
        message = self.create(); message = self.command(message, {'type': 'end_turn'})
        body = self.controls(message)
        before = len(self.session.game.history)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.request('opponent/step', body), range(2)))
        self.assertEqual(sorted(status for status, _ in results), [200, 409])
        self.assertEqual(sum(bool(result.get('opponent_acted')) for _, result in results), 1)
        self.assertEqual(len(self.session.game.history), before + 1)


if __name__ == '__main__': unittest.main()
