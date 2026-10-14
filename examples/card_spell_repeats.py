"""Synthetic mechanism scenario: card attachments, two choices and a terminal replay.

The named demo registry is separate from the representative card package. It
does not pretend that a real source card or a formal discovery pool is adapted.
"""
import json
from pathlib import Path
from hs_sim.engine import (Registry,CardDefinition,CardType,Game,Scenario,PlayerSetup,
    GrantCardSpellRepeat,CardReference,DamageKind)
from hs_sim.engine.effects import RequestChoice,ChoiceOption,Damage
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def build_registry():
    r=Registry('card-spell-repeat-demo-v1')
    r.register_card(CardDefinition('demo.hero','机制演示英雄',CardType.HERO,health=30))
    r.register_card(CardDefinition('demo.filler','占位牌',CardType.MINION,cost=1,attack=1,health=1))
    def grant(c):
        cards=[c.state.entities[i] for i in c.state.players[c.player_id].hand]
        return [GrantCardSpellRepeat(CardReference.capture(next(e for e in cards if e.card_id==cid)),
            source_id=c.source_id) for cid in ('demo.choice','demo.fire')]
    r.register_behavior('demo.grant',grant)
    r.register_behavior('demo.fire',lambda c:[Damage(c.state.players[3-c.player_id].hero_id,6,c.source_id,DamageKind.SPELL)])
    r.register_behavior('demo.choice',lambda c:[RequestChoice(c.player_id,
        (ChoiceOption('hit','造成3点伤害',(Damage(c.state.players[3-c.player_id].hero_id,3,c.source_id,DamageKind.SPELL),)),),
        source_id=c.source_id)])
    r.register_card(CardDefinition('demo.grant','测试授予者',CardType.MINION,attack=1,health=4,battlecry='demo.grant'))
    r.register_card(CardDefinition('demo.fire','测试伤害法术',CardType.SPELL,cost=4,on_play='demo.fire'))
    r.register_card(CardDefinition('demo.choice','测试选择法术',CardType.SPELL,cost=2,on_play='demo.choice'))
    return r


def run():
    r=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('demo.hero',hand=('demo.grant','demo.choice')+('demo.fire',)*3,
        deck=('demo.filler',)*4,mana=10,max_mana=10),PlayerSetup('demo.hero',deck=('demo.filler',)*4)),seed=92),r)
    submit(game,'play_card','demo.grant');submit(game,'play_card','demo.choice')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        assert match.state.pending_choice is not None
        submit(match,'select_choice');assert match.state.pending_choice is not None
        submit(match,'select_choice')
        assert match.state.entities[match.state.players[2].hero_id].health==24
        submit(match,'end_turn');submit(match,'end_turn')
        submit(match,'play_card','demo.fire')
        assert match.state.entities[match.state.players[2].hero_id].health==12
        submit(match,'play_card','demo.fire')
        assert match.state.entities[match.state.players[2].hero_id].health==6
        submit(match,'end_turn');submit(match,'end_turn')
        submit(match,'play_card','demo.fire')
        assert match.state.status=='finished' and match.state.winner==1
        assert len(match.state.cast_history)==6 and len(match.state.spell_repeats)==2
        assert not match.state.spell_policy_receipts
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('card-spell-repeat-snapshot.json',snapshot),('card-spell-repeat-replay.json',build_replay(game)),
                       ('card-spell-repeat-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),casts=len(game.state.cast_history),
        captured_card_plays=sum(bool(p.card_spell_repeats) for p in game.state.play_history),
        winner=game.state.winner,registry=game.registry.version,restored_and_replayed=True)))


if __name__=='__main__':main()
