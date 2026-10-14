"""Grouped temporary offers through player ports, including a paused save."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario,GenerationContext,CardType,Zone
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit
from examples.imbue_directed_modification import use


def choose(game,kind,registry):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    option=next(o for o in listing['observation']['pending_choice']['options'] if registry.card(o['card_id']).kind==kind)
    action=next(a for a in listing['actions'] if a['type']=='select_choice' and a['options']==[option['ref']])
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']
    return option['card_id']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_09',hand=('EDR_852',),deck=('CS2_182',)*4,mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*4,mana=10,max_mana=10)),seed=66,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'EDR_852');use(game)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        minion=choose(match,CardType.MINION,registry);submit(match,minion)
        body=next(i for i in match.state.players[1].board if match.state.entities[i].card_id==minion)
        submit(match);submit(match);use(match)
        spell=choose(match,CardType.SPELL,registry)
        temporary=next(i for i in match.state.players[1].hand if match.state.entities[i].card_id==spell)
        assert match.state.entities[temporary].hand_lifetime is not None
        submit(match)
        assert match.state.entities[temporary].zone==Zone.GRAVEYARD
        assert body in match.state.players[1].board
        assert match.state.entities[body].hand_lifetime is None
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('imbue-moon-snapshot.json',snapshot),('imbue-moon-replay.json',build_replay(game)),
        ('imbue-moon-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
