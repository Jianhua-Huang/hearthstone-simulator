"""Import ordered, anonymous client observations; never execute server rules.

Only GameState is authoritative for this *log projection*. PowerTaskList repeats
the stream and is counted but excluded. This tool is not a player observation
API, a complete server trace, or proof of a region/build's effective rules.
"""
from collections import Counter
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools import card_batch as batch
from tools import power_log_grammar as wire

CONTRACT = 'power-log-observations-v1'
TOKEN = re.compile(r'[A-Z][A-Z0-9_]*|-?\d+')
CARD = re.compile(r'[A-Za-z0-9_]+')
ENTITY = re.compile(
    r'\[(?:entityName=.* )?id=(\d+) zone=([A-Z_]*) zonePos=(\d+) '
    r'cardId=([A-Za-z0-9_]*) player=(\d+)\]')
COLLECTION = 'System.Collections.Generic.List`1[System.String]'
# Local extensions, kept separate from the unmodified licensed grammar:
# numeric GameTags can be negative; observed prefab names contain apostrophes.
TAG_VALUE = re.compile(wire.TAG_VALUE_RE.pattern.replace(r'value=(\w+)', r'value=(-?\w+)'))
TAG_CHANGE = re.compile(wire.TAG_CHANGE_RE.pattern.replace(r'value=(\w+)', r'value=(-?\w+)'))
HIDE_ENTITY = re.compile(wire.HIDE_ENTITY_RE.pattern.replace(r'value=(\w+)', r'value=(-?\w+)'))
CACHED_TAG = re.compile(wire.CACHED_TAG_FOR_DORMANT_CHANGE_RE.pattern.replace(r'value=(\w+)', r'value=(-?\w+)'))
SUB_SPELL_START = re.compile(r'SUB_SPELL_START - SpellPrefabGUID=\S+ Source=(\d+) TargetCount=(\d+)')
CHOICE_HANDLERS = {
    'GameState.DebugPrintEntityChoices': 'choice',
    'GameState.SendChoices': 'send_choices',
    'GameState.DebugPrintEntitiesChosen': 'chosen',
}


def _match(pattern, text):
    match = pattern.fullmatch(text)
    return match.groups() if match else None


def _integer(value):
    if not re.fullmatch(r'-?\d+', value):
        raise ValueError('invalid integer')
    return int(value)


def _token(value):
    if not TOKEN.fullmatch(value):
        raise ValueError('invalid symbolic or numeric value')
    return int(value) if re.fullmatch(r'-?\d+', value) else value


def _card(value):
    if not value:
        return None
    if not CARD.fullmatch(value):
        raise ValueError('invalid card identifier')
    return value


