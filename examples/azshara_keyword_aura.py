"""Azshara hero Windfury, weapon wear, source silence and player API replay.

This is a mechanics scenario with explicit cards, not a legal constructed deck.
"""
import json
from pathlib import Path

from hs_sim.engine import Game, Keyword, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def hero_attack(game):
    port = game.for_player(1); listing = port.legal_actions()
    own, enemy = sorted(listing['observation']['players'], key=lambda p: p['id'])
    action = next(a for a in listing['actions'] if a['type'] == 'attack' and
                  a['attacker'] == own['hero']['ref'] and a['defender'] == enemy['hero']['ref'])
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('CS2_106', 'CATA_151', 'CS2_106', 'EX1_332'),
                    deck=('CS2_182',)*8, max_mana=10, mana=10),
        PlayerSetup('HERO_08', deck=('CS2_182',)*8, max_mana=10, mana=10)), seed=151), registry)
    submit(game, 'CS2_106'); submit(game); submit(game); submit(game, 'CATA_151')
    snapshot = game.snapshot(); restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        hero_attack(match); hero_attack(match)
        assert match.state.players[1].weapon_id is None
        assert match.state.entities[match.state.players[2].hero_id].health == 20
        submit(match); submit(match); submit(match, 'CS2_106'); hero_attack(match)
        submit(match, 'EX1_332', 'CATA_151')
        hero = match.state.entities[match.state.players[1].hero_id]
        assert (hero.attack, hero.attacks_this_turn) == (3, 1)
        assert Keyword.WINDFURY not in hero.keywords
        listing = match.for_player(1).legal_actions()
        hero_ref = next(p for p in listing['observation']['players'] if p['id'] == 1)['hero']['ref']
        assert not any(a['type'] == 'attack' and a['attacker'] == hero_ref for a in listing['actions'])
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run(); output = Path(__file__).resolve().parents[1]/'outputs'
    for name, value in (('azshara-snapshot.json', snapshot), ('azshara-replay.json', build_replay(game)),
                        ('azshara-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__': main()
