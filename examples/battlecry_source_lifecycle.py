"""Synthetic ownership transfer, P2 choice, then source-dependent stop."""
import json
from pathlib import Path
from hs_sim.engine import (Game,Registry,CardDefinition,CardType,PlayerSetup,Scenario,PlayCard,
    RepeatPlayedBattlecrySequence,BattlecrySequencePolicy)
from hs_sim.engine.effects import GainArmor,ReturnToHand,ChangeControl,RequestChoice,ChoiceOption
from hs_sim.engine.replay import build_replay,replay


def build_registry():
    registry=Registry('battlecry-source-lifecycle-example-v1')
    registry.register_card(CardDefinition('fixture.hero','实验英雄',CardType.HERO,health=30))
    def transfer(c): return [] if c.battlecry.origin=='hand' else [ChangeControl(c.source_id,2)]
    def choose(c):
        return [] if c.battlecry.origin=='hand' else [RequestChoice(c.player_id,
            (ChoiceOption('gain','获得护甲',(GainArmor(c.player_id,3),)),),source_id=c.source_id)]
    def bounce(c): return [] if c.battlecry.origin=='hand' else [ReturnToHand(c.source_id)]
    callbacks={'transfer':transfer,'choose':choose,'bounce':bounce,'armor':lambda c:[GainArmor(c.player_id,1)],
        'sequence':lambda c:[RepeatPlayedBattlecrySequence(c.player_id,c.source_id,4,choices='player',
            policy=BattlecrySequencePolicy('same_incarnation','current',exclude_source_target=True))]}
    for name,callback in callbacks.items():
        registry.register_behavior('fixture.'+name,callback)
        registry.register_card(CardDefinition('fixture.'+name,'实验：'+name,CardType.MINION,health=4,battlecry='fixture.'+name))
    return registry


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('fixture.hero',hand=tuple('fixture.'+n for n in
        ('transfer','choose','bounce','armor','sequence'))),PlayerSetup('fixture.hero')),seed=73),registry)
    for entity_id in tuple(game.state.players[1].hand):game.apply(PlayCard(1,entity_id))
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.state.pending_choice.player_id==2
        assert match.for_player(1).observe()['observation']['pending_choice']=={'player_id':2}
        port=match.for_player(2);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='select_choice')
        assert port.submit({'revision':listing['revision'],'action':action})['accepted']
        children=[b for b in match.state.battlecry_history if b.origin=='played_history']
        assert [(b.player_id,b.history_player_id,b.history_play_id) for b in children]==[(1,1,1),(2,1,2),(2,1,3)]
        assert match.state.entities[match.state.players[2].hero_id].armor==3
        assert len(match.state.players[2].hand)==1 and not match.state.players[2].board
        assert len(match.state.play_history)==5 and len(match.state.battlecry_history)==8
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('battlecry-source-snapshot.json',snapshot),('battlecry-source-replay.json',build_replay(game)),
        ('battlecry-source-view.json',game.for_player(2).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),battlecries=len(game.state.battlecry_history),
        direct_attempts=3,stopped_on_bounce=True,restored_and_replayed=True)))


if __name__=='__main__':main()
