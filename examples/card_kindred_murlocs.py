"""Seven genuine roots and their actual dependencies through player DTOs."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.engine import Keyword, PlayerSetup, Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from hs_sim.engine.information import VIEW_VERSION
from examples.card_qualified_next import session

YETI = 'CORE_CS2_182'


def setup(hand, board=(), deck=(YETI,)*8, seed=1063):
    return Scenario((
        PlayerSetup('HERO_08', hand=hand, board=board, deck=deck,
            mana=30, max_mana=30, mana_cap=30),
        PlayerSetup('HERO_08', deck=(YETI,)*8,
            mana=30, max_mana=30, mana_cap=30)), seed=seed)


def main():
    def murlocs(g, play, end, submit):
        play(1, 'TLC_427'); end(1); end(2)
        play(1, 'DINO_404'); play(1, 'TLC_429'); play(1, 'TIME_428')
        play(1, 'WW_001t', target_player=2); end(1)
        s = g.state
        tokens = [s.entities[i] for i in s.players[1].board if s.entities[i].card_id == 'TLC_429t']
        assert [(e.attack, e.health) for e in tokens] == [(1, 2), (1, 2)]
        yeti = next(s.entities[i] for i in s.players[1].board if s.entities[i].card_id == YETI)
        assert Keyword.RUSH in yeti.keywords and yeti.max_health == 6
        assert s.entities[s.players[2].hero_id].health == 27

    def elementals(g, play, end, submit):
        play(1, 'TLC_223'); end(1); end(2)
        play(1, 'TLC_243'); play(1, 'TLC_903'); play(1, 'TLC_226')
        s = g.state
        assert s.entities[s.players[1].hero_id].attack == 5
        assert sum(s.entities[i].card_id == 'TLC_226' for i in s.players[1].board) == 2
        play(1, 'CS2_029', target_card='TLC_226')
        assert any(g.state.entities[i].card_id == 'WW_001t' for i in g.state.players[1].hand)
        end(1); s = g.state
        drake = next(s.entities[i] for i in s.players[1].board if s.entities[i].card_id == 'TLC_243')
        assert Keyword.IMMUNE not in drake.keywords and s.entities[s.players[1].hero_id].attack == 0

    scenes = [session(setup(('TLC_427', 'DINO_404', 'TLC_429', 'TIME_428'), (YETI,)), murlocs),
        session(setup(('TLC_223', 'TLC_243', 'TLC_903', 'TLC_226', 'CS2_029'),
            deck=(YETI, 'WW_001t', YETI, YETI), seed=1064), elementals)]
    result = dict(content_version=CONTENT_VERSION, core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION, observation_version=VIEW_VERSION,
        roots=7, dependencies=2, actions=sum(s['actions'] for s in scenes),
        checkpoints=sum(len(s['checkpoints']) for s in scenes), scenarios=scenes,
        lab_fixture_definitions=0, formal_pool_complete=False, cn_calibrated=False)
    assert (result['actions'], result['checkpoints']) == (16, 18)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__':
    main()
