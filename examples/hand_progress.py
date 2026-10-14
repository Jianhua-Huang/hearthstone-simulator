"""Mixed-class Corrupt/Infuse scenario; every action uses the player port."""
import json
from pathlib import Path

from hs_sim.engine import Game, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def play(game, card_id, target_card=None, enemy_hero=False):
    port=game.for_player(1);listing=port.legal_actions();players=listing['observation']['players']
    ref=next(c['ref'] for c in players[0]['hand'] if c['card_id']==card_id)
    target=players[1]['hero']['ref'] if enemy_hero else next(
        (c['ref'] for p in players for c in p['board'] if c['card_id']==target_card),None)
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==ref and a.get('target')==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def end_turn(game, player):
    port=game.for_player(player);listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='end_turn')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('DMF_073','DMF_124','DMF_248','REV_956','REV_601','CS2_029','CS2_029','SCH_248'),
            board=('CS2_101t',)*3,deck=('CS2_182',)*10,max_mana=10,mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*10,max_mana=10,mana=10)),seed=111),registry)
    play(game,'CS2_029','CS2_101t')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        play(match,'CS2_029','CS2_101t');play(match,'SCH_248','CS2_101t')
        end_turn(match,1);end_turn(match,2)
        play(match,'REV_601t',enemy_hero=True);play(match,'REV_956t');play(match,'DMF_248t')
        state=match.state;own=state.players[1]
        hand={state.entities[i].card_id:state.entities[i] for i in own.hand}
        # The second Fireball and the later three-mana weapon each corrupt it again.
        assert (hand['DMF_124t'].attack,hand['DMF_124t'].health)==(5,5)
        assert 'DMF_073t' in hand and 'SCH_248' in hand
        progress=next(a for a in hand['REV_601'].abilities if a.kind=='hand_progress')
        assert progress.progress_value==0 and not progress.progress_keys
        priest=next(state.entities[i] for i in own.board if state.entities[i].card_id=='REV_956t')
        assert (priest.attack,priest.health)==(4,5)
        weapon=state.entities[own.weapon_id]
        assert (weapon.attack,weapon.durability)==(4,3)
        assert state.entities[state.players[2].hero_id].health==27
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();output=Path(__file__).resolve().parents[1]/'outputs';output.mkdir(exist_ok=True)
    for name,data in (('hand-progress-snapshot.json',snapshot),('hand-progress-replay.json',build_replay(game)),
                      ('hand-progress-view.json',game.observe(1))):
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
