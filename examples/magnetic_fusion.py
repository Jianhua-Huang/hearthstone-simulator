"""Five real Magnetic upgrades through player DTOs, including save and replay."""
import json
from pathlib import Path

from hs_sim.engine import Game, Keyword, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game, card_id=None):
    port=game.for_player(game.state.active_player)
    listing=port.legal_actions()
    if card_id is None:
        action=next(a for a in listing['actions'] if a['type']=='end_turn')
    else:
        own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
        ref=next(c['ref'] for c in own['hand'] if c['card_id']==card_id)
        action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref
                    and a.get('magnetic_target')==own['board'][0]['ref'])
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',board=('BOT_563',),
            hand=('BOT_911','BOT_251','DEEP_015','BOT_107','BOT_035'),
            deck=('CS2_182',)*12,max_mana=10,mana=10),
        PlayerSetup('HERO_08',board=('CS2_182','CS2_182'),deck=('CS2_182',)*12,max_mana=10,mana=10)),seed=115),registry)
    submit(game,'BOT_911');submit(game,'BOT_251');submit(game,'DEEP_015')
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match);submit(match);submit(match,'BOT_107');submit(match,'BOT_035');submit(match)
        state=match.state;host=state.entities[state.players[1].board[0]]
        assert (host.attack,host.health)==(19,18)
        assert {Keyword.DIVINE_SHIELD,Keyword.TAUNT,Keyword.REBORN,Keyword.POISONOUS}<=host.keywords
        assert len(state.players[1].board)==1 and not state.players[2].board
        assert len(state.magnetic_history)==5 and len(state.death_history)==2
        assert state.entities[state.players[1].hero_id].health==29
        assert state.entities[state.players[2].hero_id].health==29
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('magnetic-snapshot.json',snapshot),('magnetic-replay.json',build_replay(game)),
                      ('magnetic-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                      'restored_and_replayed':True}))


if __name__=='__main__':main()
