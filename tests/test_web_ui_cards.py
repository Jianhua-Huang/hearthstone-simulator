"""Registered-card test tools: public metadata, private creation, replay boundaries."""
import json
import unittest
from unittest.mock import patch

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.resolver import Resolution
from web_ui.server import Host


class WebUICards(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        self.token = ''

    def request(self, path, body=None, token=None):
        return self.host.route('/api/' + path, body or {}, self.token if token is None else token)

    def create(self, preset='practice'):
        status, created = self.request('create', {'preset': preset}, token='')
        self.assertEqual(status, 200)
        self.token = created['token']
        self.session = self.host.sessions[self.token]
        return self.request('view')[1]

    def add(self, message, card_id):
        status, result = self.request('test/hand', {'revision': message['revision'], 'card_id': card_id})
        self.assertEqual(status, 200, result)
        return result

    def command(self, message, action):
        status, result = self.request('action', {'revision': message['revision'], 'action': action})
        self.assertEqual(status, 200)
        self.assertTrue(result['accepted'], result.get('command_error'))
        return result

    def portable(self):
        game = self.session.game
        restored = Game.from_snapshot(json.loads(json.dumps(game.snapshot())), self.session.registry)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(replay(build_replay(game), self.session.registry).snapshot(), game.snapshot())
        for seat in (1, 2):
            self.assertEqual(restored.for_player(seat).observe(), game.for_player(seat).observe())

    def unchanged(self, before, segments, ticket):
        self.assertEqual(self.session.game.snapshot(), before)
        self.assertEqual(self.session.test_segments, segments)
        self.assertEqual(self.session.opponent_ticket, ticket)

    def test_catalog_is_static_complete_registry_and_explicit_experimental_scope(self):
        status, catalog = self.request('catalog')
        self.assertEqual(status, 200)
        self.assertIsNone(self.host.game)
        self.assertEqual(catalog['scope'], 'experimental_registry')
        self.assertIn('不是完整炉石卡池', catalog['scope_note'])
        cards = {c['id']: c for c in catalog['cards']}
        self.assertEqual(set(cards), set(self.host.registry.cards))
        self.assertEqual((catalog['total'], catalog['addable_count']), (311, 262))
        for cid, definition in self.host.registry.cards.items():
            row = cards[cid]
            self.assertEqual(row['can_add'], definition.hand_playable and not bool(definition.starship_for))
            self.assertEqual(row['cost'], definition.cost)
            self.assertEqual(row['cost_resource'], definition.cost_payment.value)
            self.assertEqual(row['can_add'], row['disabled_reason'] is None)
            self.assertIsInstance(row['note'], str)
            self.assertNotIn('<', row['text'])
            self.assertNotIn('[x]', row['text'])
        self.assertEqual(cards['CS2_029']['text'], '造成6点伤害。')
        self.assertIn('黑暗之赐', cards['FIR_900']['text'])
        self.assertEqual(cards['HERO_08bp']['disabled_reason'], 'card_not_hand_playable')
        self.assertEqual(cards['HERO_08']['disabled_reason'], 'card_not_hand_playable')
        self.assertEqual(self.request('catalog', {'viewer': 2}), (400, {'error': 'invalid_request'}))
        message = self.create()
        self.assertEqual(self.request('catalog')[1], catalog)
        self.assertEqual(self.request('view')[1], message)

    def test_add_only_own_hand_no_payment_or_draw_stale_and_other_session_isolation(self):
        message = self.create()
        old_revision, old_ticket = message['revision'], message['opponent']['ticket']
        game = self.session.game
        own_deck = list(game.state.players[1].deck)
        enemy = game.for_player(2).observe()['observation']['players'][1]
        _, other = self.request('create', {'preset': 'practice'}, token='')
        other_before = self.request('view', token=other['token'])[1]
        message = self.add(message, 'CS2_118')
        self.assertEqual(message['test_adjustment']['name'], self.session.registry.card('CS2_118').name)
        own = message['observation']['players'][0]
        self.assertEqual(len(own['hand']), 5)
        self.assertEqual(own['hand'][-1]['card_id'], 'CS2_118')
        self.assertEqual(own['mana'], 10)
        self.assertEqual(list(self.session.game.state.players[1].deck), own_deck)
        self.assertEqual(self.session.game.for_player(2).observe()['observation']['players'][1], enemy)
        self.assertNotEqual(message['opponent']['ticket'], old_ticket)
        self.assertEqual(self.request('view', token=other['token'])[1], other_before)
        before = self.session.game.snapshot()
        self.assertEqual(self.request('test/hand', {'revision': old_revision, 'card_id': 'CS2_118'}),
                         (409, {'error': 'stale_observation'}))
        self.assertEqual(self.session.game.snapshot(), before)
        self.assertEqual(len(self.session.test_segments), 1)

    def test_private_names_texts_and_handoff_never_disclose_generated_identity(self):
        message = self.add(self.create(), 'FIR_900')
        self.assertIn('FIR_900', message['names'])
        self.assertIn('黑暗之赐', message['card_texts']['FIR_900'])
        self.assertEqual(set(message['card_texts']), set(message['names']))
        self.assertNotIn('FP1_007', message['card_texts'])
        for forbidden in ('test_segments', 'origin', 'rng_state', 'snapshot'):
            self.assertNotIn(forbidden, message)
        status, switched = self.request('handoff')
        self.assertEqual(status, 200)
        self.token = switched['token']
        self.assertEqual(set(self.request('view')[1]), {'seat', 'handoff'})
        status, message = self.request('ready')
        self.assertEqual(status, 200)
        self.assertNotIn('FIR_900', message['names'])
        self.assertNotIn('FIR_900', message['card_texts'])
        self.assertNotIn('FIR_900', json.dumps(message))
        self.assertEqual(set(message['card_texts']), set(message['names']))

    def test_add_then_play_discover_waiting_restore_and_replay_segments(self):
        message = self.create()
        # Include a real accepted action in the preserved branch.
        attacker = message['observation']['players'][0]['board'][0]['ref']
        attack = next(a for a in message['actions'] if a['type'] == 'attack' and a['attacker'] == attacker)
        message = self.command(message, attack)
        previous = self.session.game.snapshot()
        message = self.add(message, 'FIR_900')
        self.assertEqual(len(self.session.test_segments), 1)
        segment = self.session.test_segments[0]
        self.assertEqual(segment['adjustment'], {'type': 'add_to_hand', 'player_id': 1, 'card_id': 'FIR_900'})
        self.assertEqual(replay(segment['replay'], self.session.registry).snapshot(), previous)
        self.assertEqual(segment['after_hash'], self.session.game.state_hash())
        self.assertEqual(self.session.game.history, [])
        ref = message['observation']['players'][0]['hand'][-1]['ref']
        message = self.command(message, next(a for a in message['actions'] if a['type'] == 'play_card' and a['card'] == ref))
        self.assertIsNotNone(message['observation']['pending_choice'])
        self.assertEqual(message['test_controls']['hand_reason'], 'choice_pending')
        self.portable()
        for _ in range(3):
            if message['observation']['pending_choice'] is None: break
            choice = next(a for a in message['actions'] if a['type'] == 'select_choice')
            message = self.command(message, choice)
        self.assertIsNone(message['observation']['pending_choice'])
        self.assertEqual(len(message['observation']['players'][0]['hand']), 5)
        self.portable()

    def test_invalid_requests_unknown_and_non_hand_definitions_are_atomic(self):
        message = self.create()
        before, ticket = self.session.game.snapshot(), self.session.opponent_ticket
        revision = message['revision']
        invalid = ({'revision': revision}, {'card_id': 'CS2_118'},
                   {'revision': None, 'card_id': 'CS2_118'}, {'revision': 'é' * 64, 'card_id': 'CS2_118'},
                   {'revision': revision, 'card_id': None}, {'revision': revision, 'card_id': ['CS2_118']},
                   {'revision': revision, 'card_id': 'CS2_118', 'player_id': 2},
                   {'revision': revision, 'card_id': 'CS2_118', 'viewer': 2})
        for body in invalid:
            self.assertEqual(self.request('test/hand', body), (400, {'error': 'invalid_request'}))
            self.unchanged(before, [], ticket)
        choices = next(c.id for c in self.session.registry.cards.values() if c.choice_only)
        ship = next(c.id for c in self.session.registry.cards.values() if c.starship_for)
        for cid, error in (('unknown', 'unknown_card'), (choices, 'choice_only'),
                           (ship, 'special_card_template'), ('HERO_08', 'card_not_hand_playable'),
                           ('HERO_08bp', 'card_not_hand_playable')):
            self.assertEqual(self.request('test/hand', {'revision': revision, 'card_id': cid}), (400, {'error': error}))
            self.unchanged(before, [], ticket)
        self.assertEqual(self.request('test/hand', {'revision': revision, 'card_id': 'CS2_118'}, token='wrong')[0], 403)

    def test_full_hand_uses_actual_capacity_and_never_burns_card(self):
        self.create()
        self.session.game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', hand=('CS2_029',), hand_cap=2), PlayerSetup('HERO_01'),
        )), self.session.registry)
        message = self.add(self.request('view')[1], 'CS2_118')
        self.assertEqual(message['test_controls']['hand_reason'], 'hand_full')
        self.assertFalse(message['test_controls']['hand_enabled'])
        before, segments, ticket = self.session.game.snapshot(), list(self.session.test_segments), self.session.opponent_ticket
        self.assertEqual(self.request('test/hand', {'revision': message['revision'], 'card_id': 'CS2_118'}),
                         (409, {'error': 'hand_full'}))
        self.unchanged(before, segments, ticket)

    def test_opening_pending_other_turn_handoff_and_game_end_are_disabled(self):
        def rejected(message, reason):
            before, segments, ticket = self.session.game.snapshot(), list(self.session.test_segments), self.session.opponent_ticket
            self.assertEqual(message['test_controls']['hand_reason'], reason)
            self.assertFalse(message['test_controls']['hand_enabled'])
            self.assertEqual(self.request('test/hand', {'revision': message['revision'], 'card_id': 'CS2_118'}),
                             (409, {'error': reason}))
            self.unchanged(before, segments, ticket)
        rejected(self.create('constructed'), 'opening_pending')
        message = self.create()
        ref = next(c['ref'] for c in message['observation']['players'][0]['hand'] if c['card_id'] == 'UNG_029')
        message = self.command(message, next(a for a in message['actions'] if a['type'] == 'play_card' and a['card'] == ref))
        rejected(message, 'choice_pending')
        message = self.create()
        message = self.command(message, {'type': 'end_turn'})
        rejected(message, 'not_your_turn')
        message = self.command(message, {'type': 'concede'})
        rejected(message, 'game_not_playing')
        message = self.create()
        _, switched = self.request('handoff')
        self.token = switched['token']
        before, ticket = self.session.game.snapshot(), self.session.opponent_ticket
        self.assertEqual(self.request('test/hand', {'revision': message['revision'], 'card_id': 'CS2_118'}),
                         (409, {'error': 'handoff_pending'}))
        self.unchanged(before, [], ticket)

    def test_special_mana_is_preserved_and_failure_discards_clone(self):
        self.create()
        self.session.game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', mana=3, max_mana=5, temporary_mana=1, overload_locked=2, overload_owed=1),
            PlayerSetup('HERO_01'),
        )), self.session.registry)
        message = self.request('view')[1]
        self.assertEqual(message['test_controls']['mana_reason'], 'special_mana_active')
        self.assertTrue(message['test_controls']['hand_enabled'])
        accounts = tuple(getattr(self.session.game.state.players[1], k) for k in ('mana', 'max_mana', 'temporary_mana', 'overload_locked', 'overload_owed'))
        message = self.add(message, 'CS2_118')
        self.assertEqual(tuple(getattr(self.session.game.state.players[1], k) for k in ('mana', 'max_mana', 'temporary_mana', 'overload_locked', 'overload_owed')), accounts)
        before, segments, ticket = self.session.game.snapshot(), list(self.session.test_segments), self.session.opponent_ticket
        original_run = Resolution.run
        def explode_after_mutation(resolution, effects):
            original_run(resolution, effects)
            raise ValueError('test resolver rollback')
        for target, effect in (('web_ui.server.Resolution.run', explode_after_mutation),
                               ('web_ui.server.Game.from_snapshot', ValueError('test restoration rollback'))):
            with patch(target, side_effect=effect, autospec=True):
                self.assertEqual(self.request('test/hand', {'revision': message['revision'], 'card_id': 'CS2_029'}),
                                 (409, {'error': 'test_hand_adjustment_unavailable'}))
            self.unchanged(before, segments, ticket)


if __name__ == '__main__':
    unittest.main()
