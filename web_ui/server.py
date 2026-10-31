"""Run with python -m web_ui.server. No third-party dependencies."""
import argparse
import json
import secrets
import threading
import re
import random
import html
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, MatchSetup, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry, CARD_LIMITATIONS, PACKAGE_LIMITATIONS
from hs_sim.engine.effects import AddToHand, ChangeManaCrystals, RefreshMana
from hs_sim.engine.replay import build_replay
from hs_sim.engine.resolver import Resolution
from hs_sim.targets import canonical_digest, load_baseline
from hs_sim.engine.dark_gift_cards import INVENTORY_HASH
from .bot import BotError, actor_for, choose_action

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).parent / 'static'
BOT_ACTION_BUDGET = 24
BOT_STEP_LIMIT = 64

def plain_card_text(text):
    text = re.sub(r'<[^>]*>', '', text or '').replace('[x]', '')
    return re.sub(r'[$#](?=\d)', '', html.unescape(text)).strip()


@lru_cache(maxsize=1)
def printed_metadata():
    """Static pinned records, never identities taken from a live match."""
    baseline = load_baseline()
    rows = {row['id']: (row['data'], row.get('notes', '')) for row in baseline.support['cards']}
    gifts = json.loads((ROOT / 'data/support/dark-gifts-core.json').read_text(encoding='utf-8'))
    if canonical_digest(gifts) != INVENTORY_HASH:
        raise ValueError('Card catalog requires pinned Dark Gift records')
    for row in gifts['records']:
        rows.setdefault(row['id'], (row, '黑暗之赐实验包：发现随从池仅含四张代表；正式完整卡池和国服时序尚未校准。'))
    return baseline.target['target_id'], rows


def hand_card_disabled_reason(card):
    if card.choice_only: return 'choice_only'
    if not card.hand_playable: return 'card_not_hand_playable'
    if card.starship_for: return 'special_card_template'
    return None


