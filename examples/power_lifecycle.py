"""Synthetic installation/replacement policies through player commands and recovery."""
import json
from pathlib import Path
from hs_sim.engine import (AddHeroPower, CardDefinition, CardType, CostSpec, Game,
    PaymentType, PlayerSetup, Registry, RemoveHeroPower, Scenario, TriggerHeroPower, hero_power_references)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RefreshHeroPower, ReplaceHeroPower, RequestChoice
from hs_sim.engine.replay import build_replay,replay


def build_registry():
    registry=Registry('example-power-lifecycle-v1')
    registry.register_card(CardDefinition('hero','实验英雄',CardType.HERO,health=30))
    for card,amount in (('primary',1),('extra',2),('replacement',4)):
        registry.register_behavior(card,lambda c,n=amount:[GainArmor(c.player_id,n)])
        registry.register_card(CardDefinition(card,card,CardType.HERO_POWER,cost=2,on_use=card))
    registry.register_behavior('install',lambda c:[AddHeroPower(1,'extra',c.source_id,
        CostSpec(payment=PaymentType.CORPSES,card_types=(CardType.HERO_POWER,)))])
    def choose_replacement(c):
        power=hero_power_references(c.state,1,scope='additional')[0]
        return [RequestChoice(1,(ChoiceOption('replace','替换额外技能',
            (ReplaceHeroPower(1,'replacement',power=power),)),),source_id=c.source_id),
            TriggerHeroPower(1,c.source_id,power=power)]
    registry.register_behavior('choose',choose_replacement)
    registry.register_behavior('refresh',lambda c:[RefreshHeroPower(1,p)
        for p in hero_power_references(c.state,1)])
    registry.register_behavior('trigger',lambda c:[TriggerHeroPower(1,c.source_id,
        power=hero_power_references(c.state,1,scope='additional')[0])])
    registry.register_behavior('remove',lambda c:[RemoveHeroPower(1,
        hero_power_references(c.state,1,scope='additional')[0],c.source_id)])
    for card in ('install','choose','refresh','trigger','remove'):
        registry.register_card(CardDefinition(card,card,CardType.SPELL,on_play=card))
    return registry


def submit(game,kind,card=None):
    port=game.for_player(1); listing=port.legal_actions(); own=listing['observation']['players'][0]
    candidates=listing['actions']
    if kind=='play_card':
        ref=next(e['ref'] for e in own['hand'] if e['card_id']==card)
        action=next(a for a in candidates if a['type']==kind and a['card']==ref)
    elif kind=='use_hero_power':
        power=own['hero_power'] if card=='primary' else own['additional_hero_powers'][0]
        action=next(a for a in candidates if a['type']==kind and a['power']==power['ref'])
    else:action=next(a for a in candidates if a['type']==kind)
    assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    registry=build_registry()
    game=Game.from_scenario(Scenario((PlayerSetup('hero',hero_power_card_id='primary',
        hand=('install','choose','refresh','trigger','remove'),mana=10,max_mana=10,corpses=4),
        PlayerSetup('hero')),seed=68),registry)
    submit(game,'play_card','install');submit(game,'use_hero_power','extra')
    submit(game,'play_card','choose');snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),registry)
    for match in (game,restored):
        submit(match,'select_choice')
        # The queued trigger has a stale reference and cannot activate the replacement.
        assert len(match.state.hero_power_history)==1
        submit(match,'use_hero_power','extra');submit(match,'use_hero_power','primary')
        submit(match,'play_card','refresh');submit(match,'play_card','trigger')
        submit(match,'use_hero_power','extra');submit(match,'play_card','remove')
        state=match.state
        assert state.entities[state.players[1].hero_id].armor==15
        assert state.players[1].mana==4 and state.players[1].hero_power_uses_this_turn==4
        assert not state.players[1].additional_hero_power_ids
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),registry).snapshot()==game.snapshot()
    return game,snapshot


def main():
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('power-lifecycle-snapshot.json',snapshot),('power-lifecycle-replay.json',build_replay(game)),
                       ('power-lifecycle-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),'state_hash':game.state_hash(),
        'restored_and_replayed':True}))


if __name__=='__main__':main()