class Observer:
    """A sequential observer. Later reveals never rewrite earlier references."""

    def __init__(self):
        self.events = []
        self.games = []
        self.issues = []
        self.counts = Counter()
        self.diagnostics = []
        self.game = None
        self.stack = []
        self.entity_context = None
        self.details = None
        self.players = {}
        self.names = {}
        self.opaque = {}
        self.game_entity = None
        self.choice_context = {}
        self.chosen_details = None
        self.option_context = None
        self.current_option = None
        self.line = 0
        self.time = None

    def issue(self, code):
        # Never retain unparsed payloads or display/account names in errors.
        self.issues.append(dict(line=self.line, game=self.game_id, code=code))

    @property
    def game_id(self):
        return self.game['id'] if self.game else None

    def event(self, kind, **fields):
        result = dict(line=self.line, time=self.time, game=self.game_id,
                      kind=kind, parent=self.stack[-1]['line'] if self.stack else None,
                      **fields)
        self.events.append(result)
        self.counts['events'] += 1
        return result

    def reference(self, value):
        value = value.strip()
        if re.fullmatch(r'-?\d+', value):
            return dict(entity_id=int(value))
        if value == 'GameEntity' and self.game_entity is not None:
            return dict(entity_id=self.game_entity)
        match = ENTITY.fullmatch(value)
        if match:
            eid, zone, position, cid, player = match.groups()
            return dict(entity_id=int(eid), zone=zone or None,
                        zone_position=int(position), card_id=_card(cid), player_id=int(player))
        if value.startswith('['):
            raise ValueError('unsupported entity descriptor')
        if value in self.names:
            pid = self.names[value]
            if pid in self.players:
                return dict(entity_id=self.players[pid])
            return dict(player_id=pid)
        if value not in self.opaque:
            self.opaque[value] = len(self.opaque) + 1
        self.counts['unresolved_references'] += 1
        return dict(opaque_ref=self.opaque[value])

    def flush_details(self):
        if self.details:
            if self.details['indices'] != set(range(self.details['count'])):
                self.issue('incomplete_or_duplicate_detail_list')
            self.details = None

    def start_game(self):
        self.flush_details()
        self.flush_chosen()
        if self.stack:
            self.issue('unclosed_blocks_before_game')
        if self.game:
            self.game['end_line'] = self.line - 1
        self.game = dict(id=len(self.games) + 1, start_line=self.line,
                         end_line=None, metadata={}, first_observed_turn=None)
        self.games.append(self.game)
        self.stack = []
        self.players = {}
        self.names = {}
        self.opaque = {}
        self.game_entity = None
        self.entity_context = None
        self.choice_context = {}
        self.option_context = self.current_option = None
        self.event('create_game')

    def detail(self, kind, index, value):
        if not self.details or self.details['kind'] != kind:
            self.issue('orphan_detail')
        else:
            if index in self.details['indices'] or index >= self.details['count']:
                self.issue('invalid_detail_index')
            self.details['indices'].add(index)
        self.event(kind, index=index, entity=self.reference(value),
                   packet_line=self.details['line'] if self.details else None)

    def power(self, text):
        # Details belong to a preceding packet, not to the most recently seen
        # entity forever. Other power records terminate the detail/tag context.
        if groups := _match(wire.METADATA_INFO_RE, text):
            self.detail('metadata_info', int(groups[0]), groups[1])
            return
        if groups := _match(wire.SUB_SPELL_START_TARGETS_RE, text):
            self.detail('sub_spell_target', int(groups[0]), groups[1])
            return
        if groups := _match(wire.SUB_SPELL_START_SOURCE_RE, text):
            if not self.stack or self.stack[-1]['kind'] != 'sub_spell':
                self.issue('orphan_sub_spell_source')
            self.event('sub_spell_source', entity=self.reference(groups[0]))
            return
        self.flush_details()
        if text.startswith('tag='):
            groups = _match(TAG_VALUE, text)
            if not groups or self.entity_context is None:
                raise ValueError('orphan or malformed initial tag')
            tag, value = groups
            self.tag('initial_tag', self.entity_context, tag, value)
            return
        self.entity_context = None
        if text == 'CREATE_GAME':
            self.start_game()
            return
        if groups := _match(wire.GAME_ENTITY_RE, text):
            self.game_entity = int(groups[0])
            self.entity_context = dict(entity_id=self.game_entity)
            self.event('game_entity', entity_id=self.game_entity)
            return
        if groups := _match(wire.PLAYER_ENTITY_RE, text):
            eid, pid, _hi, _lo = map(int, groups)
            self.entity_context = dict(entity_id=eid)
            self.players[pid] = eid
            self.event('player', entity_id=eid, player_id=pid)
            return
        if groups := _match(wire.FULL_ENTITY_CREATE_RE, text):
            eid, cid = groups
            self.entity_context = dict(entity_id=int(eid))
            self.event('full_entity', entity=dict(entity_id=int(eid)), card_id=_card(cid))
            return
        for pattern, kind in ((wire.FULL_ENTITY_UPDATE_RE, 'full_entity_update'),
                              (wire.SHOW_ENTITY_RE, 'show_entity'),
                              (wire.CHANGE_ENTITY_RE, 'change_entity')):
            if groups := _match(pattern, text):
                entity, cid = groups
                ref = self.reference(entity)
                self.entity_context = ref
                self.event(kind, entity=ref, card_id=_card(cid))
                return
        for pattern, kind in ((TAG_CHANGE, 'tag_change'),
                              (HIDE_ENTITY, 'hide_entity'),
                              (CACHED_TAG, 'cached_dormant_tag')):
            if groups := _match(pattern, text):
                entity, tag, value, *extra = groups
                self.tag(kind, self.reference(entity), tag, value,
                         definition_change=bool(extra and extra[0]))
                return
        for pattern in (wire.BLOCK_START_20457_TRIGGER_KEYWORD_RE,
                        wire.BLOCK_START_20457_RE, wire.BLOCK_START_12051_RE):
            if groups := _match(pattern, text):
                block_type, entity, effect, effect_index, target, *extra = groups
                effect_value = dict(unavailable='client_collection_string') if effect == COLLECTION else _card(effect)
                if effect == COLLECTION:
                    self.counts['unavailable_effect_card_ids'] += 1
                fields = dict(block_type=_token(block_type), entity=self.reference(entity),
                              target=self.reference(target), effect_card_id=effect_value,
                              effect_index=_integer(effect_index))
                if extra:
                    fields['sub_option'] = _integer(extra[0])
                if len(extra) > 1:
                    fields['trigger_keyword'] = _token(extra[1])
                self.event('block_start', **fields)
                self.stack.append(dict(kind='block', line=self.line))
                return
        if text in ('BLOCK_END', 'SUB_SPELL_END'):
            kind = 'block' if text == 'BLOCK_END' else 'sub_spell'
            if not self.stack or self.stack[-1]['kind'] != kind:
                self.issue('unmatched_' + kind + '_end')
                self.event(kind + '_end', start_line=None)
            else:
                start = self.stack.pop()
                self.event(kind + '_end', start_line=start['line'])
            return
        if groups := _match(wire.META_DATA_RE, text):
            meta, data, count = groups
            # Meta.Data can be a signed number, or an entity reference. Never
            # export arbitrary strings as scalar data.
            value = int(data) if re.fullmatch(r'-?\d+', data) else self.reference(data)
            self.event('metadata', meta=_token(meta), data=value, info_count=int(count))
            self.details = dict(kind='metadata_info', line=self.line, count=int(count), indices=set())
            return
        if groups := _match(SUB_SPELL_START, text):
            source, count = groups
            self.event('sub_spell_start', source=self.reference(source), target_count=int(count))
            self.stack.append(dict(kind='sub_spell', line=self.line))
            self.details = dict(kind='sub_spell_target', line=self.line, count=int(count), indices=set())
            return
        if groups := _match(wire.SHUFFLE_DECK_RE, text):
            self.event('shuffle_deck', player_id=int(groups[0]))
            return
        if text == 'RESET_GAME':
            self.event('reset_game')
            self.counts['observed_game_resets'] += 1
            return
        if _match(wire.VO_SPELL_RE, text):
            self.counts['excluded_cosmetic_records'] += 1
            return
        raise ValueError('unsupported power record')

    def tag(self, kind, entity, tag, value, **fields):
        tag = _token(tag)
        value = _token(value)
        ref = dict(entity_id=entity) if type(entity) is int else entity
        self.event(kind, entity=ref, tag=tag, value=value, **fields)
        if (self.game and tag == 'TURN' and ref.get('entity_id') == self.game_entity
                and self.game['first_observed_turn'] is None):
            self.game['first_observed_turn'] = value

    def game_meta(self, text):
        if groups := _match(wire.GAME_PLAYER_META, text):
            pid, name = groups
            self.names[name] = int(pid)
            self.event('player_metadata', player_id=int(pid))
            return
        key, value = text.split('=', 1)
        if key not in ('BuildNumber', 'GameType', 'FormatType', 'ScenarioID'):
            raise ValueError('unsupported game metadata')
        value = _integer(value) if key in ('BuildNumber', 'ScenarioID') else _token(value)
        if not self.game:
            raise ValueError('metadata before create game')
        self.game['metadata'][key] = value
        self.event('game_metadata', key=key, value=value)

    def choices(self, handler, text):
        kind = CHOICE_HANDLERS[handler]
        if kind == 'choice':
            if groups := _match(wire.CHOICES_CHOICE_RE, text):
                cid, player, task, ctype, low, high = groups
                self.choice_context[kind] = int(cid)
                self.event('choice', choice_id=int(cid), player=self.reference(player),
                           task_list=int(task) if task else None, choice_type=_token(ctype),
                           count_min=int(low), count_max=int(high))
                return
            if groups := _match(wire.CHOICES_SOURCE_RE, text):
                self.choice_item(kind, 'choice_source', groups[0])
                return
            pattern = wire.CHOICES_ENTITIES_RE
        elif kind == 'send_choices':
            if groups := _match(wire.SEND_CHOICES_CHOICE_RE, text):
                cid, ctype = groups
                self.choice_context[kind] = int(cid)
                self.event(kind, choice_id=int(cid), choice_type=_token(ctype))
                return
            pattern = wire.SEND_CHOICES_ENTITIES_RE
        else:
            if groups := _match(wire.ENTITIES_CHOSEN_RE, text):
                self.flush_chosen()
                cid, player, count = groups
                self.choice_context[kind] = int(cid)
                self.chosen_details = dict(count=int(count), indices=set())
                self.event(kind, choice_id=int(cid), player=self.reference(player), count=int(count))
                return
            pattern = wire.ENTITIES_CHOSEN_ENTITIES_RE
        if groups := _match(pattern, text):
            index, entity = groups
            if kind == 'chosen' and self.chosen_details:
                if int(index) in self.chosen_details['indices'] or int(index) >= self.chosen_details['count']:
                    self.issue('invalid_chosen_index')
                self.chosen_details['indices'].add(int(index))
            self.choice_item(kind, kind + '_entity', entity, index=int(index))
            return
        raise ValueError('unsupported choice record')

    def flush_chosen(self):
        if self.chosen_details:
            if self.chosen_details['indices'] != set(range(self.chosen_details['count'])):
                self.issue('incomplete_chosen_list')
            self.chosen_details = None

    def choice_item(self, context, kind, value, **fields):
        cid = self.choice_context.get(context)
        if cid is None:
            self.issue('orphan_choice_item')
        self.event(kind, choice_id=cid, entity=self.reference(value), **fields)

    def options(self, text):
        if groups := _match(wire.OPTIONS_ENTITY_RE, text):
            self.option_context = int(groups[0])
            self.current_option = None
            self.event('options', options_id=self.option_context)
            return
        if self.option_context is None:
            self.issue('orphan_option')
        for pattern, main in ((wire.OPTIONS_OPTION_ERROR_RE, True),
                              (wire.OPTIONS_OPTION_RE, True),
                              (wire.OPTIONS_SUBOPTION_ERROR_RE, False),
                              (wire.OPTIONS_SUBOPTION_RE, False)):
            if groups := _match(pattern, text):
                kind, index, *values = groups
                fields = dict(options_id=self.option_context, index=int(index))
                if main:
                    otype, entity, *error = values
                    self.current_option = int(index)
                    fields['option_type'] = _token(otype)
                else:
                    entity, *error = values
                    fields['option_index'] = self.current_option
                    if self.current_option is None:
                        self.issue('orphan_option_detail')
                fields['entity'] = self.reference(entity) if entity else None
                if error:
                    fields.update(error=_token(error[0]), error_param=int(error[1]) if error[1] else None)
                self.event(kind, **fields)
                return
        raise ValueError('unsupported option record')

    def consume(self, line, number):
        self.line = number
        line = line.rstrip('\r\n')
        if not line.strip():
            self.counts['blank_lines'] += 1
            return
        timestamp = wire.TIMESTAMP_RE.fullmatch(line)
        if not timestamp:
            self.issue('invalid_line_prefix')
            return
        level, self.time, body = timestamp.groups()
        if level in ('W', 'E'):
            # Retain the position of client diagnostics without names/content.
            # They are separate from packet syntax and are not server events.
            diagnostic = dict(line=number, game=self.game_id, level=level)
            if body == ('PowerProcessor.BuildTaskList(): Hit a SUB_SPELL_END task '
                        'without a corresponding open SubSpellOrigin!'):
                diagnostic['code'] = 'client_reported_orphan_subspell_origin'
            self.diagnostics.append(diagnostic)
        match = wire.POWERLOG_LINE_RE.fullmatch(body)
        if not match:
            if body.startswith('GameState.'):
                self.issue('invalid_selected_handler_prefix')
            else:
                self.counts['excluded_unstructured_diagnostics'] += 1
            return
        handler, text = match.groups()
        text = text.strip()
        if handler.startswith('PowerTaskList.'):
            self.counts['excluded_power_task_list_lines'] += 1
            return
        if not handler.startswith('GameState.'):
            self.counts['excluded_other_handler_lines'] += 1
            return
        self.counts['selected_handler_lines'] += 1
        if handler not in ('GameState.DebugPrintPower', 'GameState.DebugPrintPowerList') and not self.game:
            self.issue('selected_record_before_create_game')
        try:
            if handler == 'GameState.DebugPrintPower':
                if not self.game and text != 'CREATE_GAME':
                    self.issue('power_record_before_create_game')
                self.power(text)
            elif handler == 'GameState.DebugPrintGame':
                self.game_meta(text)
            elif handler in CHOICE_HANDLERS:
                self.choices(handler, text)
            elif handler == 'GameState.OnEntityChoices':
                match = re.fullmatch(r'id=(\d+) playerId=(\d+) queued', text)
                if not match:
                    raise ValueError('unsupported queued choice notice')
                cid, pid = map(int, match.groups())
                self.event('choice_queued', choice_id=cid, player_id=pid)
            elif handler == 'GameState.DebugPrintOptions':
                self.options(text)
            elif handler == 'GameState.SendOption':
                groups = _match(wire.SEND_OPTION_RE, text)
                if not groups:
                    raise ValueError('unsupported selected option')
                option, sub, target, position = map(int, groups)
                self.event('send_option', option=option, sub_option=sub,
                           target=target, position=position, options_id=self.option_context)
            elif handler == 'GameState.DebugPrintPowerList' and re.fullmatch(r'Count=\d+', text):
                self.counts['power_list_headers'] += 1
            else:
                raise ValueError('unsupported selected handler')
        except (ValueError, TypeError):
            self.issue('unparsed_selected_record')

    def finish(self, line_count):
        self.line = line_count
        self.flush_details()
        self.flush_chosen()
        if self.stack:
            self.issue('unclosed_blocks_at_eof')
        if self.game:
            self.game['end_line'] = line_count
        if not self.games:
            self.issue('no_canonical_games')


