"""UI host integration tests, independent of canonical engine changes."""
import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from web_ui.server import make_server
from examples.play_as_players import choose_action

class WebUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def setUp(self):
        self.server.host.game = None
        self.server.host.sessions.clear()
        self.token = ''
    def request(self, path, body=None, token=None, origin=None):
        headers={'Content-Type':'application/json','Authorization':'Bearer '+(self.token if token is None else token)}
        if origin: headers['Origin']=origin
        req=Request(self.base+'/api/'+path,json.dumps(body or {}).encode(),headers)
        try:
            with urlopen(req) as r: return r.status,json.load(r)
        except HTTPError as e: return e.code,json.load(e)
    def create(self,preset='practice'):
        status,d=self.request('create',{'preset':preset})
        self.assertEqual(status,200); self.token=d['token']
        return self.request('view')[1]
    def command(self,m,a): return self.request('action',{'revision':m['revision'],'action':a})[1]
    def switch(self):
        old=self.token
        status,d=self.request('handoff'); self.assertEqual(status,200)
        self.token=d['token']
        self.assertEqual(self.request('view',token=old)[0],403)
        self.assertEqual(set(self.request('view')[1]),{'seat','handoff'})
        self.assertEqual(self.request('action',{'revision':'0'*64,'action':{'type':'end_turn'}})[0],409)
        return self.request('ready')[1]
    def test_choices_hidden_information_and_replay(self):
        m=self.create()
        enemy=m['observation']['players'][1]
        self.assertTrue(all(c['card_id'] is None and 'cost' not in c for c in enemy['hand']))
        self.assertNotIn('deck',enemy)
        ids={c['card_id'] for c in m['observation']['players'][0]['hand']}
        self.assertNotIn('FP1_007',m['names'])
        ref=next(c['ref'] for c in m['observation']['players'][0]['hand'] if c['card_id']=='UNG_029')
        a=next(a for a in m['actions'] if a['type']=='play_card' and a['card']==ref)
        m=self.command(m,a); self.assertTrue(m['accepted'])
        self.assertTrue(m['observation']['pending_choice']['options'])
        from hs_sim.engine import Game
        from hs_sim.engine.representative import build_registry
        game=self.server.host.game
        restored=Game.from_snapshot(json.loads(json.dumps(game.snapshot())),build_registry())
        self.assertEqual(restored.for_player(1).observe(),game.for_player(1).observe())
        self.assertEqual(restored.for_player(2).observe(),game.for_player(2).observe())
        other=self.switch()
        self.assertEqual(other['observation']['pending_choice'],{'player_id':1})
        self.assertNotIn('CS2_029',other['names'])  # Private spell offer and hand remain undisclosed.
        m=self.switch(); choice=m['observation']['pending_choice']
        m=self.command(m,{'type':'select_choice','choice':choice['ref'],'options':[choice['options'][0]['ref']]})
        self.assertTrue(m['accepted']); self.assertIsNone(m['observation']['pending_choice'])
        from hs_sim.engine.replay import build_replay,replay
        from hs_sim.engine.representative import build_registry
        game=self.server.host.game
        self.assertEqual(replay(build_replay(game),build_registry()).snapshot(),game.snapshot())
    def test_illegal_stale_and_seat_override(self):
        m=self.create(); before=self.server.host.game.snapshot()
        bad=self.command(m,{'type':'play_card','card':'e999999'})
        self.assertFalse(bad['accepted']); self.assertEqual(bad['command_error'],'invalid_action')
        self.assertEqual(before,self.server.host.game.snapshot())
        status,bad=self.request('action',{'revision':m['revision'],'action':{'type':'end_turn'},'viewer':2})
        self.assertFalse(bad['accepted'])
        good=self.command(m,{'type':'end_turn'});self.assertTrue(good['accepted'])
        stale=self.command(m,{'type':'end_turn'})
        self.assertEqual(stale['command_error'],'stale_observation')
        self.assertEqual(self.request('view',{'viewer':2})[0],400)
        self.assertEqual(self.request('view',token='wrong')[0],403)
        self.assertEqual(self.request('view',origin='https://evil.example')[0],403)
    def test_constructed_complete_match(self):
        m=self.create('constructed'); kinds=set(); switches=0
        for _ in range(150):
            o=m['observation']
            if o['status']!='playing':break
            actor=o['pending_choice']['player_id'] if o['pending_choice'] else o['active_player']
            if actor!=m['seat']:m=self.switch(); switches+=1
            a=choose_action(m); kinds.add(a['type']);m=self.command(m,a)
            self.assertTrue(m['accepted'],m.get('command_error'))
        self.assertNotEqual(m['observation']['status'],'playing')
        self.assertTrue({'select_choice','play_card','attack','end_turn','use_hero_power'}<=kinds)
        self.assertGreater(switches,3)
    def test_transport_guards_and_static_files(self):
        self.assertEqual(self.request('view')[0],403)
        self.assertEqual(self.request('create',{'preset':'unknown'})[0],400)
        for path in ('/','/app.js','/style.css'):
            with urlopen(self.base+path) as r:
                self.assertEqual(r.status,200); self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('view',{'viewer':True})[0],403)
        with urlopen(self.base+'/app.js') as r:
            script=r.read().decode('utf-8-sig')
        self.assertNotIn('confirm(',script)
        self.assertIn("$('source').replaceChildren();$('type').replaceChildren();",script)

    def test_new_browser_and_expired_session_create_independent_matches(self):
        original=self.create(); original_token=self.token
        self.assertEqual(self.request('view',token='expired')[0],403)
        status,new=self.request('create',{'preset':'constructed'},token='expired')
        self.assertEqual(status,200); self.assertNotEqual(new['token'],original_token)
        self.token=new['token']
        new_view=self.request('view')[1]
        self.assertEqual(new_view['observation']['opening_stage'],'mulligan')
        self.assertEqual(self.request('view',token=original_token)[1],original)
        self.command(new_view,choose_action(new_view))
        self.assertEqual(self.request('view',token=original_token)[1],original)
        self.server.host.sessions.clear()  # Simulate a service restart.
        self.assertEqual(self.request('view')[0],403)
        self.create('practice')

    def test_local_art_static_boundary(self):
        for name in ('TheBox_Table', 'HERO_08', 'CS2_182'):
            with urlopen(self.base+'/assets/'+name+'.webp') as r:
                self.assertEqual(r.headers['Content-Type'],'image/webp')
                raw=r.read()
                self.assertEqual(raw[:4],b'RIFF')
                self.assertEqual(raw[8:12],b'WEBP')
        for path in ('/assets/manifest.json','/assets/../server.py','/assets/nonexistent.webp'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base+path)
            self.assertEqual(caught.exception.code,404)

    def test_test_mana_refill_payment_restore_and_replay_segments(self):
        from hs_sim.engine import Game
        from hs_sim.engine.replay import build_replay, replay
        from hs_sim.engine.representative import build_registry
        m = self.create()
        session = self.server.host.sessions[self.token]
        original = session.game.snapshot()
        self.assertEqual(m['test_controls'], {'mana_enabled': True, 'mana_reason': None, 'hand_enabled': True, 'hand_reason': None})
        status, m = self.request('test/mana', {'revision': m['revision'], 'mana': 4})
        self.assertEqual(status, 200)
        self.assertEqual((m['observation']['players'][0]['mana'], m['observation']['players'][0]['max_mana']), (4, 4))
        yeti = next(c['ref'] for c in m['observation']['players'][0]['hand'] if c['card_id'] == 'CS2_182')
        m = self.command(m, next(a for a in m['actions'] if a['type'] == 'play_card' and a['card'] == yeti))
        self.assertTrue(m['accepted'])
        self.assertEqual(m['observation']['players'][0]['mana'], 0)
        spent_snapshot = session.game.snapshot()
        stale_revision = m['revision']
        status, m = self.request('test/mana', {'revision': stale_revision, 'mana': 10})
        self.assertEqual(status, 200)
        self.assertEqual((m['observation']['players'][0]['mana'], m['observation']['players'][0]['max_mana']), (10, 10))
        self.assertEqual(session.game.state.players[1].mana_spent, 0)
        self.assertEqual(len(session.test_segments), 2)
        for segment, expected in zip(session.test_segments, (original, spent_snapshot)):
            self.assertEqual(replay(segment['replay'], build_registry()).snapshot(), expected)
        self.assertEqual(session.test_segments[-1]['after_hash'], session.game.state_hash())
        self.assertEqual(session.game.history, [])
        self.assertEqual(session.game.origin, session.game.snapshot())
        before = session.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': stale_revision, 'mana': 10}), (409, {'error': 'stale_observation'}))
        self.assertEqual(self.command({'revision': stale_revision}, {'type': 'end_turn'})['command_error'], 'stale_observation')
        self.assertEqual(before, session.game.snapshot())
        fireball = next(c['ref'] for c in m['observation']['players'][0]['hand'] if c['card_id'] == 'CS2_029')
        enemy_hero = m['observation']['players'][1]['hero']['ref']
        m = self.command(m, next(a for a in m['actions'] if a['type'] == 'play_card' and a['card'] == fireball and a.get('target') == enemy_hero))
        self.assertTrue(m['accepted'])
        self.assertEqual(m['observation']['players'][0]['mana'], 6)
        self.assertEqual(m['observation']['players'][1]['hero']['health'], 24)
        restored = Game.from_snapshot(json.loads(json.dumps(session.game.snapshot())), build_registry())
        for seat in (1, 2):
            self.assertEqual(restored.for_player(seat).observe(), session.game.for_player(seat).observe())
        self.assertEqual(replay(build_replay(session.game), build_registry()).snapshot(), session.game.snapshot())
        self.assertNotIn('test_segments', m)
        self.assertNotIn('origin', m)
        self.assertNotIn('FP1_007', m['names'])
        self.assertTrue(all(c['card_id'] is None for c in m['observation']['players'][1]['hand']))

    def test_test_mana_validation_isolation_and_rollback(self):
        from unittest.mock import patch
        m = self.create()
        token = self.token
        session = self.server.host.sessions[token]
        original = session.game.snapshot()
        for value in (-1, 11, True, None, '10', 10.0):
            self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': value}), (400, {'error': 'invalid_mana'}))
            self.assertEqual(session.game.snapshot(), original)
        for body in ({'revision': m['revision'], 'mana': 10, 'player_id': 2},
                     {'revision': m['revision'], 'mana': 10, 'viewer': 2},
                     {'revision': 'not-a-revision', 'mana': 10}, {'mana': 10}):
            self.assertEqual(self.request('test/mana', body), (400, {'error': 'invalid_request'}))
            self.assertEqual(session.game.snapshot(), original)
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}, token='wrong')[0], 403)
        with patch('web_ui.server.Game.from_snapshot', side_effect=ValueError('test restoration failure')):
            self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 3}), (500, {'error': 'host_error'}))
        self.assertEqual(session.game.snapshot(), original)
        self.assertEqual(session.test_segments, [])
        status, other = self.request('create', {'preset': 'practice'}, token='')
        self.assertEqual(status, 200)
        other_before = self.request('view', token=other['token'])[1]
        status, changed = self.request('test/mana', {'revision': m['revision'], 'mana': 0}, token=token)
        self.assertEqual(status, 200)
        self.assertEqual(changed['observation']['players'][0]['mana'], 0)
        self.assertEqual(changed['observation']['players'][1]['mana'], 10)
        self.assertEqual(self.request('view', token=other['token'])[1], other_before)

    def test_test_mana_rejects_opening_choice_inactive_handoff_and_ended(self):
        m = self.create('constructed')
        self.assertEqual(m['test_controls'], {'mana_enabled': False, 'mana_reason': 'opening_pending', 'hand_enabled': False, 'hand_reason': 'opening_pending'})
        before = self.server.host.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'opening_pending'}))
        self.assertEqual(before, self.server.host.game.snapshot())
        m = self.create()
        visions = next(c['ref'] for c in m['observation']['players'][0]['hand'] if c['card_id'] == 'UNG_029')
        m = self.command(m, next(a for a in m['actions'] if a['type'] == 'play_card' and a['card'] == visions))
        self.assertEqual(m['test_controls'], {'mana_enabled': False, 'mana_reason': 'choice_pending', 'hand_enabled': False, 'hand_reason': 'choice_pending'})
        before = self.server.host.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'choice_pending'}))
        self.assertEqual(before, self.server.host.game.snapshot())
        m = self.create()
        status, handoff = self.request('handoff')
        self.assertEqual(status, 200); self.token = handoff['token']
        before = self.server.host.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'handoff_pending'}))
        m = self.request('ready')[1]
        self.assertEqual(m['test_controls'], {'mana_enabled': False, 'mana_reason': 'not_your_turn', 'hand_enabled': False, 'hand_reason': 'not_your_turn'})
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'not_your_turn'}))
        self.assertEqual(before, self.server.host.game.snapshot())
        m = self.command(m, {'type': 'concede'})
        self.assertEqual(m['test_controls'], {'mana_enabled': False, 'mana_reason': 'game_not_playing', 'hand_enabled': False, 'hand_reason': 'game_not_playing'})
        before = self.server.host.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'game_not_playing'}))
        self.assertEqual(before, self.server.host.game.snapshot())

    def test_test_mana_preserves_special_accounts_and_cap(self):
        from hs_sim.engine import Game, PlayerSetup, Scenario
        self.create()
        session = self.server.host.sessions[self.token]
        for accounts in ({'temporary_mana': 2}, {'overload_locked': 2}, {'overload_owed': 2}):
            session.game = Game.from_scenario(Scenario((
                PlayerSetup('HERO_08', mana=3, max_mana=5, **accounts),
                PlayerSetup('HERO_01'),
            )), session.registry)
            m = self.request('view')[1]
            self.assertEqual(m['test_controls'], {'mana_enabled': False, 'mana_reason': 'special_mana_active', 'hand_enabled': True, 'hand_reason': None})
            before = session.game.snapshot()
            self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (409, {'error': 'special_mana_active'}))
            self.assertEqual(session.game.snapshot(), before)
        session.game = Game.from_scenario(Scenario((
            PlayerSetup('HERO_08', mana=3, max_mana=5, mana_cap=5), PlayerSetup('HERO_01'),
        )), session.registry)
        m = self.request('view')[1]; before = session.game.snapshot()
        self.assertEqual(self.request('test/mana', {'revision': m['revision'], 'mana': 10}), (400, {'error': 'mana_above_cap'}))
        self.assertEqual(session.game.snapshot(), before)

if __name__=='__main__':unittest.main()

