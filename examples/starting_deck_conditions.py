"""Experimental eight-card constructed origin, permanent policy and discovery."""
from dataclasses import replace
import json
from pathlib import Path
from hs_sim.engine import Game, MatchSetup, DeckCondition, matches_deck_condition
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def run():
    root=Path(__file__).resolve().parents[1]
    base=MatchSetup.from_dict(json.loads((root/'examples/matches/constructed.json').read_text(encoding='utf-8')))
    common=('LOE_029','CS2_182','CS2_179','EX1_096','FP1_007','ULD_205','ULD_208')
    warrior=('DEEP_020',*common);mage=('EX1_012',*common)
    setup=replace(base,decks=(replace(base.decks[1],cards=warrior),replace(base.decks[0],cards=mage)),
        policy=replace(base.policy,id='starting-condition-fixture-v1',deck_size=8,
            allowed_card_ids=tuple(sorted(set(warrior+mage)))),first_player=1,seed=82)
    registry=build_registry();game=Game.from_decks(setup,registry)
    while game.state.pending_choice:
        routing=game.for_player(1).observe()['observation']['pending_choice']
        port=game.for_player(routing['player_id']);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='select_choice' and not a['options'])
        assert port.submit({'revision':listing['revision'],'action':action})['accepted']
    for _ in range(20):
        if game.state.active_player==1 and game.state.players[1].mana>=6:break
        submit(game,'end_turn')
    else:raise AssertionError('Fixture did not reach six mana')
    assert matches_deck_condition(game.state,registry,1,DeckCondition('starting'))
    submit(game,'play_card','DEEP_020')
    assert len(game.state.battlecry_history)==1
    submit(game,'end_turn');submit(game,'end_turn');submit(game,'play_card','LOE_029')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        assert match.for_player(2).observe()['observation']['pending_choice']=={'player_id':1}
        submit(match,'select_choice');submit(match,'select_choice')
        assert match.state.pending_choice is None
        assert len(match.state.players[1].battlecry_modifiers)==1
        assert len(match.state.battlecry_history)==3 and len(match.state.play_history)==2
        assert match.state.players[1].original_deck==warrior
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('starting-deck-snapshot.json',snapshot),('starting-deck-replay.json',build_replay(game)),
        ('starting-deck-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),battlecries=len(game.state.battlecry_history),
        constructed_origin=True,restored_and_replayed=True)))


if __name__=='__main__':main()
