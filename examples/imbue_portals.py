"""Generate portals, grow them in the deck, then draw through player ports."""
import json
from pathlib import Path
from hs_sim.engine import Game,PlayerSetup,Scenario,GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay,replay
from examples.colossal_appendages import submit
from examples.imbue_directed_modification import use


def run():
    registry=build_registry()
    # Mechanism scenario: transferred draw spell and explicit experimental pool.
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_04',
        hand=('EDR_852','EDR_852','BT_491'),deck=('CS2_182',),mana=10,max_mana=10),
        PlayerSetup('HERO_08',deck=('CS2_182',)*3,mana=10,max_mana=10)),seed=65,
        generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'EDR_852');use(game)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'EDR_852');submit(match,'BT_491')
        player=match.state.players[1]
        assert sum(match.state.entities[i].card_id=='NEW1_023' for i in player.board)==2
        assert [match.state.entities[i].card_id for i in player.hand]==['CS2_182']
        assert not player.deck and player.fatigue==1
        assert sum(c.card_id=='EDR_445pt3' and c.origin=='draw' for c in match.state.cast_history)==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('imbue-portals-snapshot.json',snapshot),('imbue-portals-replay.json',build_replay(game)),
        ('imbue-portals-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
