"""Run with python -m web_ui.server. No third-party dependencies."""
import argparse
import json
import secrets
import threading
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from hs_sim.engine import Game, MatchSetup, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / 'static'

class Host:
    def __init__(self):
        self.lock = threading.RLock()
        self.registry = build_registry()
        self.game = None
        self.token = None
        self.seat = 1
        self.handoff = False
        self.sessions = {}

    def authorize(self, token):
        return bool(self.token and isinstance(token, str) and secrets.compare_digest(token, self.token))

    def create(self, preset):
        if preset == 'constructed':
            setup = MatchSetup.from_dict(json.loads((ROOT / 'examples/matches/constructed.json').read_text(encoding='utf-8')))
            game = Game.from_decks(setup, self.registry)
        elif preset == 'practice':
            game = Game.from_scenario(Scenario((
                PlayerSetup('HERO_08', hero_power_card_id='HERO_08bp', mana=10, max_mana=10,
                    hand=('UNG_029', 'CS2_182', 'CS2_029', 'CS2_024'),
                    deck=('CS2_179', 'CS2_182', 'EX1_019', 'CS2_029') * 3, board=('CS2_179',)),
                PlayerSetup('HERO_01', hero_power_card_id='HERO_01bp', mana=10, max_mana=10,
                    hand=('CS2_182', 'CS2_106', 'FP1_007'),
                    deck=('CS2_179', 'CS2_182', 'FP1_007', 'CS2_106') * 3, board=('CS2_182',)),
                ), seed=29, name='UI representative practice'), self.registry)
        else:
            raise ValueError('invalid_preset')
        self.game = game
        self.seat = 1
        self.handoff = False
        self.token = secrets.token_urlsafe(32)
        return {'token': self.token, 'seat': self.seat}

    def listing(self):
        if self.handoff:
            return {'handoff': True, 'seat': self.seat}
        port = self.game.for_player(self.seat)
        result = port.legal_actions()
        result['events'] = port.events()
        # Only names of identities already disclosed by this seat's DTO/logs.
        ids = set()
        def visit(value):
            if isinstance(value, dict):
                if isinstance(value.get('card_id'), str):
                    ids.add(value['card_id'])
                for child in value.values(): visit(child)
            elif isinstance(value, list):
                for child in value: visit(child)
        visit(result)
        result['names'] = {i: self.registry.card(i).name for i in ids}
        result['seat'] = self.seat
        return result

    def route(self, path, body, token):
        # A fresh browser creates its own match, never takes over another seat.
        with self.lock:
            session = self.sessions.get(token)
            if path == '/api/create':
                if set(body) != {'preset'}:
                    return 400, {'error': 'invalid_request'}
                session = session or Host()
                old_token = session.token
                try:
                    result = session.create(body['preset'])
                except ValueError:
                    return 400, {'error': 'invalid_preset'}
                self.sessions.pop(old_token, None)
                # Bound local demo memory; evicted clients can create a new match.
                if len(self.sessions) >= 32:
                    self.sessions.pop(next(iter(self.sessions)))
                self.sessions[session.token] = session
                self.game = session.game  # Trusted-host diagnostics only.
                return 200, result
            if session is None:
                return 403, {'error': 'seat_session_required'}
            status, result = session._route_session(path, body, token)
            if session.token != token:
                self.sessions.pop(token, None)
                self.sessions[session.token] = session
            return status, result

    def _route_session(self, path, body, token):
        with self.lock:
            if path == '/api/create':
                if self.game is not None and not self.authorize(token):
                    return 403, {'error': 'seat_session_required'}
                if set(body) != {'preset'}: return 400, {'error': 'invalid_request'}
                try: return 200, self.create(body['preset'])
                except ValueError: return 400, {'error': 'invalid_preset'}
            if not self.authorize(token): return 403, {'error': 'seat_session_required'}
            if path == '/api/view':
                if body: return 400, {'error': 'invalid_request'}
                return 200, self.listing()
            if path == '/api/handoff':
                if body or self.handoff: return 400, {'error': 'invalid_request'}
                self.seat = 3 - self.seat
                self.handoff = True
                self.token = secrets.token_urlsafe(32)
                return 200, {'token': self.token, 'seat': self.seat, 'handoff': True}
            if path == '/api/ready':
                if body or not self.handoff: return 400, {'error': 'invalid_request'}
                self.handoff = False
                return 200, self.listing()
            if path == '/api/action':
                if self.handoff: return 409, {'error': 'handoff_pending'}
                reply = self.game.for_player(self.seat).submit(body)
                result = self.listing()
                result.update(accepted=reply['accepted'], command_error=reply['error'])
                return 200, result
            return 404, {'error': 'not_found'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass  # Never log credentials or player commands.

    def send(self, status, data, mime='application/json; charset=utf-8'):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8') if mime.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def local_request(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != expected: return False
        origin = self.headers.get('Origin')
        return origin is None or origin == 'http://' + expected

    def do_GET(self):
        if not self.local_request(): return self.send(403, {'error': 'origin_rejected'})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if re.fullmatch(r'/assets/[A-Za-z0-9_]+\.webp', self.path):
            asset = STATIC / 'assets' / self.path.rsplit('/', 1)[1]
            if asset.is_file():
                return self.send(200, asset.read_bytes(), 'image/webp')
        if self.path not in files: return self.send(404, {'error': 'not_found'})
        name, mime = files[self.path]
        self.send(200, (STATIC / name).read_bytes(), mime)

    def do_POST(self):
        if not self.local_request(): return self.send(403, {'error': 'origin_rejected'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'json_required'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536: raise ValueError()
            body = json.loads(self.rfile.read(size))
            if type(body) is not dict: raise ValueError()
        except (ValueError, UnicodeError): return self.send(400, {'error': 'invalid_request'})
        token = self.headers.get('Authorization', '').removeprefix('Bearer ')
        try:
            status, result = self.server.host.route(self.path, body, token)
        except Exception:
            # Detailed exceptions and all-knowing engine values stay in host.
            status, result = 500, {'error': 'host_error'}
        self.send(status, result)

def make_server(port=8765):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.host = Host()
    return server

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.port)
    print(f'实验对战 UI：http://127.0.0.1:{server.server_port} （Ctrl+C 停止）', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()

