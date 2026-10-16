"""Explosive Runes through real player commands and complete portable checkpoints."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.damage_history import spell_damage_dealt
from hs_sim.engine.replay import build_replay, replay


def exercise(target, providers, expected_damage, expected_hero_health, survives):
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_LOOT_101',), board=providers,
                    deck=('CORE_CS2_182',)*2, mana=10, max_mana=10),
        PlayerSetup('HERO_08', hand=(target,), deck=('CORE_CS2_182',)*2,
                    mana=10, max_mana=10)), seed=223), build_registry())
    checkpoints = []

    def check():
        saved = game.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert game.clone().snapshot() == saved
        assert replay(build_replay(game), build_registry()).snapshot() == saved
        checkpoints.append('ready')

    def submit(player, choose):
        listing = game.for_player(player).legal_actions()
        reply = game.for_player(player).submit({'revision': listing['revision'], 'action': choose(listing)})
        assert reply['accepted'], reply.get('error')
        check()

    def play(player, card_id):
        def choose(listing):
            owner = next(p for p in listing['observation']['players'] if p['id'] == player)
            card = next(c for c in owner['hand'] if c['card_id'] == card_id)
            return next(a for a in listing['actions'] if a['type'] == 'play_card' and a['card'] == card['ref'])
        submit(player, choose)

    check()
    play(1, 'CORE_LOOT_101')
    assert game.state.players[1].mana == 7
    submit(1, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    play(2, target)
    state = game.state
    rows = [row.health_result for row in state.damage_history
            if row.health_result.source_card_id == 'CORE_LOOT_101']
    assert [row.damage_dealt for row in rows] == expected_damage
    assert len({row.batch_id for row in rows}) == 1
    assert spell_damage_dealt(state, game.registry, 1, turn=2) == sum(expected_damage)
    assert state.entities[state.players[2].hero_id].health == expected_hero_health
    assert bool(state.players[2].board) == survives
    assert not state.players[1].secrets
    if survives:
        from hs_sim.engine import Keyword
        assert Keyword.DIVINE_SHIELD not in state.entities[state.players[2].board[0]].keywords
    assert state.pending_choice is None
    for viewer in (1, 2):
        public = json.dumps(game.for_player(viewer).observe()) + json.dumps(game.player_events(viewer))
        assert '"rule_ids"' not in public and '"partition_source"' not in public
    return dict(target=target, providers=providers, damage=expected_damage,
                enemy_hero_health=expected_hero_health, minion_survives=survives,
                actions=len(game.history), checkpoints=checkpoints,
                revealed=sum(event.kind == 'secret_revealed' for event in game.events))


def main():
    scenarios = [
        exercise('CORE_CS2_182', ('CORE_EX1_012',), [5, 2], 28, False),
        exercise('CORE_EX1_008', (), [0, 5], 25, True),
    ]
    result = dict(content_version='constructed-cn37-preview-v14', schema_version=SNAPSHOT_SCHEMA_VERSION,
                  formal_pool_complete=False, roots=1, scenarios=scenarios,
                  actions=sum(row['actions'] for row in scenarios),
                  checkpoints=sum(len(row['checkpoints']) for row in scenarios), waiting_choices=0)
    assert (result['actions'], result['checkpoints']) == (6, 8)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
