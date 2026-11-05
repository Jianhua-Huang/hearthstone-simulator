"""Export real frozen-engine projections for offline UI assertions only."""
from pathlib import Path
import argparse
import sys
from duel_audit import read, write, set_affinity, file_hash
from duel_audit_compare import snapshot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True); p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--cpu-mask', type=int, default=16)
    a = p.parse_args(); assert not a.output.exists(); source = a.source.resolve(); set_affinity(a.cpu_mask)
    sys.path.insert(0, str(source)); sys.path.insert(0, str(source / 'tools'))
    import duel_audit_runtime as runtime
    assert runtime.ROOT == source
    fixtures = read(a.fixtures); first = read(next(iter(fixtures.values())))
    c = runtime.catalog(a.output.parent / (a.output.stem + '-setup'), 'views', Path(first['decks']))
    views = {}
    for name, path in fixtures.items():
        fixture = read(path)
        before = runtime.Game.from_snapshot(snapshot(fixture['before']), c.registry, mode='release')
        game = runtime.Game.from_snapshot(snapshot(fixture['after']), c.registry, mode='release')
        views[name] = {'actor': fixture['actor'],
                       'before_observation': before.for_player(fixture['actor']).legal_actions()['observation'],
                       'observation': game.for_player(fixture['actor']).legal_actions()['observation']}
    write(a.output, {'source': str(source), 'exporter_sha256': file_hash(__file__), 'views': views})


if __name__ == '__main__': main()
