"""B2-05 default-mechanics EndTurn source-condition integration example.

Synthetic source conditions through two effect groups and a natural group.
Internal verification does not certify official CN timing or pool coverage.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurnRequest, EndTurnSelector, EndTurnSpec, Game, PlayerSetup, Registry,
    Scenario, TriggerEndTurnEffects, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Transform
from hs_sim.engine.end_turns import FinishEndTurnBatch
from hs_sim.engine.model import (EndTurnRepeatMatchSpec, EndTurnRepeatSpec,
    RepeatSourceEligibility)
from hs_sim.engine.replay import build_replay, replay


HIDDEN = 'native.private.enemy'


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def build_registry():
    registry = Registry('end-turn-matching-example-v1')
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO,
        health=30, metadata=metadata()))
    for name, tribes in (('plain', ()), ('beast', ('beast',)), (HIDDEN, ())):
        registry.register_card(CardDefinition(name, name, CardType.MINION,
            health=12, metadata=metadata(tribes)))
    condition = RepeatSourceEligibility('repeat.witness.controlled',
        tribes_any=('beast',), exclude_carrier=True)
    for name, count in (('conditional.two', 2), ('conditional.three', 3)):
        registry.register_card(CardDefinition(name, name, CardType.MINION,
            health=12, metadata=metadata(), end_turn_repeats=(EndTurnRepeatSpec(
                count, match=EndTurnRepeatMatchSpec(condition)),)))

    def body(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.end_turn.batch_id == 1 and context.end_turn.repeat_index == 0:
            witness = next(i for i in context.state.players[context.player_id].board
                if context.state.entities[i].card_id == 'beast')
            effects.insert(0, Transform(witness, 'plain'))
        return [RequestChoice(context.player_id,
            (ChoiceOption('resolve', 'Resolve', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior('native.end_turn.body', body)
    registry.register_card(CardDefinition('body', 'End-turn choice body',
        CardType.MINION, health=12, metadata=metadata(), triggers=(TriggerSpec(
            'turn_ended', 'native.end_turn.body', end_turn=EndTurnSpec()),)))

    def trigger(context):
        targets = tuple(i for i in context.state.players[context.player_id].board
            if context.state.entities[i].card_id == 'body')
        request = EndTurnRequest(EndTurnSelector('selected',
            (context.player_id,), ('minion',), targets), 'end_turn.effect')
        return [TriggerEndTurnEffects(context.player_id, request, context.source_id)]

    registry.register_behavior('native.trigger.end_turn', trigger)
    registry.register_card(CardDefinition('trigger', 'Trigger one selected body',
        CardType.SPELL, cost=1, on_play='native.trigger.end_turn', metadata=metadata()))
    return registry


def private_information_absent(game):
    forbidden = ('end_turn_batches', 'end_turn_history', 'repeat_plan',
        'contributors', 'resolution_frame', 'source_eligibility',
        'profile_id', 'rng_state')
    for player_id in (1, 2):
        port = game.for_player(player_id)
        view, actions, events = port.observe(), port.legal_actions(), port.events()
        encoded = json.dumps((view, actions, events), sort_keys=True)
        assert all('"' + name + '"' not in encoded for name in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded
        before = game.snapshot()
        view['observation']['players'][0]['hero']['armor'] = 999
        assert game.snapshot() == before


def submit(game, kind, card_id=None):
    port = game.for_player(1)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    actions = [a for a in listing['actions'] if a['type'] == kind]
    if card_id is not None:
        own = next(p for p in listing['observation']['players'] if p['id'] == 1)
        reference = next(c['ref'] for c in own['hand'] if c['card_id'] == card_id)
        actions = [a for a in actions if a['card'] == reference]
    assert actions, (kind, card_id)
    result = port.submit({'revision': listing['revision'], 'action': actions[0]})
    assert result['accepted'], result


def clocks(game):
    return tuple(sum(e.kind == kind for e in game.events)
        for kind in ('turn_ended', 'turn_started', 'card_drawn', 'player_effect_ticked'))


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero', hand=('trigger', 'trigger'),
            board=('conditional.two', 'conditional.three', 'beast', 'body'),
            deck=('plain',) * 4, mana=10, max_mana=10),
        PlayerSetup('hero', hand=(HIDDEN,), deck=(HIDDEN,) * 4)), seed=115),
        build_registry())
    initial_rng = game.snapshot()['rng_state']
    waiting, positions = [], []

    def portable():
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, build_registry())
        assert restored.snapshot() == snapshot
        assert restored.clone().snapshot() == snapshot
        assert replay(build_replay(restored), build_registry()).snapshot() == snapshot
        private_information_absent(game)

    def finish_waiting(expected):
        observed = 0
        while game.state.pending_choice is not None:
            portable()
            waiting.append(game.snapshot())
            row = next(r for r in reversed(game.state.end_turn_history)
                if r.execution_order is not None and not r.completed)
            group = game.state.end_turn_batches[row.capture.batch_id - 1]
            plan = row.capture.plan
            positions.append(dict(batch_id=group.id, origin=group.activation.kind,
                repeat_index=row.capture.repeat_index, repetitions=plan.repetitions,
                contributors=len(plan.contributors)))
            assert game._frame is not None
            proofs = [w for w in (*game._frame.prefix, *game._frame.continuation)
                if type(w) is FinishEndTurnBatch]
            assert len(proofs) == 1
            proof = proofs[0]
            assert proof.batch == group
            assert len(proof.context.state.end_turn_batches) == group.id - 1
            submit(game, 'select_choice')
            observed += 1
        assert observed == expected
        portable()

    submit(game, 'play_card', 'trigger')
    finish_waiting(3)
    assert clocks(game) == (0, 0, 0, 0)
    submit(game, 'play_card', 'trigger')
    finish_waiting(1)
    assert clocks(game) == (0, 0, 0, 0)
    submit(game, 'end_turn')
    finish_waiting(1)
    state = game.state
    groups = state.end_turn_batches
    assert [b.activation.kind for b in groups] == ['effect', 'effect', 'natural']
    assert [len(b.subjects) for b in groups] == [1, 1, 1]
    assert [b.plans[0].repetitions for b in groups] == [3, 1, 1]
    assert [len(b.plans[0].contributors) for b in groups] == [2, 0, 0]
    assert all(b.completed and not b.interrupted for b in groups)
    assert len(state.end_turn_history) == 5
    assert all(r.completed and not r.interrupted for r in state.end_turn_history)
    assert clocks(game) == (1, 1, 1, 0)
    assert (state.turn, state.active_player) == (2, 2)
    assert state.entities[state.players[1].hero_id].armor == 5
    assert len(state.players[1].deck) == 4 and len(state.players[2].deck) == 3
    assert game.snapshot()['rng_state'] == initial_rng
    portable()
    summary = dict(registry='end-turn-matching-example-v1',
        schema=game.snapshot()['schema_version'], actions=len(game.history),
        events=len(game.events), choices=len(waiting), waiting_positions=positions,
        groups=len(groups), group_origins=[b.activation.kind for b in groups],
        accepted_counts=[b.plans[0].repetitions for b in groups],
        contributor_counts=[len(b.plans[0].contributors) for b in groups],
        positions=len(state.end_turn_history),
        armor=state.entities[state.players[1].hero_id].armor,
        clocks=list(clocks(game)), accepted_condition_survives_witness_transform=True,
        later_groups_recheck_condition=True, complete_prebatch_proof_retained=True,
        restored_cloned_replayed_every_wait=True,
        player_dtos_have_no_private_acceptance=True, no_rng_consumed=True,
        default_mechanics_only=True, synthetic_scenario=True,
        representative_cards_added=0, official_cn_calibrated=False,
        state_hash=game.state_hash())
    return game, waiting, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--output-dir', type=Path,
        default=Path(__file__).resolve().parents[1] / 'outputs')
    args = parser.parse_args()
    if args.replay is not None:
        game = replay(json.loads(args.replay.read_text(encoding='utf-8')), build_registry())
        print(json.dumps(dict(replayed=True, actions=len(game.history), state_hash=game.state_hash())))
        return
    game, waiting, summary = run()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for suffix, value in (('summary', summary), ('snapshot', game.snapshot()),
            ('waiting', waiting), ('replay', build_replay(game)),
            ('views', [game.observe(1), game.observe(2)])):
        (args.output_dir / f'v115-end-turn-matching-{suffix}.json').write_bytes(
            (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
