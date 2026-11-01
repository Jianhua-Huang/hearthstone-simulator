"""Bounded local timing logs. Never accepts game state or authorization headers."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
import json
import logging
import math
import os
import re
import secrets
import threading
import time
import traceback

_current = ContextVar('web_ui_request_trace', default=None)
_sinks = {}
_sink_lock = threading.Lock()


class JsonSink:
    def __init__(self, directory, port):
        self.directory = Path(directory)
        self.port = port
        self.handlers = {}
        self.lock = threading.Lock()
        self.dropped = 0

    def write(self, kind, record):
        try:
            raw = json.dumps(record, ensure_ascii=False, allow_nan=False)
            with self.lock:
                handler = self.handlers.get(kind)
                if handler is None:
                    self.directory.mkdir(parents=True, exist_ok=True)
                    handler = RotatingFileHandler(self.directory / f'{kind}-{self.port}.jsonl',
                        maxBytes=5 * 1024 * 1024, backupCount=2, encoding='utf-8')
                    handler.setFormatter(logging.Formatter('%(message)s'))
                    self.handlers[kind] = handler
                # Call the handler directly: application/global logging settings cannot suppress it.
                handler.handle(logging.LogRecord('web_ui_timing', logging.INFO, '', 0, raw, (), None))
            return True
        except Exception:
            self.dropped += 1
            return False  # A logging failure must not change an accepted game command.

    def close(self):
        with self.lock:
            for handler in self.handlers.values():
                handler.close()
            self.handlers.clear()


def sink_for(port):
    directory = os.environ.get('HS_UI_LOG_DIR') or str(Path(__file__).resolve().parents[1] / 'outputs/web-ui-logs')
    key = (directory, port)
    with _sink_lock:
        if key not in _sinks:
            _sinks[key] = JsonSink(directory, port)
        return _sinks[key]


def current():
    return _current.get()


def add(name, milliseconds):
    trace = current()
    if trace is not None:
        trace.stages[name] = trace.stages.get(name, 0) + milliseconds


@contextmanager
def span(name):
    if current() is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        add(name, (time.perf_counter() - started) * 1000)


@contextmanager
def timed_lock(lock, name):
    started = time.perf_counter()
    with lock:
        add(name, (time.perf_counter() - started) * 1000)
        yield


def action(value):
    trace = current()
    if trace is not None and type(value) is dict:
        kind = value.get('type')
        if type(kind) is str and re.fullmatch(r'[a-z_]{1,40}', kind):
            trace.fields['action_type'] = kind


def scene(observation, seat):
    """Only public counts from the existing player projection; never calls the engine."""
    trace = current()
    if trace is None or type(observation) is not dict:
        return
    trace.fields['seat'] = seat
    trace.fields['turn'] = observation.get('turn')
    trace.fields['scene'] = [{'player': p['id'], 'board': len(p['board']),
        'hand': len(p['hand']), 'deck': p['deck_count']} for p in observation.get('players', [])]


class RequestTrace:
    def __init__(self, path, port, client_id=None, sink=None):
        self.id = secrets.token_hex(16)
        self.path = path.split('?', 1)[0][:100]
        self.port = port
        self.sink = sink or sink_for(port)
        self.client_id = client_id if type(client_id) is str and re.fullmatch(r'[0-9a-f]{32}', client_id) else None
        self.stages = {}
        self.fields = {}
        self.status = None
        self.started = time.perf_counter()
        self.cpu_started = time.thread_time()

    def row(self, event):
        return {'event': event, 'at': datetime.now(timezone.utc).isoformat(),
            'request_id': self.id, 'ui_id': self.client_id, 'port': self.port, 'path': self.path}

    def __enter__(self):
        self.context_token = _current.set(self)
        self.sink.write('server', self.row('request_started'))
        return self

    def exception(self, exc):
        # No exception message/locals: they can contain private data or credentials.
        self.sink.write('errors', {**self.row('exception'), 'error_class': type(exc).__name__,
            'stack': [{'file': f.filename, 'line': f.lineno, 'function': f.name}
                for f in traceback.extract_tb(exc.__traceback__)[-16:]]})

    def headers(self):
        values = {**self.stages, 'server_before_send_ms': (time.perf_counter() - self.started) * 1000}
        return {'X-Request-ID': self.id, 'X-UI-Diagnostics': '1',
            'Server-Timing': ', '.join(f'{k};dur={v:.3f}' for k, v in values.items())}

    def __exit__(self, kind, exc, tb):
        try:
            if exc is not None:
                self.exception(exc)
            self.sink.write('server', {**self.row('request_finished'), **self.fields,
                'status': self.status, 'wall_ms': round((time.perf_counter() - self.started) * 1000, 3),
                'thread_cpu_ms': round((time.thread_time() - self.cpu_started) * 1000, 3),
                'stages_ms': {k: round(v, 3) for k, v in self.stages.items()},
                'dropped_log_records': self.sink.dropped})
        finally:
            _current.reset(self.context_token)


CLIENT_STAGES = {'http_ms', 'fetch_ms', 'decode_ms', 'capture_ms', 'intent_ms', 'render_ms',
                 'outcome_ms', 'interaction_ms'}
SERVER_STAGES = {'host_lock_wait_ms', 'session_lock_wait_ms', 'route_ms', 'command_submit_ms',
    'legal_actions_ms', 'events_ms', 'view_enrichment_ms', 'ai_legal_actions_ms', 'ai_policy_ms',
    'serialize_ms', 'server_before_send_ms'}


def client_record(body):
    """Reject arbitrary log payloads; these are client reports, not trusted game facts."""
    if type(body) is not dict or set(body) - {'ui_id', 'request_id', 'path', 'action_type', 'card_id',
            'card_name', 'status', 'error_code', 'stages_ms', 'server_ms', 'scene'}:
        raise ValueError('invalid_diagnostics')
    result = {}
    for key in ('ui_id', 'request_id'):
        value = body.get(key)
        if type(value) is not str or re.fullmatch(r'[0-9a-f]{32}', value) is None:
            raise ValueError('invalid_diagnostics')
        result[key] = value
    for key, maximum in (('path', 60), ('action_type', 40), ('card_id', 120), ('card_name', 120), ('status', 20), ('error_code', 120)):
        value = body.get(key)
        if value is not None:
            if type(value) is not str or len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError('invalid_diagnostics')
            result[key] = value
    for key, allowed in (('stages_ms', CLIENT_STAGES), ('server_ms', SERVER_STAGES)):
        value = body.get(key, {})
        if type(value) is not dict or set(value) - allowed:
            raise ValueError('invalid_diagnostics')
        if any(type(v) not in (float, int) or not math.isfinite(v) or not 0 <= v <= 3600000 for v in value.values()):
            raise ValueError('invalid_diagnostics')
        result[key] = value
    value = body.get('scene', {})
    allowed = {'seat', 'turn', 'friendly_board', 'enemy_board', 'friendly_hand', 'enemy_hand'}
    if type(value) is not dict or set(value) - allowed or any(type(v) is not int or not 0 <= v <= 100000 for v in value.values()):
        raise ValueError('invalid_diagnostics')
    result['scene'] = value
    trace = current()
    return trace.sink.write('client', {**result, 'event': 'client_report',
        'received_at': datetime.now(timezone.utc).isoformat(), 'port': trace.port}) if trace else False
