"""Al'Akir's limbs, one-cost generation and Rush/Windfury through player actions.

An explicit existing-state mechanics scenario, not a legal constructed deck.
"""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def attack_egg(game):
    port = game.for_player(1); listing = port.legal_actions()
    own, enemy = sorted(listing['observation']['players'], key=lambda p: p['id'])
    attacker = next(e['ref'] for e in own['board'] if e['card_id'] == 'CATA_153')
    target = next(e['ref'] for e in enemy['board'] if e['card_id'] == 'FP1_007')
    action = next(a for a in listing['actions'] if a['type'] == 'attack' and
                  a['attacker'] == attacker and a['defender'] == target)
    assert port.submit({'revision': listing['revision'], 'action': action})['accepted']


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_01', hand=('CATA_153',), deck=('CS2_182',)*8, max_mana=10, mana=10),
        PlayerSetup('HERO_08', board=('FP1_007', 'FP1_007'), deck=('CS2_182',)*8, max_mana=10, mana=10)),
        generation_context=GenerationContext('local-2026-09-23', 'experimental'), seed=163), registry)
    submit(game, 'CATA_153'); snapshot = game.snapshot()
    restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), registry)
    for match in (game, restored):
        hand = match.observe(1)['players'][0]['hand']
        assert len(hand) == 2 and all(e['cost'] == {'amount': 1, 'payment': 'mana'} for e in hand)
        assert all(match.state.entities[i].base_cost == 4 for i in match.state.players[1].hand)
        for entry in hand: submit(match, entry['card_id'])
        assert match.state.players[1].mana == 0
        attack_egg(match); attack_egg(match)
        body = next(match.state.entities[i] for i in match.state.players[1].board
                    if match.state.entities[i].card_id == 'CATA_153')
        assert body.attacks_this_turn == 2
        assert [match.state.entities[i].card_id for i in match.state.players[2].board] == ['FP1_007t']*2
    assert game.snapshot() == restored.snapshot()
    assert replay(build_replay(game), registry).snapshot() == game.snapshot()
    return game, snapshot


def main():
    game, snapshot = run(); output = Path(__file__).resolve().parents[1]/'outputs'
    for name, value in (('alakir-snapshot.json', snapshot), ('alakir-replay.json', build_replay(game)),
                        ('alakir-view.json', game.observe(1))):
        (output/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'actions': len(game.history), 'events': len(game.events),
                     'state_hash': game.state_hash(), 'restored_and_replayed': True}))


if __name__ == '__main__': main()
