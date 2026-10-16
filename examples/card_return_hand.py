"""Real owner returns, successful Spider creation, hand growth and weapon death."""
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.replay import build_replay, replay


def main():
    g = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('CATA_201', 'CORE_DAL_720', 'EDR_523', 'TIME_100',
                    'END_021', 'CORE_CS2_182', 'CORE_CS2_182'), board=('CORE_CS2_182',),
                    deck=('CORE_CS2_182',)*6, mana=50, max_mana=50, mana_cap=50),
        PlayerSetup('HERO_03', board=('CORE_CS2_182', 'CORE_EX1_012'), deck=('CORE_CS2_182',)*2)),
        seed=191), build_registry())
    checkpoints = []
    def check():
        saved = g.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert g.clone().snapshot() == saved
        assert replay(build_replay(g), build_registry()).snapshot() == saved
        checkpoints.append('ready')
    def submit(player, choose):
        listing = g.for_player(player).legal_actions(); action = choose(listing)
        response = g.for_player(player).submit({'revision': listing['revision'], 'action': action})
        assert response['accepted'], response.get('error'); check()
    def play(cid, return_yeti=False):
        def choose(listing):
            own = next(p for p in listing['observation']['players'] if p['id'] == 1)
            card = next(c for c in own['hand'] if c['card_id'] == cid)
            target = next(e['ref'] for e in own['board'] if e['card_id'] == 'CORE_CS2_182') if return_yeti else None
            return next(a for a in listing['actions'] if a['type'] == 'play_card'
                        and a['card'] == card['ref'] and a.get('target') == target)
        submit(1, choose)
    def attack(listing):
        players = {p['id']:p for p in listing['observation']['players']}
        return next(a for a in listing['actions'] if a['type'] == 'attack'
                    and a['attacker'] == players[1]['hero']['ref'] and a['defender'] == players[2]['hero']['ref'])
    check(); play('CATA_201'); play('EDR_523', True); play('END_021'); play('TIME_100'); play('CORE_DAL_720')
    assert g.state.entities[g.state.players[1].weapon_id].attack == 6
    submit(1, attack)
    submit(1, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    submit(2, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    submit(1, attack)
    costs = [row.cost for row in g.state.play_history]; assert costs == [9, 2, 3, 4, 4]
    assert g.state.players[1].weapon_id is None
    choice = next(e for e in g.events if e.kind == 'random_choice')
    selected = g.state.entities[choice.target_id]
    assert selected.id in g.state.players[1].hand
    returned_cost = quote_cost(g.state, g.registry, selected).amount
    assert returned_cost == max(0, g.registry.card(selected.card_id).cost-2)
    assert len(g.state.players[1].hand) == 5
    assert g.state.entities[g.state.players[2].hero_id].health == 18
    for viewer in (1, 2):
        public = json.dumps(g.for_player(viewer).observe())+json.dumps(g.player_events(viewer))
        assert '"on_success"' not in public and '"zone_epoch"' not in public
    result = dict(content_version=g.registry.version, schema_version=g.snapshot()['schema_version'],
        formal_pool_complete=False, actions=len(g.history), checkpoints=checkpoints, costs=costs,
        enemy_health=18, mana=g.state.players[1].mana, own_hand=len(g.state.players[1].hand),
        returned_random_card=selected.card_id, returned_cost=returned_cost,
        enemy_hand=[g.state.entities[e].card_id for e in g.state.players[2].hand],
        hand_minion_stats=[(g.state.entities[e].card_id, g.state.entities[e].attack, g.state.entities[e].health)
                           for e in g.state.players[1].hand],
        random_roots=sum(e.kind == 'random_choice' for e in g.events), waiting_choices=0)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
