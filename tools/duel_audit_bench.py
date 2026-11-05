"""Fixed native/production HTTP cold+warm checks against an immutable source.

Use identical fixture JSON for both versions. Three ordinary samples per mode;
GC stays enabled, no profiler. Registry loaded, candidate/material caches cold.
"""
from pathlib import Path
import argparse
import gc
import gzip
import hashlib
import json
import statistics
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from duel_audit import read, write, digest, file_hash, set_affinity
from duel_audit_host import make_host


def measure(fn):
    wall, cpu = time.perf_counter(), time.thread_time()
    value = fn()
    return value, {'wall_ms': (time.perf_counter() - wall) * 1000,
                   'cpu_ms': (time.thread_time() - cpu) * 1000}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--fixture', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--samples', type=int, default=3)
    p.add_argument('--cpu-mask', type=int, default=1); p.add_argument('--http', action='store_true')
    a = p.parse_args(); source, output = a.source.resolve(), a.output.resolve()
    set_affinity(a.cpu_mask); output.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(source)); sys.path.insert(0, str(source / 'tools'))
    import duel_audit_runtime as runtime
    from hs_sim.engine import assembly_materials, playable_spell_generation
    from web_ui import server as ui, diagnostics
    assert runtime.ROOT == source
    ui.STATIC = Path(__file__).resolve().parents[1] / 'web_ui/static'
    manifest = read(source.parent / 'source-manifest.json')['files']
    assert all(file_hash(source / name) == sha for name, sha in manifest.items()), 'Frozen source changed'
    fixture = read(a.fixture); c = runtime.catalog(output, 'bench', Path(fixture['decks']))
    load = lambda path: json.loads(gzip.decompress(Path(path).read_bytes()))
    before, after = load(fixture['before']), load(fixture['after'])
    actor, action = fixture['actor'], fixture['action']; assert gc.isenabled()
    base = runtime.Game.from_snapshot(before, c.registry, mode='release'); assert base.snapshot() == before
    def clear(game):
        with assembly_materials._lock: assembly_materials._owners.clear()
        with playable_spell_generation._LOCK: playable_spell_generation._CACHE.clear()
        if hasattr(game, '_frame_encoding'): game._frame_encoding = None
    def signatures(game, view, reply):
        snap = game.snapshot(); assert snap == after
        assert reply['accepted'] == fixture.get('accepted', True)
        players = [game.for_player(i).legal_actions() for i in (1, 2)]
        return {'snapshot': digest(snap), 'reply': digest(reply), 'rng': digest(snap['rng_state']),
                'initial_query': digest(view), 'both_players': digest(players)}, players
    report = {'success': False, 'source': str(source), 'fixture': str(a.fixture.resolve()),
              'fixture_sha256': file_hash(a.fixture), 'harness_sha256': file_hash(__file__),
              'host_adapter_sha256': file_hash(Path(__file__).with_name('duel_audit_host.py')),
              'cpu_mask': a.cpu_mask, 'gc_enabled': gc.isenabled(), 'samples': [], 'http_samples': [],
              'cold_policy': 'registry/code loaded; clear material, candidate and per-game encoded frame caches independently before query and submit',
              'limits': ['No profiler samples. Clone, snapshots and assertions outside native timing.',
                         'Small samples are not P95; background load not fully isolated.']}
    expected = None
    for mode in ('cold', 'warm'):
        for index in range(a.samples):
            game = base.clone()
            if mode == 'cold': clear(game)
            view, query = measure(game.for_player(actor).legal_actions)
            command = {'revision': view['revision'], 'action': action}
            if mode == 'cold': clear(game)
            reply, submit = measure(lambda: game.for_player(actor).submit(command))
            signature, players = signatures(game, view, reply)
            if expected is None: expected = signature
            assert signature == expected, 'Ordinary samples differ'
            row = {'mode': mode, 'index': index, 'query': query, 'submit': submit, 'signature': signature}
            report['samples'].append(row); write(output / 'progress.json', report)
    report['signature'] = expected
    if a.http:
        router = make_host(ui, c.registry, c.records)
        server = ThreadingHTTPServer(('127.0.0.1', 0), ui.Handler); server.host = router; server.daemon_threads = True
        server.diagnostic_sink = diagnostics.JsonSink(output / 'http-logs', server.server_port)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        def post(route, body, token):
            req = Request(f'http://127.0.0.1:{server.server_port}' + route, json.dumps(body).encode(),
                          {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
            start = time.perf_counter()
            with urlopen(req, timeout=90) as response: raw = response.read(); headers = response.headers
            elapsed = (time.perf_counter() - start) * 1000; begin = time.perf_counter(); value = json.loads(raw)
            timings = {k: float(v) for part in headers.get('Server-Timing', '').split(',')
                       for k, sep, v in [part.strip().partition(';dur=')] if sep}
            return value, {'http_ms': elapsed, 'decode_ms': (time.perf_counter() - begin) * 1000,
                           'server': timings, 'bytes': len(raw), 'request_id': headers.get('X-Request-ID')}
        try:
            for mode in ('cold', 'warm'):
                for index in range(a.samples):
                    game = base.clone(); session = make_host(ui, c.registry, c.records, game, actor)
                    router.sessions = {session.token: session}
                    if mode == 'cold': clear(game)
                    view, query = post('/api/view', {}, session.token)
                    if mode == 'cold': clear(game)
                    reply, submit = post('/api/action', {'revision': view['revision'], 'action': action}, session.token)
                    assert game.snapshot() == after and reply['accepted'] == fixture.get('accepted', True)
                    assert reply['observation'] == players[actor - 1]['observation']
                    normalized = json.loads(json.dumps(reply)); normalized.get('opponent', {}).pop('ticket', None)
                    normalized_view = json.loads(json.dumps(view)); normalized_view.get('opponent', {}).pop('ticket', None)
                    row = {'mode': mode, 'index': index, 'query': query, 'submit': submit,
                           'reply_sha256': digest(reply), 'observation_sha256': digest(reply['observation']),
                           'normalized_reply_sha256': digest(normalized), 'normalized_query_sha256': digest(normalized_view),
                           'normalization': 'Only random host opponent ticket removed; all other response fields retained',
                           'full_snapshot_equal': True}
                    report['http_samples'].append(row); write(output / 'progress.json', report)
        finally:
            server.shutdown(); server.server_close(); thread.join(); server.diagnostic_sink.close()
    report['loaded_modules'] = {n: m.__file__ for n, m in list(sys.modules.items())
                                if n.startswith(('hs_sim', 'web_ui')) and getattr(m, '__file__', None)}
    assert all(Path(path).resolve().is_relative_to(source) for path in report['loaded_modules'].values())
    assert all(file_hash(source / name) == sha for name, sha in manifest.items()), 'Frozen source changed during benchmark'
    report['source_guard'] = True
    report['native'] = {mode: {stage: statistics.median(r[stage]['wall_ms'] for r in report['samples'] if r['mode'] == mode)
                                for stage in ('query', 'submit')} for mode in ('cold', 'warm')}
    report['success'] = True; write(output / 'result.json', report)
    print(json.dumps({'success': True, 'native': report['native']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
