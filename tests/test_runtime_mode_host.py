"""The host keeps its execution mode across new sessions and test adjustments."""
import unittest

from hs_sim.engine import RuntimeMode
from web_ui.server import Host, make_server


class RuntimeModeHost(unittest.TestCase):
    def test_debug_sessions_adjustments_and_player_output(self):
        host = Host(mode='debug')
        status, created = host.route('/api/create', {'preset': 'practice'}, '')
        self.assertEqual(status, 200)
        token = created['token']
        session = host.sessions[token]
        self.assertIs(session.game.runtime_mode, RuntimeMode.DEBUG)
        view = session.listing()
        for path, extra in (('/api/test/mana', {'mana': 9}), ('/api/test/hand', {'card_id': 'CS2_182'})):
            status, view = host.route(path, {'revision': view['revision'], **extra}, token)
            self.assertEqual(status, 200, view)
            self.assertIs(session.game.runtime_mode, RuntimeMode.DEBUG)
        card = next(card for card in view['observation']['players'][0]['hand'] if card['card_id'] == 'CS2_182')
        action = next(action for action in view['actions'] if action['type'] == 'play_card' and action['card'] == card['ref'])
        status, result = host.route('/api/action', {'revision': view['revision'], 'action': action}, token)
        self.assertEqual(status, 200)
        self.assertTrue(result['accepted'])
        self.assertEqual(len(session.game.debug_records), 1)
        self.assertNotIn('debug_records', result)
        self.assertNotIn('traceback', result)
        status, other = host.route('/api/create', {'preset': 'constructed'}, '')
        self.assertEqual(status, 200)
        self.assertIs(host.sessions[other['token']].game.runtime_mode, RuntimeMode.DEBUG)

    def test_lab_and_server_construction_keep_selected_mode(self):
        server = make_server(0, mode='debug')
        try:
            status, result = server.host.route('/api/lab/create', {'card_id': 'CS2_182'}, '')
            self.assertEqual(status, 200, result)
            self.assertIs(server.host.sessions[result['token']].game.runtime_mode, RuntimeMode.DEBUG)
        finally:
            server.server_close()


if __name__ == '__main__':
    unittest.main()
