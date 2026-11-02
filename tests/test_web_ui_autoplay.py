"""Host-only integration: two projected bots, explicit partial verdicts, privacy."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from web_ui.autoplay import Controller, AuditHandler, write_json
from web_ui.autoplay_checks import evaluate

ROOT=Path(__file__).resolve().parents[1]


class Autoplay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.c=Controller(Path(cls.temp.name),ROOT/'web_ui/autoplay_decks.json',
                         seeds=[19],max_turns=1,max_steps=10)
        cls.c.start();cls.c.thread.join(timeout=90)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),AuditHandler);cls.server.controller=cls.c
        cls.http=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.http.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.http.join();cls.temp.cleanup()

    def request(self,path,body=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        req=Request(self.base+path,None if body is None else json.dumps(body).encode(),headers)
        try:
            with urlopen(req)as r:return r.status,r.read()
        except HTTPError as e:return e.code,e.read()

    def test_two_distinct_deck_orders_both_players_act(self):
        self.assertFalse(self.c.thread.is_alive())
        self.assertEqual(self.c.status,'finished')
        self.assertEqual([g['order']for g in self.c.games],[('shaman','priest'),('priest','shaman')])
        self.assertTrue(all(g['status']!='runner_error' for g in self.c.games))
        self.assertEqual({r['actor']for r in self.c.rows},{1,2})
        self.assertTrue(all(r['accepted']for r in self.c.rows))
        self.assertTrue(all(r['timings']['query_ms']>=0 and r['timings']['submit_ms']>=0 for r in self.c.rows))

    def test_browser_projection_has_no_opponent_hand_identity(self):
        for environment in ('A','B'):
            for seat in (1,2):
                data=self.c.views[environment][str(seat)]
                other=next(p for p in data['observation']['players']if p['id']!=seat)
                self.assertTrue(all(not c.get('card_id') or c['card_id']=='GAME_005' for c in other['hand']))
                self.assertNotIn('state',data);self.assertNotIn('rng_state',data)

    def test_private_files_not_http_routes_and_foreign_origin_rejected(self):
        self.assertEqual(self.request('/private/A-1-final-snapshot.json')[0],404)
        self.assertEqual(self.request('/audit/status',origin='https://example.com')[0],403)
        self.assertEqual(self.request('/audit/start',{'extra':1})[0],400)
        self.assertEqual(self.request('/audit/view?env=A&seat=1')[0],200)

    def test_report_is_partial_and_never_certifies_unplayed_card(self):
        report=self.c.make_report()
        self.assertTrue(all(c['verdict']in('partial','not_exercised')for c in report['coverage']))
        self.assertTrue(any(c['verdict']=='not_exercised'for c in report['coverage']))
        self.assertIn('partial',str(__import__('web_ui.autoplay_checks',fromlist=['x']).__doc__))

    def test_assembly_observer_can_load_public_catalog_but_not_submit_actions(self):
        status,raw=self.request('/api/catalog',{})
        self.assertEqual(status,200)
        self.assertIn('BE_114',{c['id']for c in json.loads(raw)['cards']})
        self.assertEqual(self.request('/api/action',{})[0],404)

    def test_missing_destroy_event_requires_review_and_locations_are_excluded(self):
        before={'entities':{1:{'kind':'minion','dormant':False,'attack':6,'silenced':False,'card_id':'example','controller':1},2:{'kind':'location','dormant':False,'attack':6,'silenced':False,'card_id':'example','controller':1}},
                'players':{1:{'board':[1]},2:{'board':[2]}},'active':1}
        after={**before,'pending':None}
        native=type('PlayCard',(),{'entity_id':10})()
        checks=evaluate('CORE_EX1_197',10,1,native,before,after,[],None)
        self.assertEqual(checks[0]['status'],'needs_review')
        self.assertEqual(checks[0]['evidence']['expected_original_victims'],[1])
        events=[{'kind':'minion_died','target_id':1,'source_id':1,'player_id':1}]
        self.assertEqual(evaluate('CORE_EX1_197',10,1,native,before,after,events,None)[0]['status'],'pass')

    def test_windows_temporary_report_lock_does_not_abort_write(self):
        original=Path.replace;attempts=[]
        def transient(path,target):
            attempts.append(1)
            if len(attempts)<3:raise PermissionError('simulated short Windows read lock')
            return original(path,target)
        target=Path(self.temp.name)/'retry.json'
        with patch.object(Path,'replace',transient):write_json(target,{'value':9})
        self.assertEqual(len(attempts),3)
        self.assertEqual(json.loads(target.read_text()),{'value':9})


if __name__=='__main__':unittest.main()
