"""Native real representative pack: Shark, Comet and three Combo payload types."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup,GenerationContext,Keyword,SelectChoice
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit
from examples.hand_progress import play


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',
        hand=('TRL_092','GDB_873','GAME_005','LOE_029','EX1_131','EX1_613'),
        deck=('CS2_182',)*4,mana=10,max_mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*4)),
        seed=89,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','TRL_092');submit(game,'play_card','GDB_873')
    assert game.state.pending_choice is not None and game.state.players[1].combo_modifiers==[]
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        choice=match.state.pending_choice;option=next(o for o in choice.options if o.card_id=='EX1_134')
        match.apply(SelectChoice(choice.player_id,choice.id,(option.id,)))
        assert len(match.state.players[1].combo_modifiers)==1
        submit(match,'end_turn');submit(match,'end_turn')
        shark=match.state.entities[match.state.players[1].board[0]]
        assert Keyword.STEALTH not in shark.keywords
        submit(match,'play_card','GAME_005');submit(match,'play_card','LOE_029')
        submit(match,'select_choice');submit(match,'select_choice')
        submit(match,'play_card','EX1_131');play(match,'EX1_134',enemy_hero=True)
        submit(match,'play_card','EX1_613')
        board=[match.state.entities[i] for i in match.state.players[1].board]
        assert len(board)==7 and sum(e.card_id=='EX1_131t' for e in board)==2
        edwin=next(e for e in board if e.card_id=='EX1_613');assert (edwin.attack,edwin.health)==(18,18)
        assert len(match.state.combo_history)==6 and len(match.state.battlecry_history)==2
        assert match.state.entities[match.state.players[2].hero_id].health==24
        assert sum(bool(r.modifiers) for r in match.state.combo_policy_receipts)==1 and match.state.players[1].combo_modifiers==[]
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('combo-source-snapshot.json',snapshot),('combo-source-replay.json',build_replay(game)),
                       ('combo-source-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),combos=len(game.state.combo_history),battlecries=len(game.state.battlecry_history),
        policy_captures=sum(bool(r.modifiers) for r in game.state.combo_policy_receipts),restored_and_replayed=True)))


if __name__=='__main__':main()
