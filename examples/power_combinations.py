"""Existing adapters in an artificial multi-power setup; not a legal deck/source claim."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game, kind, card=None, choice_index=0):
    port = game.for_player(game.state.active_player)
    listing = port.legal_actions()
    own, enemy = sorted(listing['observation']['players'], key=lambda p: p['id'] != game.state.active_player)
    actions = [a for a in listing['actions'] if a['type'] == kind]
    if kind == 'use_hero_power':
        power = next(p for p in [own['hero_power'], *own['additional_hero_powers']] if p['card_id'] == card)
        target = enemy['hero']['ref'] if card == 'HERO_08bp' else None
        actions = [a for a in actions if a['power'] == power['ref'] and a.get('target') == target]
    elif kind == 'play_card':
        ref = next(p['ref'] for p in own['hand'] if p['card_id'] == card)
        target = enemy['hero']['ref'] if card == 'CS2_029' else None
        actions = [a for a in actions if a['card'] == ref and a.get('target') == target]
    assert port.submit({'revision': listing['revision'], 'action': actions[choice_index]})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((PlayerSetup('HERO_03', hero_power_card_id='HERO_08bp',
        additional_hero_power_card_ids=('END_000p',), hand=('END_036',)+('CS2_029',)*5,
        deck=('CS2_182',)*4, mana=10, max_mana=10), PlayerSetup('HERO_01', deck=('CS2_182',)*4)),
        seed=69, generation_context=GenerationContext('local-2026-09-23', 'experimental')), registry)
    submit(game, 'use_hero_power', 'HERO_08bp')
    submit(game, 'use_hero_power', 'END_000p')
    snapshot = game.snapshot()
    primary_history = game.state.hero_power_history[0]
    abandoned_card = game.state.players[1].hand[-1]
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        submit(match, 'select_choice', choice_index=1)  # Retry, after the primary was already paid/used.
        assert match.state.hero_power_history[0] == primary_history
        assert abandoned_card not in match.state.entities
        assert match.state.players[1].mana == 7
        assert match.state.players[1].hero_power_uses_this_turn == 2
        submit(match, 'play_card', 'END_036')
        # A second private-choice save point exercises a different source.
        choice_snapshot = match.snapshot()
        clone = Game.from_snapshot(json.loads(json.dumps(choice_snapshot)), registry)
        assert clone.for_player(2).legal_actions()['actions'] == [{'type': 'concede'}]
        submit(clone, 'select_choice'); submit(match, 'select_choice')
        assert clone.snapshot() == match.snapshot()
        submit(match, 'end_turn'); submit(match, 'end_turn')
        submit(match, 'use_hero_power', 'END_000p')
        assert match.state.pending_choice is None
        assert match.state.rewind_outcomes[0].power_id == 3
        assert match.state.rewind_outcomes[0].completed == 2
        assert match.state.players[1].mana == 9
        submit(match, 'use_hero_power', 'HERO_08bp')
        submit(match, 'play_card', 'CS2_029')
        for _ in range(2):
            submit(match, 'end_turn'); submit(match, 'end_turn')
            submit(match, 'play_card', 'CS2_029'); submit(match, 'play_card', 'CS2_029')
        assert (match.state.status, match.state.winner) == ('finished', 1)
        assert match.state.pending_choice is None
        assert match.snapshot()['rewind_session'] is None
        assert len(match.state.hero_power_history) == 4
        assert not match.for_player(1).legal_actions()['actions']
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run()
    out = Path(__file__).resolve().parents[1]/'outputs'
    for name, data in (('power-combinations-snapshot.json', snapshot),
                       ('power-combinations-replay.json', build_replay(game)),
                       ('power-combinations-view.json', game.observe(1))):
        (out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
        'state_hash': game.state_hash(), 'restored_and_replayed': True, 'winner': game.state.winner}))


if __name__ == '__main__': main()
