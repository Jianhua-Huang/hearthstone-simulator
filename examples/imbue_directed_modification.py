"""Hunter hand modifications and Shaman directed transformation through player ports."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit


def use(game,target_card=None):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
    target=next(e['ref'] for e in own['board'] if e['card_id']==target_card) if target_card else None
    action=next(a for a in listing['actions'] if a['type']=='use_hero_power' and a.get('target')==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    # Explicit mechanism setup: default Hunter/Shaman powers remain unadapted.
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_05',hand=('EDR_852','EDR_852','BAR_024'),
        deck=('BAR_024',)*3,mana=10,max_mana=10),PlayerSetup('HERO_02',hand=('EDR_852','EDR_852'),
        board=('CS2_182',),deck=('CS2_182',)*3,mana=10,max_mana=10)),seed=64,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'EDR_852');submit(game,'EDR_852');use(game)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        beast=match.state.entities[match.state.players[1].hand[0]]
        assert (beast.attack,beast.cost)==(registry.card('BAR_024').attack+2,0)
        submit(match,'BAR_024');submit(match);submit(match,'EDR_852');submit(match,'EDR_852')
        target=next(i for i in match.state.players[2].board if match.state.entities[i].card_id=='CS2_182')
        use(match,'CS2_182')
        assert match.state.entities[target].card_id=='ULD_208'
        assert match.state.entities[beast.id].attack==registry.card('BAR_024').attack+2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('directed-modification-snapshot.json',snapshot),
        ('directed-modification-replay.json',build_replay(game)),('directed-modification-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
