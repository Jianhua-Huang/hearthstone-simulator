"""Timed Stealth plus real Combo cards; explicit mechanism fixture, R-129."""
import json
from pathlib import Path
from hs_sim.engine import (Game,Scenario,PlayerSetup,GenerationContext,CardDefinition,
    CardType,Keyword,TimedKeywordSpec,ComboRepeatSpec,BattlecryRepeatSpec,TriggerSpec)
from hs_sim.engine.effects import RequestChoice,ChoiceOption
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit
from examples.hand_progress import play


def registry():
    r=build_registry()
    r.register_behavior('example.timed-pause-v1',lambda c:[RequestChoice(c.player_id,
        (ChoiceOption('continue','Continue',()),),source_id=c.source_id)])
    r.register_card(CardDefinition('example.timed-aura','Timed Stealth repetition fixture',CardType.MINION,
        health=4,keywords=(Keyword.STEALTH,),timed_keywords=(TimedKeywordSpec(Keyword.STEALTH),),
        combo_repeats=(ComboRepeatSpec(),),battlecry_repeats=(BattlecryRepeatSpec(kinds=(CardType.MINION,)),),
        triggers=(TriggerSpec('attachments_expired','example.timed-pause-v1'),)))
    return r


def run():
    r=registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=('LOE_029','EX1_134','EX1_613'),
        board=('example.timed-aura',),deck=('CS2_182',)*4,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*4)),seed=88,
        generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    aura=game.state.players[1].board[0]
    submit(game,'end_turn')
    assert Keyword.STEALTH in game.state.entities[aura].keywords
    submit(game,'end_turn')
    assert game.state.pending_choice is not None
    assert Keyword.STEALTH not in game.state.entities[aura].keywords
    assert not any(e.kind=='turn_started' and dict(e.data).get('turn')==3 for e in game.events)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice');submit(match,'play_card','LOE_029')
        submit(match,'select_choice');submit(match,'select_choice')
        play(match,'EX1_134',enemy_hero=True);submit(match,'play_card','EX1_613')
        assert len(match.state.combo_history)==4 and len(match.state.battlecry_history)==2
        assert match.state.entities[match.state.players[2].hero_id].health==24
        assert match.observe(1)['players'][0]['board'][0]['keyword_durations']==[]
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('timed-keyword-snapshot.json',snapshot),('timed-keyword-replay.json',build_replay(game)),
                       ('timed-keyword-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),combos=len(game.state.combo_history),
        battlecries=len(game.state.battlecry_history),turn=game.state.turn,restored_and_replayed=True)))


if __name__=='__main__':main()
