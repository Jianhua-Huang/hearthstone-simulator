"""Synthetic discovery grant, identical unmodified spell, restore and terminal replay."""
import json
from pathlib import Path
from hs_sim.engine import (Registry,CardDefinition,CardType,CardMetadata,CardClass,
    Game,Scenario,PlayerSetup,GenerationContext,DiscoverFromPool,CardSpellRepeatGrant,DamageKind)
from hs_sim.engine.pools import PoolCard,PoolDefinition,PoolMember
from hs_sim.engine.effects import Damage
from hs_sim.engine.replay import build_replay,replay
from examples.battlecry_activations import submit


def build_registry():
    r=Registry('creation-repeat-demo-v1')
    r.register_card(CardDefinition('demo.hero','机制演示英雄',CardType.HERO,health=30))
    r.register_card(CardDefinition('demo.filler','占位牌',CardType.MINION,cost=1,attack=1,health=1))
    r.register_behavior('demo.fire',lambda c:[Damage(c.state.players[3-c.player_id].hero_id,6,c.source_id,DamageKind.SPELL)])
    r.register_card(CardDefinition('demo.fire','测试伤害法术',CardType.SPELL,cost=4,on_play='demo.fire',
        metadata=CardMetadata(False,(CardClass.MAGE,),None)))
    r.register_pool_card(PoolCard.from_definition(r.card('demo.fire')))
    r.register_pool(PoolDefinition('demo.spells','v1','creation-demo','experimental',(PoolMember('demo.fire'),)))
    r.register_behavior('demo.discover',lambda c:[DiscoverFromPool(c.player_id,'demo.spells',source_id=c.source_id,
        discoveries=2,delivery='after_all',spell_repeat=CardSpellRepeatGrant())])
    r.register_card(CardDefinition('demo.discover','测试发现者',CardType.MINION,attack=1,health=4,battlecry='demo.discover'))
    return r


def run():
    game=Game.from_scenario(Scenario((PlayerSetup('demo.hero',hand=('demo.discover','demo.fire'),
        deck=('demo.filler',)*4,mana=10,max_mana=10),PlayerSetup('demo.hero',deck=('demo.filler',)*4)),
        seed=93,generation_context=GenerationContext('creation-demo','experimental')),build_registry())
    submit(game,'play_card','demo.discover');submit(game,'select_choice')
    snapshot=game.snapshot();restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        assert len(match.state.players[1].hand)==1
        submit(match,'select_choice')
        submit(match,'play_card','demo.fire')
        assert match.state.entities[match.state.players[2].hero_id].health==24
        assert not match.state.play_history[-1].card_spell_repeats
        submit(match,'play_card','demo.fire')
        assert match.state.entities[match.state.players[2].hero_id].health==12
        submit(match,'end_turn');submit(match,'end_turn');submit(match,'play_card','demo.fire')
        assert match.state.status=='finished' and match.state.winner==1
        assert len(match.state.cast_history)==5 and len(match.state.spell_repeats)==2
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('creation-repeat-snapshot.json',snapshot),('creation-repeat-replay.json',build_replay(game)),
                       ('creation-repeat-view.json',game.for_player(1).observe())):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(actions=len(game.history),events=len(game.events),state_hash=game.state_hash(),
        hand_plays=len(game.state.play_history),casts=len(game.state.cast_history),
        captured_card_plays=sum(bool(p.card_spell_repeats) for p in game.state.play_history),
        winner=game.state.winner,registry=game.registry.version,restored_and_replayed=True)))


if __name__=='__main__':main()
