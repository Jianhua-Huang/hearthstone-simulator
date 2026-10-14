"""Onyxia's generated Health costs and own-turn protection through player DTOs."""
import json
from pathlib import Path

from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def fireball(game, target_player):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
    target=next(p for p in listing['observation']['players'] if p['id']==target_player)['hero']['ref']
    card=next(e['ref'] for e in own['hand'] if e['card_id']=='CS2_029')
    action=next(a for a in listing['actions'] if a['type']=='play_card' and a['card']==card and a.get('target')==target)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((
        PlayerSetup('HERO_01',hand=('CATA_155','CS2_029'),deck=('CS2_182',)*12,max_mana=10,mana=10),
        PlayerSetup('HERO_08',hand=('CS2_029',),deck=('CS2_182',)*12,max_mana=10,mana=10)),seed=173,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'CATA_155')
    generated=[game.state.entities[i].card_id for i in game.state.players[1].hand if game.state.entities[i].card_id!='CS2_029']
    assert generated==['FP1_007','FP1_007']
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'FP1_007');submit(match,'FP1_007')
        hero=match.state.entities[match.state.players[1].hero_id]
        assert (hero.health,hero.max_health,match.state.players[1].mana)==(34,34,1)
        submit(match);submit(match)
        fireball(match,1)
        hero=match.state.entities[match.state.players[1].hero_id]
        assert (hero.health,hero.max_health)==(40,40)
        submit(match);fireball(match,1)
        hero=match.state.entities[match.state.players[1].hero_id]
        assert (hero.health,hero.max_health)==(34,40)
        assert len([e for e in match.events if e.kind=='health_loss_replaced'])==3
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();output=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('onyxia-snapshot.json',snapshot),('onyxia-replay.json',build_replay(game)),('onyxia-view.json',game.observe(1))):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
