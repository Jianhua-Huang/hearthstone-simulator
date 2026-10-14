"""Native experimental source: Brann, discovered Blizzard/Pyroblast and terminal replay."""
import json
from pathlib import Path
from hs_sim.engine import Game,Scenario,PlayerSetup,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit
from examples.hand_progress import play
from examples.excavate_generation import choose


def run():
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hand=('JAIL_123','EX1_279'),board=('LOE_077',),
        deck=('CS2_182',)*8,mana=10,max_mana=10),PlayerSetup('HERO_01',board=('CS2_182',),deck=('CS2_182',)*8)),
        seed=94,generation_context=GenerationContext('local-2026-09-23','experimental')),build_registry())
    play(game,'JAIL_123');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        choose(match,'CS2_028');assert match.state.pending_choice is not None
        choose(match,'EX1_279');submit(match,'end_turn');submit(match,'end_turn')
        play(match,'CS2_028')
        enemy=match.state.entities[match.state.players[2].board[0]];assert enemy.health==1 and enemy.frozen
        submit(match,'end_turn');submit(match,'end_turn');play(match,'EX1_279',enemy_hero=True)
        assert match.state.entities[match.state.players[2].hero_id].health==20
        assert not match.state.play_history[-1].card_spell_repeats
        submit(match,'end_turn');submit(match,'end_turn');play(match,'EX1_279',enemy_hero=True)
        assert match.state.winner==1 and match.state.status=='finished'
        assert len(match.state.cast_history)==5 and len(match.state.battlecry_history)==2
        assert len(match.state.spell_repeats)==2 and not match.state.spell_policy_receipts
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('card-spell-source-snapshot.json',snapshot),('card-spell-source-replay.json',build_replay(game)),
                       ('card-spell-source-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),casts=len(game.state.cast_history),battlecries=len(game.state.battlecry_history),
        captured_card_plays=sum(bool(p.card_spell_repeats) for p in game.state.play_history),
        winner=game.state.winner,restored_and_replayed=True)))


if __name__=='__main__':main()
