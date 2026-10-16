"""Six real quantity-price consumers through both players' public commands."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def main():
    g = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('JAIL_204', 'TIME_047', 'CATA_452', 'CATA_568',
                    'TIME_715', 'JAIL_514', 'CORE_CS2_029'), deck=('CORE_CS2_182',)*8,
                    mana=50, max_mana=50, mana_cap=50),
        PlayerSetup('HERO_03', deck=('CORE_CS2_182',)*2)), seed=181), build_registry())
    checkpoints = []
    def check():
        saved = g.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert g.clone().snapshot() == saved
        assert replay(build_replay(g), build_registry()).snapshot() == saved
        checkpoints.append('ready')
    def submit(player, choose):
        listing = g.for_player(player).legal_actions()
        action = choose(listing)
        reply = g.for_player(player).submit({'revision': listing['revision'], 'action': action})
        assert reply['accepted'], reply.get('error')
        check()
    def play(cid, enemy_hero=False):
        def choose(listing):
            players = {p['id']: p for p in listing['observation']['players']}
            card = next(c for c in players[1]['hand'] if c['card_id'] == cid)
            target = players[2]['hero']['ref'] if enemy_hero else None
            return next(a for a in listing['actions'] if a['type'] == 'play_card'
                        and a['card'] == card['ref'] and a.get('target') == target)
        submit(1, choose)
    check(); play('JAIL_204')
    submit(1, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    submit(2, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    play('CORE_CS2_029', True)
    def attack(listing):
        players = {p['id']: p for p in listing['observation']['players']}
        source = next(e for e in players[1]['board'] if e['card_id'] == 'JAIL_204')
        return next(a for a in listing['actions'] if a['type'] == 'attack'
                    and a['attacker'] == source['ref'] and a['defender'] == players[2]['hero']['ref'])
    submit(1, attack)
    for cid in ('TIME_047', 'CATA_452', 'CATA_568', 'TIME_715', 'JAIL_514'): play(cid)
    costs = [p.cost for p in g.state.play_history]
    assert costs == [2, 4, 3, 4, 8, 5, 4]
    assert g.state.players[1].mana == 22
    assert g.state.entities[g.state.players[2].hero_id].health == 19
    assert g.state.pending_choice is None
    assert len(g.state.players[1].hand) == 8
    for viewer in (1, 2):
        public = json.dumps(g.for_player(viewer).observe()) + json.dumps(g.player_events(viewer))
        assert '"hero_damage_taken"' not in public and '"condition_facts"' not in public
    result = dict(content_version=g.registry.version, schema_version=g.snapshot()['schema_version'],
        formal_pool_complete=False, actions=len(g.history), checkpoints=checkpoints,
        costs=costs, mana=g.state.players[1].mana, enemy_health=19,
        own_hand=len(g.state.players[1].hand), owner_turns=len(g.state.owner_turn_history),
        own_draws=sum(row.player_id == 1 for row in g.state.draw_history), waiting_choices=0,
        board=[g.state.entities[e].card_id for e in g.state.players[1].board])
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__': main()
