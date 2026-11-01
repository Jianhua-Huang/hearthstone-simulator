"""Local observability must preserve game behavior and keep credentials out of logs."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import json
import re
import threading
import time
import unittest

from web_ui import diagnostics as d
from web_ui.server import make_server, Host


class DiagnosticLogs(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.sink = d.JsonSink(self.temp.name, 12345)

    def tearDown(self):
        self.sink.close()
        self.temp.cleanup()

    def rows(self, kind):
        path = Path(self.temp.name) / f'{kind}-12345.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_scopes_reset_and_exception_messages_never_enter_logs(self):
        secret = 'AUTH-AND-HIDDEN-STATE-MUST-NOT-APPEAR'
        with d.RequestTrace('/api/action', 12345, 'a' * 32, self.sink) as trace:
            with d.span('command_submit_ms'):
                d.action({'type': 'play_card', 'authorization': secret})
            try:
                raise ValueError(secret)
            except ValueError as exc:
                trace.exception(exc)
            trace.status = 200
            self.assertRegex(trace.headers()['X-Request-ID'], r'^[0-9a-f]{32}$')
        self.assertIsNone(d.current())
        end = self.rows('server')[-1]
        self.assertEqual(end['action_type'], 'play_card')
        self.assertGreaterEqual(end['stages_ms']['command_submit_ms'], 0)
        self.assertGreaterEqual(end['wall_ms'], 0)
        self.assertGreaterEqual(end['thread_cpu_ms'], 0)
        self.assertEqual(self.rows('errors')[0]['error_class'], 'ValueError')
        self.assertNotIn(secret, ''.join(p.read_text(encoding='utf-8') for p in Path(self.temp.name).iterdir()))

    def test_invalid_telemetry_cannot_inject_arbitrary_payloads(self):
        good = {'ui_id': 'a'*32, 'request_id': 'b'*32, 'error_code':'invalid_action', 'stages_ms': {'http_ms': 4},
                'server_ms': {'command_submit_ms': 2}, 'scene': {'friendly_board': 4, 'enemy_board': 2}}
        with d.RequestTrace('/api/diagnostics/client', 12345, sink=self.sink):
            self.assertTrue(d.client_record(good))
            for update in ({'token': 'SECRET'}, {'stages_ms': {'http_ms': float('nan')}},
                           {'stages_ms': {'http_ms': -1}}, {'stages_ms': {'http_ms': True}},
                           {'server_ms': {'full_snapshot': 1}}, {'scene': {'deck': []}},
                           {'card_name': 'bad\nlog line'}, {'request_id': 'invalid'}):
                with self.subTest(update=update), self.assertRaises(ValueError):
                    d.client_record({**good, **update})
        self.assertEqual(len(self.rows('client')), 1)

    def test_thread_contexts_do_not_mix_requests(self):
        barrier = threading.Barrier(2)
        def run(kind):
            with d.RequestTrace('/api/action', 12345, sink=self.sink):
                d.action({'type': kind});barrier.wait()
                with d.span('command_submit_ms'): time.sleep(.005)
        threads = [threading.Thread(target=run, args=(kind,)) for kind in ('play_card', 'attack')]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        finished = [row for row in self.rows('server') if row['event'] == 'request_finished']
        self.assertEqual({row['action_type'] for row in finished}, {'play_card', 'attack'})
        self.assertEqual(len({row['request_id'] for row in finished}), 2)
        self.assertIsNone(d.current())

    def test_rotation_bounds_files_and_io_failure_is_nonfatal(self):
        self.sink.write('server', {'event': 'initial'})
        self.sink.handlers['server'].maxBytes = 250
        for index in range(30): self.sink.write('server', {'index': index, 'text': 'x'*100})
        self.assertLessEqual(len(list(Path(self.temp.name).glob('server-*'))), 3)
        blocker = Path(self.temp.name) / 'not-a-directory';blocker.write_text('x')
        broken = d.JsonSink(blocker, 1)
        self.assertFalse(broken.write('server', {'safe': True}))
        self.assertEqual(broken.dropped, 1)

    def test_traced_and_untraced_commands_have_identical_results(self):
        host = Host();_,created = host.route('/api/create', {'preset':'practice'}, '')
        token = created['token'];session = host.sessions[token]
        _,before = host.route('/api/view', {}, token)
        saved = session.game.clone()
        ref = next(c['ref'] for c in before['observation']['players'][0]['hand'] if c['card_id']=='CS2_182')
        action = next(a for a in before['actions'] if a['type']=='play_card' and a['card']==ref)
        command = {'revision':before['revision'], 'action':action}
        _,plain = host.route('/api/action', command, token);plain_state = session.game.snapshot()
        session.game = host.game = saved
        with d.RequestTrace('/api/action', 12345, sink=self.sink):
            _,traced = host.route('/api/action', command, token)
        self.assertEqual(session.game.snapshot(), plain_state)
        plain = deepcopy(plain);traced = deepcopy(traced)
        plain['opponent'].pop('ticket');traced['opponent'].pop('ticket')
        self.assertEqual(plain, traced)
        stages = self.rows('server')[-1]['stages_ms']
        self.assertTrue({'command_submit_ms','legal_actions_ms','events_ms','view_enrichment_ms'} <= stages.keys())

    def test_ai_query_policy_and_submission_are_separate_timings(self):
        host=Host();_,created=host.route('/api/create',{'preset':'practice','opponent':'ai'},'')
        token=created['token'];_,view=host.route('/api/view',{},token)
        _,view=host.route('/api/action',{'revision':view['revision'],'action':{'type':'end_turn'}},token)
        self.assertTrue(view['opponent']['can_step'])
        with d.RequestTrace('/api/opponent/step',12345,sink=self.sink):
            _,after=host.route('/api/opponent/step',{'revision':view['revision'],'ticket':view['opponent']['ticket']},token)
        self.assertTrue(after['opponent_acted'])
        row=self.rows('server')[-1]
        self.assertTrue({'ai_legal_actions_ms','ai_policy_ms','command_submit_ms','legal_actions_ms'} <= row['stages_ms'].keys())
        self.assertIn('action_type',row)


class DiagnosticHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.server = make_server(0)
        cls.sink = d.JsonSink(cls.temp.name, cls.server.server_port)
        cls.server.diagnostic_sink = cls.sink
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True);cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.sink.close();cls.temp.cleanup()

    def call(self, path, body=None, token=''):
        req = Request(self.base+'/api/'+path, json.dumps(body or {}).encode(),
            {'Content-Type':'application/json','Authorization':'Bearer '+token,'X-UI-Trace-ID':'a'*32})
        try:
            with urlopen(req) as response:return response.status,dict(response.headers),json.load(response)
        except HTTPError as response:return response.code,dict(response.headers),json.load(response)

    def test_http_headers_correlate_action_with_local_logs(self):
        _,_,created = self.call('create', {'preset':'practice'});token = created['token']
        _,_,view = self.call('view', token=token)
        ref = next(c['ref'] for c in view['observation']['players'][0]['hand'] if c['card_id']=='CS2_182')
        action = next(a for a in view['actions'] if a['type']=='play_card' and a['card']==ref)
        status,headers,after = self.call('action', {'revision':view['revision'],'action':action},token)
        self.assertEqual(status,200);self.assertTrue(after['accepted'])
        self.assertEqual(headers['X-UI-Diagnostics'],'1')
        self.assertRegex(headers['X-Request-ID'],r'^[0-9a-f]{32}$')
        self.assertIn('command_submit_ms;dur=',headers['Server-Timing'])
        self.assertIn('legal_actions_ms;dur=',headers['Server-Timing'])
        payload={'ui_id':'a'*32,'request_id':headers['X-Request-ID'],'path':'action',
                 'card_id':'CS2_182','card_name':'冰风雪人','stages_ms':{'http_ms':20,'outcome_ms':320},
                 'scene':{'friendly_board':1,'enemy_board':1}}
        status,_,reply = self.call('diagnostics/client',payload,token)
        self.assertEqual((status,reply),(200,{'recorded':True}))
        self.assertEqual(self.call('diagnostics/client',payload,'invalid')[0],403)
        self.assertEqual(self.call('diagnostics/client',{**payload,'token':token},token)[0],400)
        raw=''.join(p.read_text(encoding='utf-8') for p in Path(self.temp.name).iterdir())
        self.assertNotIn(token,raw)
        self.assertIn(headers['X-Request-ID'],raw)
        self.assertNotIn('"observation"',raw)

    def test_host_failure_is_logged_without_exposing_message_or_state(self):
        with patch.object(self.server.host,'route',side_effect=RuntimeError('PRIVATE-CREDENTIAL')):
            status,headers,reply = self.call('view')
        self.assertEqual((status,reply),(500,{'error':'host_error'}))
        path=Path(self.temp.name)/f'errors-{self.server.server_port}.jsonl'
        raw=path.read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE-CREDENTIAL',raw)
        self.assertIn(headers['X-Request-ID'],raw)
        self.assertIn('RuntimeError',raw)
