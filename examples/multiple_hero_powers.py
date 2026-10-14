"""Artificial multi-power setup using existing adapters, not a legal starting deck."""
import json
from pathlib import Path
from hs_sim.engine import Game, PlayerSetup, Scenario, GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def use(game, additional=False):
    port=game.for_player(1); listing=port.legal_actions(); players=listing['observation']['players']
    own,enemy=players
    power=own['additional_hero_powers'][0] if additional else own['hero_power']
    target=None if additional else enemy['hero']['ref']
    action=next(a for a in listing['actions'] if a['type']=='use_hero_power'
                and a['power']==power['ref'] and a['target']==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def choose(game):
    port=game.for_player(1); listing=port.legal_actions()
    action=next(a for a in listing['actions'] if a['type']=='select_choice')
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_08',hero_power_card_id='HERO_08bp',
        additional_hero_power_card_ids=('EDR_449p',),deck=('CS2_182',)*3,mana=10,max_mana=10),
        PlayerSetup('HERO_01',deck=('CS2_182',)*3)),seed=67,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    use(game); use(game,True); snapshot=game.snapshot()
    assert snapshot['state']['hero_power_history'][-1]['completed'] is False
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        choose(match)
        assert match.state.players[1].hero_power_uses_this_turn==2
        assert match.state.players[1].mana==6
        submit(match); submit(match)
        use(match,True); choose(match); use(match)
        assert match.state.entities[match.state.players[2].hero_id].health==28
        assert match.state.players[1].hero_power_uses_this_turn==2
        assert len(match.state.hero_power_history)==4
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run(); out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('multiple-powers-snapshot.json',snapshot),
                       ('multiple-powers-replay.json',build_replay(game)),
                       ('multiple-powers-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),
        'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__': main()
