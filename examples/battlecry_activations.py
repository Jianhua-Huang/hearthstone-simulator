"""Existing minion, weapon and hero Battlecries, player commands and restored discovery."""
import json
from pathlib import Path
from hs_sim.engine import Game, GenerationContext, PlayerSetup, Scenario
from hs_sim.engine.representative import build_registry
from hs_sim.engine.replay import build_replay, replay


def submit(game,kind,card=None):
    port=game.for_player(game.state.active_player);listing=port.legal_actions()
    actions=[a for a in listing['actions'] if a['type']==kind]
    if card is not None:
        own=next(p for p in listing['observation']['players'] if p['id']==game.state.active_player)
        ref=next(c['ref'] for c in own['hand'] if c['card_id']==card)
        actions=[a for a in actions if a['card']==ref]
    assert actions,(kind,card)
    result=port.submit({'revision':listing['revision'],'action':actions[0]})
    assert result['accepted'],result


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('HERO_01',hand=('LOE_029','CATA_580','SC_400'),
        deck=('CS2_182',)*6,mana=10,max_mana=10),PlayerSetup('HERO_08',deck=('CS2_182',)*6)),
        seed=73,generation_context=GenerationContext('local-2026-09-23','experimental')),registry)
    submit(game,'play_card','LOE_029')
    assert game.state.pending_choice is not None and not game.state.battlecry_history[0].completed
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice')
        submit(match,'play_card','CATA_580')
        submit(match,'end_turn');submit(match,'end_turn')
        submit(match,'play_card','SC_400')
        assert [b.card_id for b in match.state.battlecry_history]==['LOE_029','CATA_580','SC_400']
        assert all(b.completed and not b.interrupted for b in match.state.battlecry_history)
        assert len(match.state.play_history)==3 and match.state.players[1].mana==3
        assert match.state.entities[match.state.players[1].hero_id].card_id=='SC_400'
        assert match.state.cast_history==[]
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('battlecry-snapshot.json',snapshot),('battlecry-replay.json',build_replay(game)),
                       ('battlecry-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
                     'battlecries':len(game.state.battlecry_history),'restored_and_replayed':True}))


if __name__=='__main__':main()
