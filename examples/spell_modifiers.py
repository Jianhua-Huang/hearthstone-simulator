"""Native representative player spell budgets, expiry, discovery and terminal play."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit
from examples.hand_progress import play


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',
        hand=('BOT_411','EDR_464','GDB_873','CS2_029','CS2_029','CS2_029'),
        deck=('CS2_182',)*4,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*4)),
        seed=90,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','BOT_411');submit(game,'play_card','EDR_464')
    assert [m.uses_remaining for m in game.state.players[1].spell_modifiers]==[1,3]
    submit(game,'end_turn');submit(game,'end_turn')
    assert [m.uses_remaining for m in game.state.players[1].spell_modifiers]==[3]
    submit(game,'play_card','GDB_873')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.state.pending_choice is not None
        assert match.state.players[1].spell_modifiers[0].uses_remaining==2
        submit(match,'select_choice');assert match.state.pending_choice is not None
        submit(match,'select_choice');assert len(match.state.players[1].combo_modifiers)==2
        play(match,'CS2_029',enemy_hero=True);play(match,'CS2_029',enemy_hero=True)
        assert match.state.entities[match.state.players[2].hero_id].health==6
        assert match.state.players[1].spell_modifiers==[]
        submit(match,'end_turn');submit(match,'end_turn');play(match,'CS2_029',enemy_hero=True)
        assert match.state.status=='finished' and match.state.winner==1
        assert len(match.state.spell_policy_receipts)==3 and len(match.state.cast_history)==7
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('spell-modifier-snapshot.json',snapshot),('spell-modifier-replay.json',build_replay(game)),
                       ('spell-modifier-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),casts=len(game.state.cast_history),
        policy_captures=len(game.state.spell_policy_receipts),winner=game.state.winner,restored_and_replayed=True)))


if __name__=='__main__':main()
