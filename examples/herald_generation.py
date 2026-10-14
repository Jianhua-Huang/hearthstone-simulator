"""Real DK Heralds: generated minion ranks, temporary Health payment, save/replay."""
import json
from pathlib import Path
from hs_sim.engine import CardClass, CardDefinition, CardMetadata, CardType, Game, PlayerSetup, Scenario
from hs_sim.engine.costs import quote_cost
from hs_sim.engine.model import PaymentType
from hs_sim.engine.pools import GenerationContext
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def run():
    registry=build_registry()
    registry.register_card(CardDefinition('fixture.dk','死亡骑士测试英雄',CardType.HERO,health=30,
        metadata=CardMetadata(False,(CardClass.DEATH_KNIGHT,),None)))
    game=Game.from_scenario(Scenario((PlayerSetup('fixture.dk',hand=('CATA_780',)*3,
        deck=('CS2_182',)*10,max_mana=10,mana=10),PlayerSetup('HERO_01',deck=('CS2_182',)*10,
        max_mana=10,mana=10)),seed=72,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'CATA_780');submit(game,'CATA_780')
    old=[i for i in game.state.players[1].hand if game.state.entities[i].card_id!='CATA_780']
    assert all(quote_cost(game.state,registry,game.state.entities[i]).payment==PaymentType.HEALTH for i in old)
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match);submit(match)
        assert all(quote_cost(match.state,registry,match.state.entities[i]).payment==PaymentType.MANA for i in old)
        before=set(match.state.players[1].hand);submit(match,'CATA_780')
        new=next(iter(set(match.state.players[1].hand)-before));card=match.state.entities[new]
        assert quote_cost(match.state,registry,card).amount==4
        mana=match.state.players[1].mana
        submit(match,card.card_id)
        assert match.state.players[1].mana==mana
        assert match.state.entities[match.state.players[1].hero_id].health==26
        assert len(match.state.herald_history)==3
    assert restored.snapshot()==game.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs';out.mkdir(exist_ok=True)
    for name,data in (('herald-generation-snapshot.json',snapshot),('herald-generation-replay.json',build_replay(game)),
                      ('herald-generation-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__':main()
