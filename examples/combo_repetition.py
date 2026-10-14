"""Real Combo cards with explicit synthetic repetition/policy fixtures (R-128).

These fixtures test public mechanisms; they do not claim to implement Shark or
Lucky Comet. Replay uses this exact extended registry through the Python API.
"""
import json
from pathlib import Path
from hs_sim.engine import (Game,Scenario,PlayerSetup,GenerationContext,CardDefinition,CardType,
    ComboRepeatSpec,BattlecryRepeatSpec,AddComboRepeatModifier,TriggerSpec)
from hs_sim.engine.effects import RequestChoice,ChoiceOption
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit
from examples.hand_progress import play


def registry():
    r=build_registry()
    r.register_behavior('example.combo-policy-v1',lambda c:[AddComboRepeatModifier(c.player_id,
        ComboRepeatSpec(3),source_id=c.source_id,uses=1,trigger='activation')])
    r.register_behavior('example.combo-pause-v1',lambda c:[RequestChoice(c.player_id,
        (ChoiceOption('continue','Continue',()),),source_id=c.source_id)])
    r.register_card(CardDefinition('example.combo-power','Combo policy fixture',CardType.HERO_POWER,on_use='example.combo-policy-v1'))
    r.register_card(CardDefinition('example.combo-aura','Mixed repetition fixture',CardType.MINION,health=4,
        combo_repeats=(ComboRepeatSpec(),),battlecry_repeats=(BattlecryRepeatSpec(),),
        triggers=(TriggerSpec('combo_modifier_used','example.combo-pause-v1'),)))
    return r


def run():
    r=registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_03',hand=('LOE_029','EX1_134','EX1_613'),
        board=('example.combo-aura',),hero_power_card_id='example.combo-power',deck=('CS2_182',)*4,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*4)),seed=87,
        generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    submit(game,'use_hero_power');submit(game,'play_card','LOE_029')
    submit(game,'select_choice');submit(game,'select_choice')
    play(game,'EX1_134',enemy_hero=True)
    assert game.state.pending_choice is not None and game.state.combo_history==[]
    assert game.state.players[1].combo_modifiers==[]
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice');submit(match,'play_card','EX1_613')
        assert [b.plan.repetitions for b in match.state.combo_batches]==[3,2]
        assert len(match.state.combo_history)==5 and len(match.state.battlecry_history)==2
        assert sum(bool(r.modifiers) for r in match.state.combo_policy_receipts)==1 and len(match.state.play_history)==3
        assert match.state.entities[match.state.players[2].hero_id].health==21
        edwin=next(match.state.entities[i] for i in match.state.players[1].board if match.state.entities[i].card_id=='EX1_613')
        assert (edwin.attack,edwin.health)==(10,10) and match.state.players[1].mana==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('combo-repeat-snapshot.json',snapshot),('combo-repeat-replay.json',build_replay(game)),
        ('combo-repeat-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),combos=len(game.state.combo_history),
        battlecries=len(game.state.battlecry_history),policy_captures=sum(bool(r.modifiers) for r in game.state.combo_policy_receipts),restored_and_replayed=True)))


if __name__=='__main__':main()
