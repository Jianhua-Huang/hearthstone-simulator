"""Synthetic 21-entry history, a 20-payload cap, random order, and saved choices.

This is a mechanism fixture, not the Shudderwock card adapter.
"""
import json
from pathlib import Path
from hs_sim.engine import (Game, Registry, CardDefinition, CardType, PlayerSetup, Scenario,
    RepeatPlayedBattlecrySequence, PlayCard, SelectChoice)
from hs_sim.engine.effects import GainArmor, ReturnToHand, RequestChoice, ChoiceOption
from hs_sim.engine.replay import build_replay, replay


def build_registry():
    registry=Registry('bounded-battlecry-example-v1')
    registry.register_card(CardDefinition('fixture.hero','实验英雄',CardType.HERO,health=30))
    def payload(c):
        if c.battlecry.origin=='hand': return [GainArmor(1,1),ReturnToHand(c.source_id)]
        return [RequestChoice(1,(ChoiceOption('continue','继续',()),),source_id=c.source_id),GainArmor(1,1)]
    registry.register_behavior('fixture.payload',payload)
    registry.register_behavior('fixture.sequence',lambda c:[RepeatPlayedBattlecrySequence(1,c.source_id,20,
        selection='random',order='random',choices='player')])
    for name in ('payload','sequence'):
        registry.register_card(CardDefinition('fixture.'+name,'实验：'+name,CardType.MINION,health=4,battlecry='fixture.'+name))
    return registry


def choose(game):
    port=game.for_player(1);listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='select_choice')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('fixture.hero',hand=('fixture.payload','fixture.sequence')),
        PlayerSetup('fixture.hero')),seed=73),registry)
    payload,sequence=game.state.players[1].hand
    for _ in range(21): game.apply(PlayCard(1,payload))
    game.apply(PlayCard(1,sequence));snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        while match.state.pending_choice: choose(match)
        children=[b for b in match.state.battlecry_history if b.origin=='played_history']
        assert len(children)==20 and len({b.history_play_id for b in children})==20
        assert len(match.state.play_history)==22
        assert match.state.entities[match.state.players[1].hero_id].armor==41
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('bounded-battlecry-snapshot.json',snapshot),('bounded-battlecry-replay.json',build_replay(game)),
        ('bounded-battlecry-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        battlecries=len(game.state.battlecry_history),hand_plays=len(game.state.play_history),
        history_candidates=21,direct_attempts=20,restored_and_replayed=True)))


if __name__=='__main__':main()
