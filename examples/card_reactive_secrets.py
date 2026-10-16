"""Two real secrets through player commands and independent portable checkpoints."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from hs_sim.cards import build_registry
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def exercise(setup, run):
    game = Game.from_scenario(setup, build_registry())
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
    def play(player, card_id, target_card=None):
        def choose(listing):
            players = {p['id']:p for p in listing['observation']['players']}
            card = next(c for c in players[player]['hand'] if c['card_id'] == card_id)
            target = (next(c['ref'] for p in players.values() for c in p['board'] if c['card_id'] == target_card)
                      if target_card else None)
            return next(a for a in listing['actions'] if a['type'] == 'play_card'
                        and a['card'] == card['ref'] and a.get('target') == target)
        submit(player, choose)
    def end(player):
        submit(player, lambda listing: next(a for a in listing['actions'] if a['type'] == 'end_turn'))
    check(); run(game, play, end, submit)
    assert game.state.pending_choice is None
    for viewer in (1, 2):
        public = json.dumps(game.for_player(viewer).observe())+json.dumps(game.player_events(viewer))
        assert '"death_id"' not in public and '"secret_instance_id"' not in public
    return dict(actions=len(game.history), checkpoints=checkpoints,
                owner_health=game.state.entities[game.state.players[1].hero_id].health,
                owner_board=[game.state.entities[e].card_id for e in game.state.players[1].board],
                enemy_board=[game.state.entities[e].card_id for e in game.state.players[2].board],
                revealed=sum(event.kind == 'secret_revealed' for event in game.events),
                resurrections=len(game.state.resurrection_history))


def main():
    def attack(game, play, end, submit):
        play(1, 'JAIL_315'); end(1)
        def choose(listing):
            players = {p['id']:p for p in listing['observation']['players']}
            return next(a for a in listing['actions'] if a['type'] == 'attack'
                        and a['defender'] == players[1]['hero']['ref'])
        submit(2, choose)
        sheep = game.state.entities[game.state.players[2].board[0]]
        assert (sheep.card_id, sheep.attack, sheep.health, sheep.attacks_this_turn) == ('CS2_tk1', 1, 1, 1)
    first = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('JAIL_315',), deck=('CORE_CS2_182',)*2, mana=10, max_mana=10),
        PlayerSetup('HERO_08', board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*2, mana=10, max_mana=10)), seed=227), attack)
    assert (first['owner_health'], first['enemy_board'], first['revealed']) == (29, ['CS2_tk1'], 1)
    def resummon(game, play, end, submit):
        play(1, 'CORE_CS2_182'); original = game.state.players[1].board[0]
        play(1, 'TIME_620'); end(1); play(2, 'CORE_CS2_029', 'CORE_CS2_182')
        body = game.state.entities[game.state.players[1].board[0]]
        assert (body.card_id, body.attack, body.health, body.origin_entity_id) == ('CORE_CS2_182', 4, 5, original)
        assert body.id != original and not game.state.players[1].secrets
    second = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CORE_CS2_182', 'TIME_620'), deck=('CORE_CS2_182',)*2, mana=10, max_mana=10),
        PlayerSetup('HERO_08', hand=('CORE_CS2_029',), deck=('CORE_CS2_182',)*2, mana=10, max_mana=10)), seed=227), resummon)
    assert (second['owner_board'], second['resurrections'], second['revealed']) == (['CORE_CS2_182'], 1, 1)
    result = dict(content_version='constructed-cn37-preview-v15', schema_version=SNAPSHOT_SCHEMA_VERSION, formal_pool_complete=False,
                  roots=2, actions=first['actions']+second['actions'],
                  checkpoints=len(first['checkpoints'])+len(second['checkpoints']), waiting_choices=0,
                  scenarios=[first, second])
    assert (result['actions'], result['checkpoints']) == (7, 9)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
