"""Public carrier selection with a necessary real Inspiring Maul producer.

This synthetic scenario is not a legal constructed deck. Its own factory is
required for restoration and for the module's explicit replay CLI.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardDefinition, CardType,
    EndTurnProducerRequest, EndTurnSelector, EndTurnSpec, Game, PlayerSetup,
    Scenario, TriggerRandomEndTurnEffects, TriggerSpec)
from hs_sim.engine.effects import (ChoiceOption, Damage, GainArmor, RandomDamage,
    RequestChoice, Silence)
from hs_sim.engine.actions import PlayCard, SelectChoice
from hs_sim.engine.model import Zone
from hs_sim.engine.representative import build_registry as representative_registry
from hs_sim.engine.end_turn_producers import end_turn_carriers
from hs_sim.engine.replay import build_replay, replay


BODY = 'demo.producer_choice_body'
OTHER = 'demo.producer_false_body'
CALLER = 'demo.random_end_turn_caller'


def body(context):
    """A later random effect advances RNG without changing the saved draw."""
    enemy = context.state.players[3 - context.player_id].hero_id
    return [RequestChoice(context.player_id,
        (ChoiceOption('continue', 'Run accepted body and keep its original selection',
            (GainArmor(context.player_id, context.source.damage + 1),
             Damage(context.source_id, 1, context.source_id),
             RandomDamage((enemy,), 1, source_id=context.source_id),
             *tuple(Silence(i) for i in context.state.players[context.player_id].board
                    if context.state.entities[i].card_id == 'ICC_901'))),),
        source_id=context.source_id, prompt='Synthetic end-turn body: retain one carrier draw')]


def build_registry():
    registry = representative_registry()
    registry.register_trigger_condition('demo.producer_never', lambda c: False)
    registry.register_behavior('demo.producer_choice', body)
    registry.register_behavior('demo.producer_false', lambda c: [GainArmor(c.player_id, 99)])
    registry.register_behavior('demo.random_end_turn', lambda c: [TriggerRandomEndTurnEffects(
        c.player_id, EndTurnProducerRequest(EndTurnSelector('owner', (c.player_id,), ('minion',))), c.source_id)])
    registry.register_card(CardDefinition(BODY, 'Synthetic producer choice body', CardType.MINION,
        health=30, triggers=(TriggerSpec('turn_ended', 'demo.producer_choice', EndTurnSpec()),)))
    registry.register_card(CardDefinition(OTHER, 'Synthetic structurally present false body', CardType.MINION,
        health=30, triggers=(TriggerSpec('turn_ended', 'demo.producer_false',
            EndTurnSpec('controller', 'demo.producer_never')),)))
    registry.register_card(CardDefinition(CALLER, 'Synthetic random end-turn caller', CardType.SPELL,
        cost=0, on_play='demo.random_end_turn'))
    return registry


def run():
    registry = build_registry()
    game = Game.from_scenario(Scenario((
        PlayerSetup('test.hero', board=(BODY, OTHER, 'ICC_901'),
            weapon_card_id='CATA_472', hand=('AV_400', 'CATA_480', 'CS2_106', CALLER),
            deck=('CS2_182',) * 10, mana=10, max_mana=10),
        PlayerSetup('test.hero', deck=('CS2_182',) * 10, mana=10, max_mana=10)),
        seed=147, name='synthetic-end-turn-producer-selection'), registry)
    selector = EndTurnSelector('owner', (1,), ('minion',))
    assert [c.card_id for c in end_turn_carriers(game.state, registry, selector)] == [BODY, OTHER]

    def play(card):
        entity = next(i for i in game.state.players[1].hand if game.state.entities[i].card_id == card)
        game.apply(PlayCard(1, entity))

    def resolve_choices():
        waits = 0
        while game.state.pending_choice is not None:
            assert waits < 8
            snap = json.loads(json.dumps(game.snapshot()))
            restored = Game.from_snapshot(snap, build_registry())
            assert restored.snapshot() == snap
            witnesses = tuple(b.activation.selection for b in game.state.end_turn_batches)
            choice = game.state.pending_choice
            action = SelectChoice(choice.player_id, choice.id, ('continue',))
            game.apply(action)
            restored.apply(action)
            assert restored.snapshot() == game.snapshot()
            assert game.snapshot()['rng_state'] != snap['rng_state']
            assert tuple(b.activation.selection for b in game.state.end_turn_batches[:len(witnesses)]) == witnesses
            waits += 1
        return waits
    play('AV_400')
    play('CATA_480')
    play('CS2_106')  # Destroy the equipped real Maul; outer Deathrattle repeats select separately.
    waits = resolve_choices()
    play(CALLER)
    waits += resolve_choices()
    restored = Game.from_snapshot(game.snapshot(), build_registry())
    replayed = replay(build_replay(game), build_registry())
    assert restored.snapshot() == replayed.snapshot() == game.snapshot()
    selections = [b.activation.selection for b in game.state.end_turn_batches]
    assert len(selections) == 3 and all(s is not None for s in selections)
    assert all(len(s.candidates) == 2 for s in selections)
    # The false body stays structurally eligible; conditions are checked after selection.
    assert [s.selected.card_id for s in selections] == [BODY, OTHER, BODY]
    assert all([c.card_id for c in s.candidates] == [BODY, OTHER] for s in selections)
    assert all(s.rng_before != s.rng_after for s in selections)
    assert selections[1].rng_before != selections[0].rng_after  # Accepted body made later draws.
    assert game.snapshot()['rng_state'] != json.loads(json.dumps(selections[-1].rng_after))
    groups = game.state.end_turn_batches
    assert [b.activation.issuer_card_id for b in groups] == ['CATA_472', 'CATA_472', CALLER]
    assert [b.total for b in groups] == [2, 0, 2] and all(b.completed for b in groups)
    assert groups[1].subjects == groups[1].plans == ()  # Chosen false condition, not an empty pool.
    assert groups[0].plans[0].repetitions == groups[2].plans[0].repetitions == 2
    assert {s.card_id for s in groups[0].plans[0].contributors} == {'ICC_901', 'CATA_480'}
    assert {s.card_id for s in groups[2].plans[0].contributors} == {'CATA_480'}
    icc = next(e for e in game.state.entities.values() if e.card_id == 'ICC_901')
    assert icc.silenced and not icc.abilities
    rows = game.state.end_turn_history
    assert len(rows) == waits == 4 and all(r.completed for r in rows)
    assert [r.capture.repeat_index for r in rows] == [0, 1, 0, 1]
    assert [e.amount for e in game.events if e.kind == 'armor_gained'] == [1, 2, 3, 4]
    assert sum(e.kind == 'random_choice' for e in game.events) == waits
    # Snowfall repeats the Maul's one natural Deathrattle twice; each invokes a fresh producer draw.
    assert len(game.state.deathrattle_batches) == 1
    outer = game.state.deathrattle_batches[0]
    assert outer.trigger_count == 1 and outer.total == outer.plan.repetitions == 2
    assert [s.instance.source_card_id for s in outer.plan.contributors] == ['AV_400']
    assert [r.capture.repeat_index for r in game.state.deathrattle_history] == [1, 2]
    assert all(r.completed and r.capture.card_id == 'CATA_472' and r.capture.origin == 'death'
               for r in game.state.deathrattle_history)
    assert [d.card_id for d in game.state.death_history] == ['CATA_472']
    maul = next(e for e in game.state.entities.values() if e.card_id == 'CATA_472')
    assert maul.zone == Zone.GRAVEYARD
    assert game.state.entities[game.state.players[1].weapon_id].card_id == 'CS2_106'
    clocks = [e.remaining_turns for e in game.state.players[1].player_effects]
    assert clocks == [3, 3]
    assert game.state.turn == game.state.active_player == 1
    assert not any(e.kind in ('turn_ended', 'turn_started', 'card_drawn', 'player_effect_ticked')
                   for e in game.events)
    assert all(len(p.deck) == 10 for p in game.state.players.values())
    result = dict(actions=len(game.history), events=len(game.events),
        batches=len(selections), positions=len(game.state.end_turn_history), choices=waits,
        selected=[s.selected.card_id for s in selections],
        candidate_counts=[len(s.candidates) for s in selections],
        deathrattle_positions=outer.total, player_effect_clocks=clocks,
        restored_and_replayed=True,
        raw_card='CATA_472', schema=game.snapshot()['schema_version'], hash=game.state_hash())
    return game, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay')
    args = parser.parse_args()
    if args.replay:
        game = replay(json.loads(Path(args.replay).read_text(encoding='utf-8')), build_registry())
        print('回放逐步校验通过', game.state_hash())
        return
    game, result = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    for suffix, value in (('summary', result), ('snapshot', game.snapshot()), ('replay', build_replay(game))):
        (output / f'end-turn-producers-{suffix}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
