"""Hidden secrets, counter, spell redirection, bounce and attack replacement."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def command(game, kind, card_id=None, target='hero'):
    port=game.for_player(game.state.active_player)
    listing=port.legal_actions();players=listing['observation']['players']
    hand={c['ref']:c['card_id'] for p in players for c in p['hand']}
    target_ref=players[0]['hero']['ref'] if target=='hero' else players[0]['board'][0]['ref']
    action=next(a for a in listing['actions'] if a['type']==kind and
        (card_id is None or hand.get(a.get('card'))==card_id) and
        (kind!='play_card' or a.get('target') is None or a['target']==target_ref) and
        (kind!='attack' or a['defender']==target_ref))
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('EX1_287','tt_010','EX1_611','EX1_130'),board=('CS2_182',),
            deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029','CS2_029'),board=('CS2_182','CS2_182'),
            deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=97),registry)
    for card in ('EX1_287','tt_010','EX1_611','EX1_130'):
        command(game,'play_card',card)
    hidden=game.observe(2)
    assert all(s['card_id'] is None for s in hidden['players'][0]['secrets'])
    command(game,'end_turn')
    command(game,'play_card','CS2_029')
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        command(match,'play_card','CS2_029',target='minion')
        command(match,'attack')
        command(match,'attack')
        assert not match.state.players[1].secrets
        assert match.state.entities[match.state.players[1].hero_id].health==30
        assert match.state.entities[match.state.players[1].board[0]].health==5
        assert match.state.entities[match.state.players[2].board[0]].health==3
        assert any(match.state.entities[i].cost==6 for i in match.state.players[2].hand)
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot,hidden


def main():
    game,snapshot,hidden=run()
    output=Path(__file__).resolve().parents[1]/'outputs';output.mkdir(exist_ok=True)
    for name,data in (('secrets-snapshot.json',snapshot),('secrets-replay.json',build_replay(game)),
                       ('secrets-hidden-view.json',hidden),('secrets-final-view.json',game.observe(2))):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                     'restored_and_replayed':True}))


if __name__=='__main__':main()
