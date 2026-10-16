"""Real Steed, Fireballs and a complete named Stegodon via player commands."""
import json
from hs_sim.cards.constructed import CONTENT_VERSION
from hs_sim.cards.granted_deathrattle_cards import STEED, STEGODON
from hs_sim.engine import Keyword, PlayerSetup, Scenario
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from .card_qualified_next import session

YETI = 'CORE_CS2_182'
SQUIRE = 'CORE_EX1_008'
FIREBALL = 'CORE_CS2_029'


def main():
    setup = Scenario((
        PlayerSetup('HERO_08', hand=(STEED,), board=(YETI, SQUIRE), deck=(YETI,)*8,
                    mana=40, max_mana=40, mana_cap=40),
        PlayerSetup('HERO_08', hand=(FIREBALL, FIREBALL), deck=(YETI,)*8,
                    mana=40, max_mana=40, mana_cap=40)), seed=438)
    def run(game, play, end, submit):
        target = game.state.players[1].board[0]
        play(1, STEED, target_card=YETI)
        assert (game.state.entities[target].attack, game.state.entities[target].health) == (6, 11)
        assert Keyword.TAUNT in game.state.entities[target].keywords
        end(1)
        play(2, FIREBALL, target_card=YETI)
        assert game.state.entities[target].health == 5
        play(2, FIREBALL, target_card=YETI)
        assert [game.state.entities[i].card_id for i in game.state.players[1].board] == [STEGODON, SQUIRE]
        child = game.state.entities[game.state.players[1].board[0]]
        assert (child.attack, child.health) == (2, 6) and Keyword.TAUNT in child.keywords
    scene = session(setup, run)
    result = dict(content_version=CONTENT_VERSION, core_effects_version=CORE_EFFECTS_VERSION,
        snapshot_schema=SNAPSHOT_SCHEMA_VERSION, new_roots=1, new_dependencies=1,
        lab_fixture_definitions=0, actions=scene['actions'], checkpoints=len(scene['checkpoints']),
        scenarios=[scene], formal_pool_complete=False, cn_calibrated=False,
        limit='Short decks, explicit mana and cross-class scenarios are internal experiments.')
    assert (result['actions'], result['checkpoints']) == (4, 5)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == '__main__': main()
