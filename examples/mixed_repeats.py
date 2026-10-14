"""Necessary real Deios carrier using four independent public repeat families.

The scenario is an experimental cross-class mechanism fixture, not a legal
constructed deck. It uses only the representative registry and its existing
generation pool; the default representative replay CLI can restore it.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import EndTurn, Game, GenerationContext, PlayCard, PlayerSetup, Scenario, SelectChoice, UseHeroPower
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry


FAMILIES = ('battlecry_repeat', 'deathrattle_repeat', 'hero_power_repeat', 'end_turn_repeat')


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', board=('BOT_107',), weapon_card_id='CATA_472',
            hand=('TIME_064', 'LOE_029', 'CS2_106', 'EX1_332'),
            deck=('CS2_182',) * 10, mana=10, max_mana=10, hero_power_card_id='HERO_08bp'),
        PlayerSetup('HERO_01', deck=('CS2_182',) * 10, mana=10, max_mana=10)),
        seed=148, name='representative-four-family-mixed-repeats',
        generation_context=GenerationContext('local-2026-09-23', 'experimental')), build_registry())

    def play(card_id, target_id=None):
        owner = game.state.active_player
        entity_id = next(i for i in game.state.players[owner].hand
            if game.state.entities[i].card_id == card_id)
        game.apply(PlayCard(owner, entity_id, target_id))
        return entity_id

    source_id = play('TIME_064')
    policies = {family: active_abilities(game.state.entities[source_id], family)[0].id for family in FAMILIES}
    assert len(set(policies.values())) == 4
    assert not game.state.battlecry_batches and not game.state.deathrattle_batches
    play('LOE_029')
    waiting_hashes = []
    while game.state.pending_choice is not None:
        assert len(waiting_hashes) < 4
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, build_registry())
        assert restored.snapshot() == game.clone().snapshot() == snapshot
        assert replay(build_replay(game), build_registry()).snapshot() == snapshot
        waiting_hashes.append(game.state_hash())
        choice = game.state.pending_choice
        action = SelectChoice(choice.player_id, choice.id, (choice.options[0].id,))
        game.apply(action); restored.apply(action)
        assert restored.snapshot() == game.snapshot()
    assert len(waiting_hashes) == 2
    battlecry = game.state.battlecry_batches[0]
    assert battlecry.plan.repetitions == 2 and battlecry.plan.contributors == (policies['battlecry_repeat'],)
    assert [x.repeat_index for x in game.state.battlecry_history] == [1, 2]

    game.apply(EndTurn(1))
    assert game.state.entities[source_id].health == 6
    game.apply(EndTurn(2))
    play('CS2_106')  # Replacing the real Maul creates two actual Deathrattles.
    assert game.state.entities[source_id].health == 2
    outer = game.state.deathrattle_batches[0]
    assert outer.trigger_count == 1 and outer.total == outer.plan.repetitions == 2
    assert [s.ability.id for s in outer.plan.contributors] == [policies['deathrattle_repeat']]
    assert [x.capture.repeat_index for x in game.state.deathrattle_history] == [1, 2]
    producers = [b for b in game.state.end_turn_batches if b.activation.selection is not None]
    assert len(producers) == 2 and all(b.total == 2 for b in producers)
    assert all(len(b.activation.selection.candidates) == 1 and
        b.activation.selection.selected.card_id == 'BOT_107' for b in producers)

    enemy = game.state.players[2].hero_id
    mana_before = game.state.players[1].mana
    game.apply(UseHeroPower(1, game.state.players[1].hero_power_id, enemy))
    power = game.state.hero_power_history[0]
    assert power.repeat_plan.repetitions == 2 and game.state.players[1].mana == mana_before - 2
    assert len(game.state.hero_power_payload_history) == 2
    assert [s.ability.id for s in power.repeat_plan.contributors] == [policies['hero_power_repeat']]

    play('EX1_332', source_id)
    assert not any(active_abilities(game.state.entities[source_id], family) for family in FAMILIES)
    game.apply(EndTurn(1))
    assert game.state.entities[source_id].health == 1
    assert [b.total for b in game.state.end_turn_batches] == [2, 0, 2, 2, 1]
    assert all(b.completed for b in game.state.end_turn_batches)
    assert [b.plans[0].repetitions for b in game.state.end_turn_batches if b.plans] == [2, 2, 2, 1]
    assert all([s.ability.id for s in b.plans[0].contributors] == [policies['end_turn_repeat']]
        for b in game.state.end_turn_batches if b.plans and b.plans[0].repetitions == 2)
    snapshot = game.snapshot()
    assert Game.from_snapshot(snapshot, build_registry()).snapshot() == snapshot
    assert replay(build_replay(game), build_registry()).snapshot() == snapshot
    view = json.dumps(game.observe(1), sort_keys=True)
    for private in ('battlecry_acceptance', 'contributors', 'consumable_ids', 'rng_before', 'next_deathrattle_id'):
        assert '"' + private + '"' not in view
    result = dict(raw_card='TIME_064', registry=game.registry.version,
        schema=snapshot['schema_version'], actions=len(game.history), events=len(game.events),
        choices=len(waiting_hashes), waiting_hashes=waiting_hashes,
        battlecry_positions=len(game.state.battlecry_history),
        deathrattle_positions=len(game.state.deathrattle_history),
        hero_power_roots=len(game.state.hero_power_history),
        hero_power_positions=len(game.state.hero_power_payload_history),
        end_turn_batches=len(game.state.end_turn_batches),
        end_turn_positions=len(game.state.end_turn_history),
        end_turn_totals=[b.total for b in game.state.end_turn_batches],
        independent_random_producer_roots=len(producers),
        shared_source_silenced=game.state.entities[source_id].silenced,
        shared_source_health=game.state.entities[source_id].health,
        restored_and_replayed=True, state_hash=game.state_hash())
    return game, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    if args.replay is not None:
        game = replay(json.loads(args.replay.read_text(encoding='utf-8')), build_registry())
        print(json.dumps(dict(replayed=True, actions=len(game.history), state_hash=game.state_hash())))
        return
    game, result = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    for suffix, value in (('summary', result), ('snapshot', game.snapshot()),
            ('replay', build_replay(game)), ('view', game.observe(1))):
        (output / f'mixed-repeats-{suffix}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
