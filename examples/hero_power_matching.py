"""Synthetic source conditions through three default public Hero Power roots.

This example is internal evidence, not official timing or constructed-pool coverage.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, HeroPowerReference, PlayerSetup, Registry, Scenario, TriggerHeroPower)
from hs_sim.engine.effects import (ChoiceOption, GainArmor, InvokeBehavior,
    RequestChoice, Transform)
from hs_sim.engine.hero_powers import AddHeroPower
from hs_sim.engine.model import (HeroPowerRepeatMatchSpec, HeroPowerRepeatSpec,
    RepeatSourceEligibility)
from hs_sim.engine.replay import build_replay, replay


HIDDEN = 'native.private.enemy'


def metadata(tribes=()):
    return CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=tribes)


def build_registry():
    registry = Registry('hero-power-matching-example-v1')
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO,
        health=30, metadata=metadata()))
    for name, tribes in (('plain', ()), ('beast', ('beast',)), (HIDDEN, ())):
        registry.register_card(CardDefinition(name, name, CardType.MINION,
            health=6, metadata=metadata(tribes)))
    condition = RepeatSourceEligibility('repeat.witness.controlled',
        tribes_any=('beast',), exclude_carrier=True)
    for name, count in (('conditional.two', 2), ('conditional.three', 3)):
        registry.register_card(CardDefinition(name, name, CardType.MINION,
            health=6, metadata=metadata(), hero_power_repeats=(HeroPowerRepeatSpec(
                count, match=HeroPowerRepeatMatchSpec(condition)),)))

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.power.origin == 'manual' and context.power_payload.repeat_index == 1:
            witness = next(i for i in context.state.players[context.player_id].board
                if context.state.entities[i].card_id == 'beast')
            effects.insert(0, Transform(witness, 'plain'))
        return [RequestChoice(context.player_id,
            (ChoiceOption('resolve', 'Resolve', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior('native.power', payload)
    # Its own metadata is deliberately absent: matching queries source witnesses.
    registry.register_card(CardDefinition('power', 'Power', CardType.HERO_POWER,
        cost=2, on_use='native.power'))
    registry.register_behavior('native.trigger.primary', lambda c: [TriggerHeroPower(
        c.player_id, c.source_id, targeting='explicit', choices='player')])

    def trigger_additional(context):
        player = context.state.players[context.player_id]
        power = context.state.entities[player.additional_hero_power_ids[-1]]
        return [TriggerHeroPower(context.player_id, context.source_id,
            targeting='explicit', choices='player', power=HeroPowerReference.capture(power))]

    registry.register_behavior('native.trigger.additional', trigger_additional)
    registry.register_behavior('native.install.additional', lambda c: [
        AddHeroPower(c.player_id, 'power', c.source_id),
        InvokeBehavior('native.trigger.additional', c.source_id, c.player_id)])
    for name, body in (('trigger', 'native.trigger.primary'),
            ('install.and.trigger', 'native.install.additional')):
        registry.register_card(CardDefinition(name, name, CardType.SPELL, cost=1,
            on_play=body, metadata=metadata()))
    return registry


def _private_information_absent(game):
    forbidden = ('hero_power_history', 'hero_power_payload_history',
        'hero_power_payload_batches', 'repeat_plan', 'contributors',
        'resolution_frame', 'source_eligibility', 'profile_id', 'rng_state')
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


def _submit(game, kind, card_id=None):
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


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero', hand=('trigger', 'install.and.trigger'),
            board=('conditional.two', 'conditional.three', 'beast'),
            deck=('plain',) * 4, hero_power_card_id='power', mana=10, max_mana=10),
        PlayerSetup('hero', hand=(HIDDEN,), deck=(HIDDEN,) * 4,
            hero_power_card_id='power')), seed=114), build_registry())
    initial_rng = game.snapshot()['rng_state']
    original_power = game.state.players[1].hero_power_id
    waiting = []
    positions = []

    def portable():
        snapshot = json.loads(json.dumps(game.snapshot()))
        restored = Game.from_snapshot(snapshot, build_registry())
        assert restored.snapshot() == snapshot
        assert restored.clone().snapshot() == snapshot
        assert replay(build_replay(restored), build_registry()).snapshot() == snapshot
        _private_information_absent(game)

    def finish_waiting(count):
        observed = 0
        while game.state.pending_choice is not None:
            portable()
            waiting.append(game.snapshot())
            row = next(r for r in reversed(game.state.hero_power_payload_history)
                if r.execution_order is not None and not r.completed)
            root = game.state.hero_power_history[row.capture.power_id - 1]
            positions.append(dict(power_id=root.id, origin=root.origin,
                repeat_index=row.capture.repeat_index, repetitions=root.repeat_plan.repetitions,
                contributors=len(root.repeat_plan.contributors)))
            _submit(game, 'select_choice')
            observed += 1
        assert observed == count
        portable()

    _submit(game, 'use_hero_power')
    finish_waiting(3)
    _submit(game, 'play_card', 'trigger')
    finish_waiting(1)
    _submit(game, 'play_card', 'install.and.trigger')
    finish_waiting(1)
    state = game.state
    roots = state.hero_power_history
    extra = state.players[1].additional_hero_power_ids[-1]
    assert [p.repeat_plan.repetitions for p in roots] == [3, 1, 1]
    assert [len(p.repeat_plan.contributors) for p in roots] == [2, 0, 0]
    assert [p.origin for p in roots] == ['manual', 'effect', 'effect']
    assert [p.source_id for p in roots] == [original_power, original_power, extra]
    assert original_power != extra and all(p.card_id == 'power' for p in roots)
    assert roots[2].activator_id not in (original_power, extra)
    assert (state.players[1].mana, state.players[1].hero_power_uses_this_turn,
        state.entities[original_power].uses_this_turn, state.entities[extra].uses_this_turn) == (6, 1, 1, 0)
    assert state.entities[state.players[1].hero_id].armor == 5
    assert all(p.completed and p.failure is None for p in roots)
    assert game.snapshot()['rng_state'] == initial_rng
    summary = dict(registry='hero-power-matching-example-v1',
        schema=game.snapshot()['schema_version'], actions=len(game.history), events=len(game.events),
        choices=len(waiting), waiting_positions=positions, roots=len(roots),
        root_origins=[p.origin for p in roots], accepted_counts=[p.repeat_plan.repetitions for p in roots],
        contributor_counts=[len(p.repeat_plan.contributors) for p in roots],
        payloads=len(state.hero_power_payload_history), final_mana=state.players[1].mana,
        armor=state.entities[state.players[1].hero_id].armor,
        once_paid_power_cost=roots[0].cost, manual_uses=state.players[1].hero_power_uses_this_turn,
        accepted_condition_survives_witness_transform=True, later_roots_recheck_condition=True,
        explicit_same_face_additional_physical_identity=True,
        restored_cloned_replayed_every_wait=True, player_dtos_have_no_private_acceptance=True,
        no_rng_consumed=True, default_mechanics_only=True, success_empty_or_multi_body_claimed=False,
        synthetic_scenario=True, representative_cards_added=0, official_cn_calibrated=False,
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
    for suffix, value in (('summary', summary), ('snapshot', game.snapshot()), ('waiting', waiting),
            ('replay', build_replay(game)), ('views', [game.observe(1), game.observe(2)])):
        (args.output_dir / f'v114-hero-power-matching-{suffix}.json').write_bytes(
            (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