class Host:
    def __init__(self):
        self.lock = threading.RLock()
        self.registry = build_registry()
        self.game = None
        self.token = None
        self.seat = 1
        self.handoff = False
        self.sessions = {}
        self.test_segments = []  # Trusted-host replay branches; never player DTOs.
        self.opponent_mode = 'human'
        self.opponent_error = None
        self.opponent_window = None
        self.opponent_steps = 0
        self.opponent_choice_steps = 0
        self.opponent_rng = random.Random(73)
        self.opponent_ticket = secrets.token_urlsafe(24)

    def authorize(self, token):
        return bool(self.token and isinstance(token, str) and secrets.compare_digest(token, self.token))

    def create(self, preset, opponent='human'):
        if type(opponent) is not str or opponent not in ('human', 'ai'):
            raise ValueError('invalid_opponent')
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
                ), seed=29, name='UI representative practice',
                generation_context=GenerationContext(printed_metadata()[0], 'experimental')), self.registry)
        else:
            raise ValueError('invalid_preset')
        self.game = game
        self.seat = 1
        self.handoff = False
        self.test_segments = []
        self.opponent_mode = opponent
        self.opponent_error = None
        self.opponent_window = None
        self.opponent_steps = 0
        self.opponent_choice_steps = 0
        self.opponent_rng = random.Random(73)
        self.refresh_opponent_ticket()
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
        records = getattr(self, 'lab_records', None) or printed_metadata()[1]
        result['card_texts'] = {i: plain_card_text(records.get(i, ({}, ''))[0].get('text', '')) for i in ids}
        result['card_art'] = {i: i+'.webp' for i in ids if (STATIC/'assets'/(i+'.webp')).is_file()}
        result['seat'] = self.seat
        reason = self.mana_disabled_reason(result['observation'])
        hand_reason = self.hand_disabled_reason(result['observation'])
        result['test_controls'] = {'mana_enabled': reason is None, 'mana_reason': reason,
                                   'hand_enabled': hand_reason is None, 'hand_reason': hand_reason}
        result['opponent'] = self.opponent_status(result['observation'])
        return result

    def catalog(self):
        records = getattr(self, 'lab_records', None) or printed_metadata()[1]
        cards = []
        for cid, card in sorted(self.registry.cards.items()):
            raw, note = records.get(cid, ({}, '内部测试定义，没有正式卡牌原文。'))
            reason = hand_card_disabled_reason(card)
            cards.append({'id': cid, 'name': card.name, 'type': card.kind.value,
                          'cost': card.cost, 'cost_resource': card.cost_payment.value,
                          'text': plain_card_text(raw.get('text', '')),
                          'can_add': reason is None, 'disabled_reason': reason,
                          'note': CARD_LIMITATIONS.get(cid, note)})
        return {'scope': 'experimental_registry', 'registry_version': self.registry.version,
                'scope_note': '这里列出已注册的实验代表卡，不是完整炉石卡池；可加入手牌不代表该卡所有规则已完整实现或经官方验证。加入会生成一张新牌，不消耗牌库。',
                'package_limitations': list(PACKAGE_LIMITATIONS),
                'total': len(cards), 'addable_count': sum(c['can_add'] for c in cards), 'cards': cards}

    def refresh_opponent_ticket(self):
        # Observable engine revisions may stay equal across private AI choices.
        # An independent one-use host ticket prevents duplicate step/config posts.
        self.opponent_ticket = secrets.token_urlsafe(24)

    def opponent_status(self, observation):
        seat = 3 - self.seat
        return {'mode': self.opponent_mode, 'seat': seat, 'error': self.opponent_error,
                'ticket': self.opponent_ticket,
                'can_step': bool(self.opponent_mode == 'ai' and not self.handoff
                    and self.opponent_error is None and observation['status'] == 'playing'
                    and actor_for(observation) == seat)}

    def validate_opponent_control(self, body, fields):
        if self.handoff: return 409, {'error': 'handoff_pending'}
        if set(body) != fields or type(body.get('revision')) is not str or type(body.get('ticket')) is not str:
            return 400, {'error': 'invalid_request'}
        if (re.fullmatch(r'[0-9a-f]{64}', body['revision']) is None
                or re.fullmatch(r'[A-Za-z0-9_-]{32}', body['ticket']) is None):
            return 400, {'error': 'invalid_request'}
        if body['revision'] != self.game.for_player(self.seat).observe()['revision']:
            return 409, {'error': 'stale_observation'}
        if not secrets.compare_digest(body['ticket'], self.opponent_ticket):
            return 409, {'error': 'stale_opponent_step'}
        return None

    def configure_opponent(self, body):
        rejected = self.validate_opponent_control(body, {'revision', 'ticket', 'mode'})
        if rejected: return rejected
        if type(body['mode']) is not str or body['mode'] not in ('human', 'ai'):
            return 400, {'error': 'invalid_opponent'}
        self.opponent_mode = body['mode']
        self.opponent_error = None
        self.opponent_window = None
        self.opponent_steps = 0
        self.opponent_choice_steps = 0
        self.refresh_opponent_ticket()
        return 200, self.listing()

    def step_opponent(self, body):
        rejected = self.validate_opponent_control(body, {'revision', 'ticket'})
        if rejected: return rejected
        observation = self.game.for_player(self.seat).observe()['observation']
        if self.opponent_mode != 'ai': return 409, {'error': 'opponent_disabled'}
        if self.opponent_error is not None: return 409, {'error': 'opponent_paused'}
        if not self.opponent_status(observation)['can_step']:
            return 409, {'error': 'opponent_not_acting'}
        window = (observation['turn'], observation['active_player'])
        if window != self.opponent_window:
            self.opponent_window, self.opponent_steps = window, 0
            self.opponent_choice_steps = 0
        rng_before = self.opponent_rng.getstate()
        acted = False
        try:
            if observation['pending_choice'] is not None and self.opponent_choice_steps >= BOT_STEP_LIMIT:
                raise BotError('action_budget_exhausted')
            port = self.game.for_player(3 - self.seat)
            message = port.legal_actions()
            action = choose_action(message, self.opponent_rng,
                                   force_end=self.opponent_steps >= BOT_ACTION_BUDGET)
            reply = port.submit({'revision': message['revision'], 'action': action})
            if not reply['accepted']: raise BotError('command_rejected')
            acted = True
            if action['type'] == 'select_choice':
                self.opponent_choice_steps += 1
            else:
                self.opponent_steps += 1
        except BotError as exc:
            self.opponent_error = exc.code
        except Exception:
            self.opponent_error = 'opponent_failed'
        if not acted:
            self.opponent_rng.setstate(rng_before)
        self.refresh_opponent_ticket()
        result = self.listing()
        result['opponent_acted'] = acted
        return 200, result

    def test_window_disabled_reason(self, observation):
        if observation['status'] != 'playing': return 'game_not_playing'
        if observation['opening_stage'] not in (None, 'complete'): return 'opening_pending'
        if observation['pending_choice'] is not None: return 'choice_pending'
        if observation['active_player'] != self.seat: return 'not_your_turn'
        return None

    def hand_disabled_reason(self, observation):
        reason = self.test_window_disabled_reason(observation)
        if reason: return reason
        player = next(p for p in observation['players'] if p['id'] == self.seat)
        if len(player['hand']) >= player['hand_cap']: return 'hand_full'
        return None

    def mana_disabled_reason(self, observation):
        reason = self.test_window_disabled_reason(observation)
        if reason: return reason
        player = next(p for p in observation['players'] if p['id'] == self.seat)
        if any(player[k] for k in ('temporary_mana', 'overload_locked', 'overload_owed')):
            return 'special_mana_active'
        return None

    def set_test_mana(self, body):
        """Change a local test fixture through the resolver, then start a replay segment.

        This is a trusted-host test tool, not a new player action or game rule.
        Existing accepted actions keep their original replay; only the fully
        validated new boundary becomes the origin of subsequent player actions.
        """
        if self.handoff: return 409, {'error': 'handoff_pending'}
        if set(body) != {'revision', 'mana'}: return 400, {'error': 'invalid_request'}
        if type(body['mana']) is not int or not 0 <= body['mana'] <= 10:
            return 400, {'error': 'invalid_mana'}
        if type(body['revision']) is not str or re.fullmatch(r'[0-9a-f]{64}', body['revision']) is None:
            return 400, {'error': 'invalid_request'}
        before = self.game.for_player(self.seat).observe()
        if body['revision'] != before['revision']: return 409, {'error': 'stale_observation'}
        reason = self.mana_disabled_reason(before['observation'])
        if reason: return 409, {'error': reason}
        player = self.game.state.players[self.seat]
        if body['mana'] > player.mana_cap: return 400, {'error': 'mana_above_cap'}
        working = self.game.clone()
        working._resolving = True
        working._state.action_number += 1
        try:
            Resolution(working).run([
                ChangeManaCrystals(self.seat, body['mana'] - player.max_mana, filled=True),
                RefreshMana(self.seat, player.mana_spent),
            ])
            working._information.sync(working)
            working._assert_stable()
        finally:
            working._resolving = False
        adjusted = working.state.players[self.seat]
        # A future registered reaction must not silently turn this tool into a
        # partially resolved or different-value adjustment.
        if (working.state.pending_choice is not None or working.state.status != 'playing'
                or (adjusted.mana, adjusted.max_mana) != (body['mana'], body['mana'])):
            return 409, {'error': 'test_adjustment_unavailable'}
        replacement = Game.from_snapshot(working.snapshot(), self.registry)
        segment = {'replay': build_replay(self.game),
                   'adjustment': {'type': 'set_mana', 'player_id': self.seat, 'mana': body['mana']},
                   'after_hash': replacement.state_hash()}
        self.test_segments.append(segment)
        self.game = replacement
        self.refresh_opponent_ticket()
        result = self.listing()
        result['test_adjustment'] = {'type': 'set_mana', 'mana': body['mana']}
        return 200, result

    def add_test_hand(self, body):
        """Generate one private card on a clone and preserve the old replay branch."""
        if self.handoff: return 409, {'error': 'handoff_pending'}
        if (set(body) != {'revision', 'card_id'} or type(body['card_id']) is not str
                or type(body['revision']) is not str
                or re.fullmatch(r'[0-9a-f]{64}', body['revision']) is None):
            return 400, {'error': 'invalid_request'}
        before = self.game.for_player(self.seat).observe()
        if body['revision'] != before['revision']: return 409, {'error': 'stale_observation'}
        reason = self.hand_disabled_reason(before['observation'])
        if reason: return 409, {'error': reason}
        card = self.registry.cards.get(body['card_id'])
        if card is None: return 400, {'error': 'unknown_card'}
        reason = hand_card_disabled_reason(card)
        if reason: return 400, {'error': reason}
        working = self.game.clone()
        working._resolving = True
        working._state.action_number += 1
        try:
            Resolution(working).run([AddToHand(self.seat, card.id)])
            working._information.sync(working)
            working._assert_stable()
        except Exception:
            return 409, {'error': 'test_hand_adjustment_unavailable'}
        finally:
            working._resolving = False
        if working.state.pending_choice is not None or working.state.status != 'playing':
            return 409, {'error': 'test_hand_adjustment_unavailable'}
        try:
            replacement = Game.from_snapshot(working.snapshot(), self.registry)
            segment = {'replay': build_replay(self.game),
                       'adjustment': {'type': 'add_to_hand', 'player_id': self.seat, 'card_id': card.id},
                       'after_hash': replacement.state_hash()}
        except Exception:
            return 409, {'error': 'test_hand_adjustment_unavailable'}
        self.test_segments.append(segment)
        self.game = replacement
        self.refresh_opponent_ticket()
        result = self.listing()
        result['test_adjustment'] = {'type': 'add_to_hand', 'card_id': card.id, 'name': card.name}
        return 200, result

    def route(self, path, body, token):
        # A fresh browser creates its own match, never takes over another seat.
        with self.lock:
            if path.startswith('/api/lab/'):
                from .card_lab import route as lab_route
                return lab_route(self, path, body, token)
            if path == '/api/catalog':
                if body: return 400, {'error': 'invalid_request'}
                return 200, (self.sessions.get(token) or self).catalog()
            session = self.sessions.get(token)
            if path == '/api/create':
                if 'preset' not in body or set(body) - {'preset', 'opponent'}:
                    return 400, {'error': 'invalid_request'}
                if type(body.get('opponent', 'human')) is not str or body.get('opponent', 'human') not in ('human', 'ai'):
                    return 400, {'error': 'invalid_opponent'}
                session = session or Host()
                old_token = session.token
                try:
                    result = session.create(body['preset'], body.get('opponent', 'human'))
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
            old_game = session.game
            status, result = session._route_session(path, body, token)
            if self.game is old_game:
                self.game = session.game
            if session.token != token:
                self.sessions.pop(token, None)
                self.sessions[session.token] = session
            return status, result

    def _route_session(self, path, body, token):
        with self.lock:
            if not self.authorize(token): return 403, {'error': 'seat_session_required'}
            if path == '/api/view':
                if body: return 400, {'error': 'invalid_request'}
                return 200, self.listing()
            if path == '/api/handoff':
                if body or self.handoff: return 400, {'error': 'invalid_request'}
                if self.opponent_mode == 'ai': return 409, {'error': 'opponent_controls_seat'}
                self.seat = 3 - self.seat
                self.handoff = True
                self.token = secrets.token_urlsafe(32)
                self.refresh_opponent_ticket()
                return 200, {'token': self.token, 'seat': self.seat, 'handoff': True}
            if path == '/api/ready':
                if body or not self.handoff: return 400, {'error': 'invalid_request'}
                self.handoff = False
                return 200, self.listing()
            if path == '/api/action':
                if self.handoff: return 409, {'error': 'handoff_pending'}
                reply = self.game.for_player(self.seat).submit(body)
                if hasattr(self, 'lab_context'):
                    from .card_lab import note_action
                    note_action(self, body.get('action',{}), reply['accepted'])
                if reply['accepted']: self.refresh_opponent_ticket()
                result = self.listing()
                result.update(accepted=reply['accepted'], command_error=reply['error'])
                return 200, result
            if path == '/api/test/mana':
                return self.set_test_mana(body)
            if path == '/api/test/hand':
                return self.add_test_hand(body)
            if path == '/api/opponent':
                return self.configure_opponent(body)
            if path == '/api/opponent/step':
                return self.step_opponent(body)
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
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'self'; base-uri 'none'")
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
        files.update({'/lab':('lab.html','text/html; charset=utf-8'), '/lab.js':('lab.js','text/javascript; charset=utf-8'), '/lab.css':('lab.css','text/css; charset=utf-8')})
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