def parse_bytes(raw):
    """Return observed packets only. No account/display strings leave memory."""
    if type(raw) is not bytes:
        raise TypeError('Power.log input must be bytes')
    text = raw.decode('utf-8-sig', errors='strict')
    if '\x00' in text:
        raise ValueError('Power.log contains NUL bytes')
    observer = Observer()
    count = 0
    for count, line in enumerate(text.splitlines(), 1):
        observer.consume(line, count)
    observer.finish(count)
    return dict(schema=1, contract=CONTRACT,
                source=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
                boundary=dict(canonical_prefix='GameState', client_observations_only=True,
                              complete_server_execution=False, full_game_capture_verified=False,
                              cn_region_verified=False, fixed_target_verified=False,
                              accepted_calibration_case=False, player_dto=False,
                              later_reveals_backfilled=False, identities_exported=False),
                coverage=dict(lines=count, counts=dict(observer.counts),
                              selected_stream_parse_complete=not observer.issues,
                              issues=observer.issues, client_diagnostics=observer.diagnostics),
                games=observer.games, events=observer.events)


def import_file(source, output):
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or output.exists():
        raise ValueError('Output must be a fresh file distinct from the source')
    guard = batch.source_guard(ROOT)
    raw = source.read_bytes()
    result = parse_bytes(raw)
    if hashlib.sha256(source.read_bytes()).hexdigest() != result['source']['sha256']:
        raise ValueError('Source changed during observation')
    if batch.source_guard(ROOT) != guard:
        raise ValueError('Python source changed during observation')
    result['parser_files'] = {str(p.relative_to(ROOT).as_posix()): batch.sha(p)
                              for p in (Path(__file__).resolve(), Path(wire.__file__).resolve())}
    if output.suffix == '.gz':
        output.parent.mkdir(parents=True, exist_ok=True)
        # Compact, deterministic storage avoids multiplying the client's large
        # logs. The underlying exclusive open preserves old observations.
        with output.open('xb') as stream:
            with gzip.GzipFile(filename='', fileobj=stream, mode='wb', mtime=0) as compressed:
                compressed.write(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    else:
        batch.save_new(output, result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = import_file(args.source, args.output)
    except (OSError, ValueError) as exc:
        # Do not echo input content or paths from decoding/I/O exceptions.
        print('Power.log import failed: ' + type(exc).__name__, file=sys.stderr)
        return 2
    print(json.dumps(dict(games=len(result['games']), events=len(result['events']),
                          issues=len(result['coverage']['issues']),
                          selected_stream_parse_complete=result['coverage']['selected_stream_parse_complete'],
                          accepted_calibration_case=False), ensure_ascii=False))
    return 0 if result['coverage']['selected_stream_parse_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
