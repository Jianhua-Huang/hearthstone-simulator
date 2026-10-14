"""Existing Brann/Jeweled Scarab with explicit synthetic source fixtures.

The fixtures exercise shared primitives; they are not Macaw card adapters.
"""
import json
from pathlib import Path
from hs_sim.engine import (Game, Scenario, PlayerSetup, GenerationContext, CardDefinition,
    CardType, TriggerBattlecry, RepeatBattlecries, BattlecryHistoryQuery)
from hs_sim.engine.sacrifice import MinionReference
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def registry():
    r=build_registry()
    r.register_behavior('fixture.trigger',lambda c:[TriggerBattlecry(MinionReference.capture(
        next(c.state.entities[i] for i in c.state.players[1].board if c.state.entities[i].card_id=='LOE_029')),
        c.source_id,choices='player')])
    r.register_behavior('fixture.repeat',lambda c:[RepeatBattlecries(c.player_id,c.source_id,
        BattlecryHistoryQuery(origins=('effect',)),choices='player')])
    r.register_card(CardDefinition('fixture_trigger','间接战吼测试入口',CardType.SPELL,on_play='fixture.trigger'))
    r.register_card(CardDefinition('fixture_repeat','历史重演测试载体',CardType.MINION,cost=2,
        attack=2,health=3,battlecry='fixture.repeat'))
    return r


def run():
    r=registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',board=('LOE_077','LOE_029'),
        hand=('fixture_trigger','fixture_repeat'),deck=('CS2_182',)*4,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*4)),seed=80,
        generation_context=GenerationContext('local-2026-09-23','experimental')),r)
    submit(game,'play_card','fixture_trigger');submit(game,'select_choice')
    submit(game,'play_card','fixture_repeat')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),r)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice');submit(match,'select_choice')
        assert [b.origin for b in match.state.battlecry_history]==['effect','hand','history','hand','history']
        assert [b.history_id for b in match.state.battlecry_history if b.origin=='history']==[1,1]
        assert len(match.state.play_history)==2 and len(match.state.battlecry_batches)==1
        assert match.state.players[1].mana==8
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),r).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('indirect-battlecry-snapshot.json',snapshot),
        ('indirect-battlecry-replay.json',build_replay(game)),('indirect-battlecry-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        battlecries=len(game.state.battlecry_history),hand_plays=len(game.state.play_history),
        restored_and_replayed=True,uses_synthetic_source_fixtures=True)))


if __name__=='__main__':main()
