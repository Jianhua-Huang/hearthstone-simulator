"""Serve a new isolated test UI using a finished audit's frozen engine."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import argparse
import sys
from duel_audit import read, write, file_hash, set_affinity
from duel_audit_host import playable_classes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fixtures', type=Path, required=True); p.add_argument('--port', type=int, required=True)
    p.add_argument('--cpu-mask', type=int, default=16)
    p.add_argument('--title', default='炉石测试台')
    a = p.parse_args(); batch, output = a.batch.resolve(), a.output.resolve()
    assert not output.exists(); output.mkdir(parents=True); set_affinity(a.cpu_mask)
    identity = read(batch / 'identity.json'); source = Path(identity['source'])
    sys.path.insert(0, str(source)); sys.path.insert(0, str(source / 'tools'))
    import duel_audit_runtime as runtime
    from web_ui import server as ui, diagnostics
    assert runtime.ROOT == source and runtime.CORE_EFFECTS_VERSION == identity['core']
    static = Path(__file__).resolve().parents[1] / 'web_ui/static'; ui.STATIC = static
    controller = runtime.catalog(output, 'ui', batch / 'plans/pair-1.json')
    fixtures = read(a.fixtures)
    PlayHost, Handler, labels = playable_classes(ui, runtime, controller, batch, fixtures, static, a.title)
    ui.Host = PlayHost
    server = ThreadingHTTPServer(('127.0.0.1', a.port), Handler); server.host = PlayHost(); server.daemon_threads = True
    server.diagnostic_sink = diagnostics.JsonSink(output / 'http-logs', a.port)
    modules = {n: m.__file__ for n, m in list(sys.modules.items()) if n.startswith(('hs_sim', 'web_ui')) and getattr(m, '__file__', None)}
    assert all(Path(f).resolve().is_relative_to(source) for f in modules.values())
    write(output / 'server.json', {'url': f'http://127.0.0.1:{a.port}/', 'identity': identity,
                                  'presets': labels, 'fixtures': fixtures, 'actual_loaded_modules': modules,
                                  'harness_sha256': file_hash(__file__),
                                  'frontend_files': {p.name: file_hash(p) for p in static.iterdir() if p.is_file()},
                                  'original_services_untouched': True})
    print('Ready http://127.0.0.1:' + str(a.port) + '/', flush=True)
    try: server.serve_forever()
    finally: server.server_close(); server.diagnostic_sink.close()


if __name__ == '__main__': main()
