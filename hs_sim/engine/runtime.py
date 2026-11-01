"""Host-only execution modes and bounded diagnostics; never saved game rules."""
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import perf_counter
import traceback
from uuid import uuid4


class RuntimeMode(str, Enum):
    RELEASE = 'release'
    DEBUG = 'debug'


DEBUG_RECORD_LIMIT = 128
_logger = logging.getLogger('hs_sim.engine.debug')


def _position(game):
    state = game._state
    choice = state.pending_choice
    return {'turn': state.turn, 'action_number': state.action_number,
            'active_player': state.active_player, 'status': state.status,
            'choice_id': choice.id if choice is not None else None,
            'entities': len(state.entities), 'events': len(game._events)}


class ActionTrace:
    """Created only for debug actions. Reads counts, never advances RNG or rules."""
    def __init__(self, game, action):
        from .turn_clocks import history_action_to_dict
        self.started = self.changed = perf_counter()
        self.stage_name = 'validate'
        self.stages = {}
        self.working = None
        self.work_count = 0
        self.last_work = deque(maxlen=32)
        self.queue_peak = 0
        try:
            command = history_action_to_dict(action)
        except (ValueError, TypeError, AttributeError):
            command = {'unsupported_type': type(action).__name__}
        if not getattr(game, '_debug_id', None):
            game._debug_id = uuid4().hex
        self.record = {'at': datetime.now(timezone.utc).isoformat(), 'mode': 'debug', 'game_id': game._debug_id,
                       'action': command, 'before': _position(game)}

    def stage(self, name):
        now = perf_counter()
        self.stages[self.stage_name] = self.stages.get(self.stage_name, 0) + (now - self.changed) * 1000
        self.changed, self.stage_name = now, name

    def work(self, work, queue_size):
        name = type(work).__name__
        self.work_count += 1
        self.last_work.append(name)
        self.queue_peak = max(self.queue_peak, queue_size)

    def finish(self, game, result=None, error=None):
        failed_stage = self.stage_name if error is not None else None
        self.stage('finished')
        event_count = (0 if self.working is None else
                       len(self.working._events) - self.record['before']['events'])
        self.record.update(status='error' if error is not None else 'ok',
            elapsed_ms=(perf_counter() - self.started) * 1000,
            stages_ms=self.stages, after=_position(game),
            work_count=self.work_count, queue_peak=self.queue_peak, event_count=event_count)
        if result is not None:
            self.record['state_hash'] = result.state_hash
        if error is not None:
            self.record.update(failed_stage=failed_stage, error_class=type(error).__name__, last_work=list(self.last_work),
                traceback=''.join(traceback.format_exception(type(error), error, error.__traceback__))[-32768:])
            if self.working is not None:
                self.record['discarded_position'] = _position(self.working)
        return self.record


def publish(record):
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(json.dumps(record, ensure_ascii=False, allow_nan=False))


@contextmanager
def debug_log(path):
    """Attach a local rotating JSONL log for a CLI/service lifetime."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(destination, maxBytes=5 * 1024 * 1024,
                                  backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    old_level, old_propagate = _logger.level, _logger.propagate
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG)
    _logger.propagate = False
    try:
        yield destination
    finally:
        _logger.removeHandler(handler)
        handler.close()
        _logger.setLevel(old_level)
        _logger.propagate = old_propagate
