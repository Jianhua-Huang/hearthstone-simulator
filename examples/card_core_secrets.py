"""All seven new Core secret roots through two actual player-command scenarios."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def exercise(setup, run):
    g = Game.from_scenario(setup, build_registry()); checkpoints = []
    def check():
        saved = g.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert g.clone().snapshot() == saved
        assert replay(build_replay(g), build_registry()).snapshot() == saved
        checkpoints.append('ready')
    def submit(player, choose):
        listing = g.for_player(player).legal_actions(); action = choose(listing)
        reply = g.for_player(player).submit({'revision': listing['revision'], 'action': action})
        assert reply['accepted'], reply.get('error'); check()
    def play(player, cid, enemy_hero=False):
        def choose(listing):
            players = {p['id']:p for p in listing['observation']['players']}
            card = next(c for c in players[player]['hand'] if c['card_id'] == cid)
            target = players[3-player]['hero']['ref'] if enemy_hero else None
            return next(a for a in listing['actions'] if a['type'] == 'play_card'
                        and a['card'] == card['ref'] and a.get('target') == target)
        submit(player, choose)
    def end(player):
        submit(player, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    def attack(cid, minion_target=False):
        def choose(listing):
            players = {p['id']:p for p in listing['observation']['players']}
            attacker = next(e for e in players[2]['board'] if e['card_id'] == cid)
            target = next(e['ref'] for e in players[1]['board'] if e['card_id'] == 'CORE_CS2_182') if minion_target else players[1]['hero']['ref']
            return next(a for a in listing['actions'] if a['type'] == 'attack'
                        and a['attacker'] == attacker['ref'] and a['defender'] == target)
        submit(2, choose)
    check(); run(g, play, end, attack)
    assert g.state.pending_choice is None
    for viewer in (1, 2):
        public = json.dumps(g.for_player(viewer).observe())+json.dumps(g.player_events(viewer))
        assert '"condition_id"' not in public and '"secret_instance_id"' not in public
    return dict(actions=len(g.history), checkpoints=checkpoints,
        owner_health=g.state.entities[g.state.players[1].hero_id].health,
        owner_armor=g.state.entities[g.state.players[1].hero_id].armor,
        owner_board=[g.state.entities[e].card_id for e in g.state.players[1].board],
        remaining_secrets=len(g.state.players[1].secrets),
        revealed=sum(e.kind == 'secret_revealed' for e in g.events),
        random_roots=sum(e.kind == 'random_choice' for e in g.events))


def main():
    first = ('CORE_EX1_287', 'CORE_EX1_289', 'CORE_EX1_610', 'CORE_EX1_611', 'CORE_BAR_812')
    def attacks(g, play, end, attack):
        for cid in first: play(1, cid)
        end(1); play(2, 'CORE_CS2_029', True)
        assert g.state.play_history[-1].countered
        attack('CORE_CS2_182'); attack('CORE_NEW1_010', True)
        assert not g.state.players[1].secrets
        assert any(g.state.entities[e].card_id == 'CS2_033' for e in g.state.players[1].board)
    a = exercise(Scenario((
        PlayerSetup('HERO_08', hand=first, board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*2,
                    mana=50, max_mana=50, mana_cap=50),
        PlayerSetup('HERO_08', hand=('CORE_CS2_029',), board=('CORE_CS2_182', 'CORE_NEW1_010'),
                    deck=('CORE_CS2_182',)*2, mana=50, max_mana=50, mana_cap=50)), seed=211), attacks)
    assert (a['actions'], a['revealed'], a['owner_health'], a['owner_armor']) == (9, 5, 30, 8)
    def after_plays(g, play, end, attack):
        play(1, 'CORE_GIL_577'); play(1, 'CORE_ULD_152'); end(1)
        play(2, 'CORE_CS2_029', True); assert not g.state.players[2].board
        play(2, 'GAME_005'); play(2, 'CORE_EX1_145')
        assert [g.state.entities[e].card_id for e in g.state.players[1].board] == ['GIL_577t']
        assert not g.state.players[1].secrets
    b = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_GIL_577', 'CORE_ULD_152'), deck=('CORE_CS2_182',)*2,
                    mana=50, max_mana=50, mana_cap=50),
        PlayerSetup('HERO_08', hand=('CORE_CS2_029', 'GAME_005', 'CORE_EX1_145'),
                    board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*2,
                    mana=50, max_mana=50, mana_cap=50)), seed=211), after_plays)
    assert (b['actions'], b['revealed'], b['owner_health'], b['random_roots']) == (6, 2, 24, 1)
    result = dict(content_version='constructed-cn37-preview-v13', schema_version=SNAPSHOT_SCHEMA_VERSION,
        formal_pool_complete=False, roots=7, scenarios=[a, b],
        actions=a['actions']+b['actions'], checkpoints=len(a['checkpoints'])+len(b['checkpoints']), waiting_choices=0)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
