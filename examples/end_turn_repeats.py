"""Synthetic mechanism demo: scoped counts, one finite use and owner expiry."""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (AddPlayerEffect, CardDefinition, CardType, EndTurnRepeatSpec, EndTurnSpec,
    Game, LimitedTriggerSpec, PlayerEffectSpec, PlayerSetup, Registry, Scenario, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice
from hs_sim.engine.end_turns import activated_end_turns
from hs_sim.engine.replay import build_replay, replay
from examples.colossal_appendages import submit


def build_registry():
    """Explicit synthetic declarations; none of these IDs are official cards."""
    registry=Registry('end-turn-repeats-demo-v1')
    registry.register_behavior('demo.armor',lambda c:[GainArmor(c.player_id,1)])
    registry.register_behavior('demo.install',lambda c:[AddPlayerEffect(c.player_id,'demo.persistent',c.source_id)])
    registry.register_behavior('demo.choose',lambda c:[RequestChoice(c.player_id,
        (ChoiceOption('gain-armor','Gain one armor'),),source_id=c.source_id,on_select='demo.armor')])
    end=EndTurnSpec()
    definitions=(
        CardDefinition('demo.hero','Mechanism hero',CardType.HERO,health=30),
        CardDefinition('demo.plain','Draw fixture',CardType.MINION,health=5),
        CardDefinition('demo.double','All-body repeat source',CardType.MINION,health=5,
            end_turn_repeats=(EndTurnRepeatSpec(),)),
        CardDefinition('demo.chooser','Minion end body with choice',CardType.MINION,health=5,
            triggers=(TriggerSpec('turn_ended','demo.choose',end_turn=end),)),
        CardDefinition('demo.finite','Four-use end body',CardType.MINION,health=5,
            limited_triggers=(LimitedTriggerSpec('turn_ended','demo.armor',uses=4,end_turn=end),)),
        CardDefinition('demo.weapon','Weapon end body',CardType.WEAPON,durability=5,
            triggers=(TriggerSpec('turn_ended','demo.armor',end_turn=end),)),
        CardDefinition('demo.duration','Two owner-end minion policy',CardType.SPELL,
            ongoing_effect_id='demo.timed'),
        CardDefinition('demo.permanent','Permanent all-body policy',CardType.SPELL,
            on_play='demo.install'))
    for definition in definitions: registry.register_card(definition)
    registry.register_player_effect(PlayerEffectSpec('demo.timed','demo.duration',
        kind='objective',duration=2,tick_event='turn_ended',
        end_turn_repeats=(EndTurnRepeatSpec(3,'minion'),)))
    registry.register_player_effect(PlayerEffectSpec('demo.persistent','demo.permanent',
        end_turn_repeats=(EndTurnRepeatSpec(),)))
    return registry


def resolve_choices(game):
    while game.state.pending_choice is not None:
        owner=game.state.pending_choice.player_id
        port=game.for_player(owner);listing=port.legal_actions()
        action=next(a for a in listing['actions'] if a['type']=='select_choice')
        assert port.submit({'revision':listing['revision'],'action':action})['accepted']


def run():
    game=Game.from_scenario(Scenario((
        PlayerSetup('demo.hero',hand=('demo.duration','demo.permanent'),
            board=('demo.double','demo.chooser','demo.finite'),weapon_card_id='demo.weapon',
            deck=('demo.plain',)*4,max_mana=5,mana=5),
        PlayerSetup('demo.hero',deck=('demo.plain',)*4)),seed=144),build_registry())
    submit(game,'demo.duration');submit(game,'demo.permanent');submit(game)
    assert game.state.pending_choice is not None
    snapshot=game.snapshot()
    restored=Game.from_snapshot(json.loads(json.dumps(snapshot)),build_registry())
    for match in (game,restored):
        resolve_choices(match)
        for _ in range(4):
            submit(match);resolve_choices(match)
        state=match.state;rows=activated_end_turns(state,1,completed=True)
        assert len(rows)==22
        assert [b.total for b in state.end_turn_batches]==[8,0,8,0,6]
        assert [[p.repetitions for p in b.plans] for b in state.end_turn_batches]==[
            [2,3,3],[],[2,3,3],[],[2,2,2]]
        assert all(b.completed for b in state.end_turn_batches)
        assert state.entities[state.players[1].hero_id].armor==22
        assert [e.spec_id for e in state.players[1].player_effects]==['demo.persistent']
        finite=next(state.entities[i] for i in state.players[1].board if state.entities[i].card_id=='demo.finite')
        ability=next(a for a in finite.abilities if a.kind=='limited_trigger')
        assert ability.uses_remaining==1 and not ability.consumed
        receipts=[x.guard_event for x in rows if not x.capture.repeat_index and x.guard_event is not None]
        assert len(receipts)==3 and len({e.sequence for e in receipts})==3
        assert sum(e.kind=='limited_trigger_used' for e in match.events)==3
        assert sum(e.kind=='turn_ended' for e in match.events)==5
        assert sum(e.kind=='turn_started' for e in match.events)==5
        assert sum(e.kind=='card_drawn' for e in match.events)==5
        assert [x.execution_order for x in rows]==list(range(1,23))
        public=json.dumps(match.observe(1),sort_keys=True)
        for private in ('end_turn_guard_id','end_turn_ability_id','guard_event','contributors'):
            assert '"'+private+'"' not in public
    assert game.snapshot()==restored.snapshot()
    assert replay(build_replay(game),build_registry()).snapshot()==game.snapshot()
    return game,snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay',type=Path,help='Verify a replay with this explicit synthetic registry')
    args=parser.parse_args()
    if args.replay is not None:
        result=replay(json.loads(args.replay.read_text(encoding='utf-8')),build_registry())
        print('回放逐步校验通过')
        print(json.dumps({'actions':len(result.history),'state_hash':result.state_hash()}))
        return
    game,snapshot=run();out=Path(__file__).resolve().parents[1]/'outputs'
    for name,value in (('end-turn-repeats-snapshot.json',snapshot),
                       ('end-turn-repeats-replay.json',build_replay(game)),
                       ('end-turn-repeats-view.json',game.observe(1))):
        (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'actions':len(game.history),'events':len(game.events),
        'end_turn_batches':len(game.state.end_turn_batches),
        'end_turn_activations':len(game.state.end_turn_history),
        'finite_consumptions':sum(e.kind=='limited_trigger_used' for e in game.events),
        'state_hash':game.state_hash(),'restored_and_replayed':True}))


if __name__=='__main__': main()
