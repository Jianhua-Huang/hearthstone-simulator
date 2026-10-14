"""Six player commands: Herald, live-neighbor sacrifice, healing and save/replay."""
import json
from pathlib import Path
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def play_rightmost(game, card):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
    ref=next(c['ref'] for c in own['hand'] if c['card_id']==card)
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref
        and a.get('position')==len(own['board']) and a.get('target') is None)
    result=port.submit({'revision':listing['revision'],'action':action})
    assert result['accepted']


def run():
    registry=build_registry()
    registry.register_card(CardDefinition('fixture.warlock','术士测试英雄',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.WARLOCK,),None)))
    game=Game.from_scenario(Scenario((PlayerSetup('fixture.warlock',hand=('CATA_725','CATA_725','CS2_182'),
        deck=('CS2_182',)*10,max_mana=10,mana=10),PlayerSetup('HERO_08',hand=('CS2_029',),
        deck=('CS2_182',)*10,max_mana=10,mana=10)),active_player=2,seed=74),registry)
    port=game.for_player(2);listing=port.legal_actions()
    target=listing['observation']['players'][0]['hero']['ref']
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a.get('target')==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']
    submit(game);play_rightmost(game,'CATA_725');play_rightmost(game,'CATA_725');play_rightmost(game,'CS2_182')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match)
        state=match.state
        assert [(state.entities[i].card_id,state.entities[i].attack,state.entities[i].health)
            for i in state.players[1].board]==[('CATA_725',2,1),('CATA_725t',3,3),('CATA_725t',3,3)]
        assert len(state.death_history)==2 and len(state.herald_history)==2
        assert state.entities[state.players[1].hero_id].health==27
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('sacrifice-snapshot.json',snapshot),('sacrifice-replay.json',build_replay(game)),
                      ('sacrifice-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
