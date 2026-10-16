"""A newly adapted real minion played and attacked via bound player JSON commands."""

import json

from hs_sim.cards import build_registry
from hs_sim.cards.constructed import load_batch
from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.replay import build_replay, replay


def main():
    game = Game.from_scenario(Scenario((
        PlayerSetup("HERO_08", hand=("CORE_NEW1_010",), mana=10, max_mana=10),
        PlayerSetup("HERO_08"),
    )), build_registry())
    checkpoints = 0

    def check():
        nonlocal checkpoints
        saved = game.snapshot()
        assert Game.from_snapshot(saved, build_registry()).snapshot() == saved
        assert game.clone().snapshot() == saved
        assert replay(build_replay(game), build_registry()).snapshot() == saved
        assert game.observe(2)["players"][0]["hand"] == [] or all(
            card["card_id"] is None for card in game.observe(2)["players"][0]["hand"])
        checkpoints += 1

    check()
    for action_type in ("play_card", "attack", "attack"):
        listing = game.for_player(1).legal_actions()
        action = next(action for action in listing["actions"] if action["type"] == action_type)
        reply = game.for_player(1).submit({"revision": listing["revision"], "action": action})
        assert reply["accepted"], reply["error"]
        check()
    result = {
        "content_version": game.registry.version,
        "new_cards": len(load_batch()["cards"]),
        "actions": len(game.history), "checkpoints": checkpoints,
        "mana": game.state.players[1].mana,
        "opponent_health": game.state.entities[game.state.players[2].hero_id].health,
        "formal_pool_complete": False,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
