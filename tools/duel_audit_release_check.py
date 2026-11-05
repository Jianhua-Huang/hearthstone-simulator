"""Finite release/replay contract checks on real fixtures, without full matches."""
from copy import deepcopy
from pathlib import Path
import argparse
import sys
import weakref
from duel_audit import read, write, file_hash, set_affinity
from duel_audit_compare import snapshot


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch', type=Path, required=True); p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--legacy-replay', type=Path); p.add_argument('--legacy-after', type=Path)
    p.add_argument('--fixtures-only', action='store_true', help='Only check the specified real actions and their v2 roundtrips; skip unrelated legacy/mixed scenes')
    p.add_argument('--output', type=Path, required=True); p.add_argument('--cpu-mask', type=int, default=16)
    a = p.parse_args()
    if not a.fixtures_only and (not a.legacy_replay or not a.legacy_after):
        p.error('Full contract checks require --legacy-replay and --legacy-after')
    b, out = a.batch.resolve(), a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    identity = read(b / 'identity.json'); source = Path(identity['source']); set_affinity(a.cpu_mask)
    sys.path.insert(0, str(source)); sys.path.insert(0, str(source / 'tools'))
    import duel_audit_runtime as runtime
    from hs_sim.engine import EndTurn
    from hs_sim.engine.replay import save_replay, load_replay, replay, build_replay, ReplayError
    assert runtime.ROOT == source
    fixtures = read(a.fixtures); first = read(next(iter(fixtures.values())))
    c = runtime.catalog(out, 'release-check', Path(first['decks']))
    result = {'success': False, 'identity': identity, 'checker_sha256': file_hash(__file__),
              'fixture_checks': [], 'snapshot_or_api_normalization': None}
    for name, path in fixtures.items():
        f = read(path); before, after = snapshot(f['before']), snapshot(f['after'])
        game = runtime.Game.from_snapshot(before, c.registry, mode='release'); assert game.snapshot() == before
        original = type(game).apply; reference = weakref.ref(game); returned = []
        def capture(action):
            value = original(reference(), action); returned.append(value.state_hash); return value
        game.apply = capture
        view = game.for_player(f['actor']).legal_actions()
        reply = game.for_player(f['actor']).submit({'revision': view['revision'], 'action': f['action']})
        assert reply['accepted'] and returned == [None]
        assert game.history[-1]['state_hash'] is game.history[-1]['events_hash'] is None
        assert game.snapshot() == after
        destination = out / (name + '-release-v2.json'); save_replay(game, destination)
        payload = read(destination)
        assert payload['schema_version'] == 2 and payload['actions'][-1]['state_hash'] is None
        restored = load_replay(destination, c.registry, mode='release')
        assert restored.snapshot() == after and restored.history == game.history
        assert build_replay(restored) == payload
        row = {'name': name, 'accepted': True, 'returned_state_hash': None, 'step_digests': None,
               'complete_after_and_rng_equal': True, 'replay_schema': 2,
               'saved_file': str(destination), 'saved_file_sha256': file_hash(destination),
               'saved_replay_roundtrip_equal': True}
        result['fixture_checks'].append(row); write(out / 'progress.json', result)
    if a.fixtures_only:
        manifest = read(b / 'source-manifest.json')['files']
        assert all(file_hash(source / path) == sha for path, sha in manifest.items())
        result.update(success=True, source_guard=True, fixtures_only=True,
                      scope='Only specified release actions, complete after/RNG and saved v2 roundtrips; no legacy/mixed extra scene.')
        write(out / 'result.json', result)
        print({'success': True, 'fixtures': len(result['fixture_checks']), 'fixtures_only': True})
        return
    # A real pre-R17 portable file is read without changing its header or hashes.
    legacy = read(a.legacy_replay); assert legacy['schema_version'] == 1
    legacy_game = load_replay(a.legacy_replay, c.registry, mode='release')
    assert legacy_game.snapshot() == snapshot(a.legacy_after)
    assert legacy_game.history == legacy['actions']
    bad = deepcopy(legacy); bad['actions'][0]['events_hash'] = '0' * 64
    try: replay(bad, c.registry, mode='release')
    except ReplayError as error:
        assert error.step == 1; result['legacy_tamper_rejected'] = str(error)
    else: raise AssertionError('Tampered v1 event digest accepted')
    result['legacy_v1'] = {'file': str(a.legacy_replay.resolve()), 'sha256': file_hash(a.legacy_replay),
                           'actions': len(legacy['actions']), 'full_snapshot_rng_history_equal': True}
    quick = read(fixtures['quick']); game = runtime.Game.from_snapshot(snapshot(quick['before']), c.registry, mode='release')
    game.apply(EndTurn(game._state.active_player)); assert game.history[-1]['state_hash'] is None
    game.runtime_mode = 'debug'; audited = game.apply(EndTurn(game._state.active_player))
    assert isinstance(audited.state_hash, str) and game.history[-1]['events_hash'] is not None
    mixed = out / 'mixed-release-debug-v2.json'; save_replay(game, mixed)
    assert load_replay(mixed, c.registry, mode='release').snapshot() == game.snapshot()
    payload = read(mixed)
    assert payload['actions'][0]['state_hash'] is None and payload['actions'][1]['state_hash'] is not None
    for field in ('final_state_hash', 'final_events_hash'):
        bad = deepcopy(payload); bad[field] = '0' * 64
        try: replay(bad, c.registry, mode='release')
        except ReplayError as error:
            assert field in str(error); result[field + '_tamper_rejected'] = str(error)
        else: raise AssertionError('Tampered v2 final digest accepted')
    result['mixed_release_debug_v2'] = {'release_step_null': True, 'debug_step_audited': True,
                                      'file': str(mixed), 'complete_roundtrip_equal': True}
    manifest = read(b / 'source-manifest.json')['files']
    assert all(file_hash(source / path) == sha for path, sha in manifest.items())
    result.update(success=True, source_guard=True, old_replay_file_unchanged=file_hash(a.legacy_replay) == result['legacy_v1']['sha256'])
    write(out / 'result.json', result)
    print({'success': True, 'real_fixtures': len(fixtures), 'legacy_actions': len(legacy['actions'])}, flush=True)


if __name__ == '__main__': main()
