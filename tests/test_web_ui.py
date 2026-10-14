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

if __name__=='__main__':unittest.main()

