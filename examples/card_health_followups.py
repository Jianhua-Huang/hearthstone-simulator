"""Ten current real cards through player commands and portable checkpoints."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
import json
from examples.card_reactive_secrets import exercise
from hs_sim.engine import Keyword, PlayerSetup, Scenario


def hero_play(game, submit, card_id, enemy=2):
    def choose(listing):
        players = {p['id']: p for p in listing['observation']['players']}
        card = next(c for c in players[1]['hand'] if c['card_id'] == card_id)
        return next(a for a in listing['actions'] if a['type'] == 'play_card'
                    and a['card'] == card['ref'] and a.get('target') == players[enemy]['hero']['ref'])
    submit(1, choose)


def main():
    def aliases(game, play, end, submit):
        play(1, 'CATA_582')
        assert game.state.entities[game.state.players[1].hero_id].attack == 3
        assert not game.state.players[1].board
        assert len(game.state.players[1].hand) == 5  # Thalnos draws after the first damage batch.
        play(1, 'CORE_CS2_028')
        assert all(game.state.entities[e].health == 1 and game.state.entities[e].frozen
                   for e in game.state.players[2].board)
        play(1, 'CORE_CS2_024', 'CORE_CS2_182')
        play(1, 'CORE_CS1_112')
        assert not game.state.players[2].board
        hero_play(game, submit, 'CORE_EX1_134')
        assert game.state.entities[game.state.players[2].hero_id].health == 27
        end(1)
        assert game.state.entities[game.state.players[1].hero_id].attack == 0
    first = exercise(Scenario((
        PlayerSetup('HERO_08', hand=('CATA_582', 'CORE_CS2_028', 'CORE_CS2_024', 'CORE_CS1_112', 'CORE_EX1_134'),
            board=('CORE_EX1_012',), deck=('CORE_CS2_182',)*2, mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182',)*2, deck=('CORE_CS2_182',)*2)), seed=233), aliases)

    def health(game, play, end, submit):
        own = game.state.players[1].board[0]
        play(1, 'CORE_BOT_222', 'CORE_CS2_182')
        assert game.state.entities[own].health == 1
        assert game.state.entities[game.state.players[1].hero_id].health == 26
        play(1, 'CATA_302', 'CORE_CS2_182')
        assert game.state.entities[own].health == 5
        play(1, 'CORE_ICC_055', 'CS2_033')
        assert game.state.entities[game.state.players[1].hero_id].health == 29
        hero_play(game, submit, 'CORE_SW_442')
        assert game.state.entities[game.state.players[1].hero_id].health == 30
        play(1, 'CATA_485', 'CS2_033')
        rows = [r.health_result for r in game.state.damage_history if r.health_result.source_card_id == 'CATA_485']
        assert [r.damage_dealt for r in rows] == [2, 1]
        assert rows[1].target_card_id in ('CORE_CS2_182', 'CS2_033')
        assert len(game.state.players[1].hand) == 1
    second = exercise(Scenario((
        PlayerSetup('HERO_09', hand=('CORE_BOT_222', 'CATA_302', 'CORE_ICC_055', 'CORE_SW_442', 'CATA_485'),
            board=('CORE_CS2_182',), deck=('CORE_CS2_182',)*2, mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', board=('CORE_CS2_182', 'CS2_033'), deck=('CORE_CS2_182',)*2)), seed=233), health)
    result = dict(content_version='constructed-cn37-preview-v17', schema_version=SNAPSHOT_SCHEMA_VERSION,
        roots=10, formal_pool_complete=False, cn_calibrated=False, waiting_choices=0,
        actions=first['actions']+second['actions'],
        checkpoints=len(first['checkpoints'])+len(second['checkpoints']), scenarios=[first, second])
    assert (result['actions'], result['checkpoints']) == (11, 13)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return result


if __name__ == '__main__': main()
