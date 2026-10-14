"""Real Sinestra, Fireball and pre-play Choose One with restored player actions."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def fireball(game):
    port = game.for_player(1); listing = port.legal_actions()
    own, enemy = sorted(listing['observation']['players'], key=lambda p: p['id'])
    ref = next(e['ref'] for e in own['hand'] if e['card_id'] == 'CS2_029')
    action = next(a for a in listing['actions'] if a['type'] == 'play_card' and
                  a['card'] == ref and a.get('target') == enemy['hero']['ref'])
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def choose_draw(game):
    port = game.for_player(1); listing = port.legal_actions()
    own = next(p for p in listing['observation']['players'] if p['id']==1)
    card = next(c['ref'] for c in own['hand'] if c['card_id']=='EX1_164')
    action = next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card and a['branch']=='draw')
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('CATA_154', 'CS2_029', 'EX1_164'),
                    deck=('CS2_182',)*16, max_mana=10, mana=10),
        PlayerSetup('HERO_08', deck=('CS2_182',)*16, max_mana=10, mana=10)), seed=173,
        generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)
    submit(game, 'CATA_154'); fireball(game)
    assert game.state.entities[game.state.players[2].hero_id].health == 18
    assert game.state.players[1].mana == 0
    submit(game); submit(game)
    snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        draws = len([e for e in match.events if e.kind == 'card_drawn'])
        choose_draw(match)
        assert match.state.pending_choice is None
        assert len([e for e in match.events if e.kind == 'card_drawn']) == draws + 6
        assert len([e for e in match.events if e.kind == 'choice_requested']) == 0
        assert [c.branch_id for c in match.state.cast_history[-2:]] == ['draw','draw']
        assert len(match.state.spell_repeats) == 2
        assert all(r.finished and r.completed == 2 for r in match.state.spell_repeats)
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run(); output = Path(__file__).resolve().parents[1] / 'outputs'
    for name, value in (('sinestra-snapshot.json', snapshot), ('sinestra-replay.json', build_replay(game)),
                        ('sinestra-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__': main()
