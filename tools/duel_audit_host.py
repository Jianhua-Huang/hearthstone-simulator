"""Shared host adapter for frozen standard registries, HTTP checks and play UI."""
import random
import secrets
import threading


def make_host(ui, registry, records, game=None, seat=1):
    host = object.__new__(ui.Host)
    host.runtime_mode = ui.RuntimeMode.RELEASE
    host.lock = threading.RLock(); host.registry = registry; host.lab_records = records
    host.game = game; host.token = secrets.token_urlsafe(32); host.seat = seat
    host.handoff = False; host.sessions = {}; host.test_segments = []
    host.opponent_mode = 'human'; host.opponent_error = None; host.opponent_window = None
    host.opponent_steps = 0; host.opponent_choice_steps = 0
    host.opponent_rng = random.Random(73); host.opponent_ticket = secrets.token_urlsafe(24)
    return host


def playable_classes(ui, runtime, controller, batch, fixtures, static, title):
    """Only adapt setup/catalog; actions, authority and projection stay production."""
    import html
    import re
    from pathlib import Path
    from duel_audit import read
    plan = read(batch / 'plan.json')
    classes = {'mage': '法师', 'hunter': '猎人', 'priest': '牧师', 'rogue': '潜行者',
               'shaman': '萨满', 'warlock': '术士', 'warrior': '战士', 'paladin': '圣骑士',
               'druid': '德鲁伊', 'death_knight': '死亡骑士', 'demon_hunter': '恶魔猎手'}
    labels = {'pair-' + str(i): ' / '.join(classes.get(plan['decks'][k]['card_class'], k) for k in pair)
              for i, pair in enumerate(plan['pairs'], 1)}
    labels.update({key: data['label'] for key, data in fixtures.items()})
    class PlayHost(ui.Host):
        def __init__(self, *, mode=ui.RuntimeMode.RELEASE):
            template = make_host(ui, controller.registry, controller.records)
            self.__dict__.update(template.__dict__); self.runtime_mode = ui.RuntimeMode(mode)

        def create(self, preset, opponent='human'):
            if preset not in labels or opponent not in ('ai', 'human'): raise ValueError('invalid_preset_or_opponent')
            self.__init__(mode=self.runtime_mode)
            if preset in fixtures:
                item = read(fixtures[preset]['fixture'])
                from duel_audit_compare import snapshot
                self.game = runtime.Game.from_snapshot(snapshot(item['before']), controller.registry, mode=self.runtime_mode)
                self.seat = item['actor']
            else:
                pair = plan['pairs'][int(preset.split('-')[1]) - 1]
                self.game = runtime.Game.from_decks(controller.fmt.match_setup(
                    tuple(runtime.spec(plan['decks'][k]) for k in pair),
                    seed=read(batch / 'config.json')['seeds'][0], first_player=1), controller.registry, mode=self.runtime_mode)
            self.opponent_mode = opponent; self.refresh_opponent_ticket()
            return {'token': self.token, 'seat': self.seat}
    class Handler(ui.Handler):
        def do_GET(self):
            if self.path != '/': return super().do_GET()
            if not self.local_request(): return self.send(403, {'error': 'origin_rejected'})
            page = (Path(static) / 'index.html').read_text('utf8')
            options = ''.join('<option value="' + html.escape(k) + '">' + html.escape(v) + '</option>' for k, v in labels.items())
            page = re.sub(r'(<select id="preset"[^>]*>).*?(</select>)', lambda m: m[1] + options + m[2], page, flags=re.S)
            page = page.replace('<title>炉石测试 Demo</title>', '<title>' + html.escape(title) + '</title>')
            page = page.replace('本地对战 Demo', html.escape(title))
            return self.send(200, page.encode('utf8'), 'text/html; charset=utf-8')
    return PlayHost, Handler, labels
