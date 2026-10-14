"""Synthetic physical Deathrattle faces, per-payload origins and lasting policies.

A paid policy and grant precede a plain natural death, a Dragon's explicitly
triggered printed/granted bodies, and a later natural Dragon death. The first
Dragon body changes the receiver and Beast witness. Accepted counts survive;
the next group queries the changed board. This is a local public mechanism
example, with no additional real card or official CN calibration claim.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayerEffectSpec, PlayerSetup, Registry, Scenario)
from hs_sim.engine.effects import (ChoiceOption, Destroy, GainArmor,
    GrantDeathrattle, RequestChoice, Transform, TriggerDeathrattles)
from hs_sim.engine.model import (DeathrattleRecipientMetadataFilter,
    DeathrattleRepeatMatchSpec, DeathrattleRepeatSpec, RepeatSourceEligibility)
from hs_sim.engine.player_effects import AddPlayerEffect
from hs_sim.engine.replay import build_replay, replay


SOURCE = 'example.dr-match.sustained-source'
WITNESS = 'example.dr-match.beast-witness'
SELF = 'example.dr-match.self-receiver'
BLANK = 'example.dr-match.blank'
PROBE = 'example.dr-match.plain-probe'
POLICY = 'example.dr-match.printed-policy'
AFTER = 'example.dr-match.after'
HIDDEN = 'example.dr-match.hidden'
GRANT = 'example.dr-match.grant'
KILL = 'example.dr-match.kill'
TRIGGER = 'example.dr-match.trigger'
PAYLOAD = 'example.dr-match.payload'


def build_registry():
    registry = Registry('deathrattle-matching-example-v1')
    plain = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    dragon = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('dragon',))
    beast = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('beast',))
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO,
        health=30, metadata=plain))
    tribal = DeathrattleRecipientMetadataFilter(tribes_any=('dragon',))
    sustained = DeathrattleRepeatMatchSpec(tribal, RepeatSourceEligibility(
        'repeat.witness.controlled', tribes_any=('beast',), exclude_carrier=True))
    registry.register_card(CardDefinition(SOURCE, 'Synthetic sustained source',
        CardType.MINION, cost=1, health=6, metadata=plain,
        deathrattle_repeats=(DeathrattleRepeatSpec(origins=('printed',), match=sustained),)))
    registry.register_card(CardDefinition(WITNESS, 'Synthetic Beast witness',
        CardType.MINION, cost=1, health=6, metadata=beast))
    for card_id in (BLANK, HIDDEN):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
            cost=1, health=6, metadata=plain))

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        capture = context.deathrattle
        if (capture.card_id == SELF and capture.ability.origin == 'printed'
                and capture.repeat_index == 1):
            witness_id = next(i for i in context.state.players[context.player_id].board
                if context.state.entities[i].card_id == WITNESS)
            effects += [Transform(context.source_id, BLANK), Transform(witness_id, BLANK)]
        return [RequestChoice(context.player_id,
            (ChoiceOption('resolve', 'Resolve this Deathrattle', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior(PAYLOAD, payload)
    registry.register_card(CardDefinition(SELF, 'Synthetic self receiver',
        CardType.MINION, cost=1, health=6, metadata=dragon, deathrattle=PAYLOAD,
        deathrattle_repeats=(DeathrattleRepeatSpec(3, scope='self',
            origins=('granted',), match=DeathrattleRepeatMatchSpec(tribal)),)))
    for card_id, card_metadata in ((PROBE, plain), (AFTER, dragon)):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
            cost=1, health=6, metadata=card_metadata, deathrattle=PAYLOAD))
    registry.register_behavior(POLICY,
        lambda context: [AddPlayerEffect(context.player_id, POLICY, context.source_id)])
    registry.register_player_effect(PlayerEffectSpec(POLICY, POLICY,
        deathrattle_repeats=(DeathrattleRepeatSpec(origins=('printed',),
            match=DeathrattleRepeatMatchSpec(tribal)),)))
    registry.register_behavior(GRANT,
        lambda context: [GrantDeathrattle(context.target_id, PAYLOAD, context.source_id)])
    registry.register_behavior(KILL,
        lambda context: [Destroy(context.target_id, context.source_id)])
    registry.register_behavior(TRIGGER,
        lambda context: [TriggerDeathrattles(context.target_id, context.source_id)])
    for card_id in (POLICY, GRANT, KILL, TRIGGER):
        registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
            cost=1, metadata=plain, on_play=card_id, requires_target=card_id != POLICY))
    return registry


def _private_information_absent(game):
    forbidden = ('deathrattle_batches', 'deathrattle_history', 'DeathrattleRecipient',
        'FinishDeathrattleBatch', 'resolution_frame', 'contributors', 'spec_index',
        'source_eligibility', 'profile_id', 'qualifying_witnesses', 'witness_ids', 'rng_state')
    for player_id in (1, 2):
        port = game.for_player(player_id)
        view, actions, events = port.observe(), port.legal_actions(), port.events()
        encoded = json.dumps((view, actions, events), sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded
        before = game.snapshot()
        view['observation']['players'][0]['hero']['armor'] = 999
        assert game.snapshot() == before


def _submit(game, kind, card_id=None, target_card_id=None):
    port = game.for_player(1)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    actions = [action for action in listing['actions'] if action['type'] == kind]
    own = next(player for player in listing['observation']['players'] if player['id'] == 1)
    if card_id is not None:
        reference = next(card['ref'] for card in own['hand'] if card['card_id'] == card_id)
        actions = [action for action in actions if action['card'] == reference]
    if target_card_id is not None:
        target = next(card['ref'] for card in own['board'] if card['card_id'] == target_card_id)
        actions = [action for action in actions if action.get('target') == target]
    assert actions, (kind, card_id, target_card_id)
    result = port.submit({'revision': listing['revision'], 'action': actions[0]})
    assert result['accepted'], result


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero', board=(SOURCE, WITNESS, SELF, PROBE, AFTER),
            hand=(POLICY, GRANT, KILL, TRIGGER, KILL), mana=10, max_mana=10),
        PlayerSetup('hero', hand=(HIDDEN,))), seed=154,
        name='synthetic-deathrattle-accepted-faces-origin-plans-and-lasting-policy'), build_registry())
    initial_rng = game.snapshot()['rng_state']
    branches = [game]
    waiting, positions = [], []

    def apply_all(kind, card_id=None, target_card_id=None):
        for branch in branches:
            _submit(branch, kind, card_id, target_card_id)
        assert all(branch.snapshot() == game.snapshot() for branch in branches)
        assert game.snapshot()['rng_state'] == initial_rng

    def finish_waiting(expected_counts, expected_sources):
        while game.state.pending_choice is not None:
            snapshot = json.loads(json.dumps(game.snapshot()))
            batch = game.state.deathrattle_batches[-1]
            rows = game.state.deathrattle_history[batch.id - 1:batch.id - 1 + batch.total]
            running = next(record for record in rows
                if record.execution_order is not None and not record.completed)
            assert [payload.plan.repetitions for payload in batch.payloads] == expected_counts
            assert [len(payload.plan.contributors) for payload in batch.payloads] == expected_sources
            proofs = [item for item in (*game._frame.prefix, *game._frame.continuation)
                if type(item).__name__ == 'FinishDeathrattleBatch']
            assert len(proofs) == 1 and proofs[0].batch == batch
            assert proofs[0].context.state.deathrattle_history[batch.id - 1].execution_order is None
            if running.capture.card_id == SELF and running.capture.repeat_index > 1:
                assert game.state.entities[running.capture.carrier_id].card_id == BLANK
            if running.capture.card_id == SELF and running.capture.ability.origin == 'granted':
                assert game.state.entities[running.capture.carrier_id].card_id == BLANK
            positions.append(dict(group_id=batch.id, origin=running.capture.origin,
                payload_origin=running.capture.ability.origin,
                repeat_index=running.capture.repeat_index, counts=expected_counts,
                contributor_counts=expected_sources))
            _private_information_absent(game)
            assert all(branch.snapshot() == snapshot for branch in branches)
            waiting.append(snapshot)
            branches.extend((game.clone(), Game.from_snapshot(snapshot, build_registry())))
            for branch in branches:
                assert replay(build_replay(branch), build_registry()).snapshot() == snapshot
            apply_all('select_choice')

    apply_all('play_card', POLICY)
    policy_id = game.state.players[1].player_effects[0].id
    apply_all('play_card', GRANT, SELF)
    apply_all('play_card', KILL, PROBE)
    finish_waiting([1], [0])
    apply_all('play_card', TRIGGER, SELF)
    finish_waiting([2, 3], [2, 1])
    apply_all('play_card', KILL, AFTER)
    finish_waiting([2], [1])

    batches = game.state.deathrattle_batches
    origins = [game.state.deathrattle_history[b.id - 1].capture.origin for b in batches]
    assert origins == ['death', 'effect', 'death']
    assert len(waiting) == len(game.state.deathrattle_history) == 8
    assert all(record.completed and not record.interrupted for record in game.state.deathrattle_history)
    assert len(game.state.death_history) == 2
    assert [effect.id for effect in game.state.players[1].player_effects] == [policy_id]
    assert game.state.players[1].player_effects[0].remaining_turns is None
    paid = game.state.play_history
    assert len(paid) == 5 and all(record.completed and record.cost == 1 for record in paid)
    assert all(record.mana_before - record.mana_after == 1 for record in paid)
    assert game.state.players[1].mana == 5
    assert game.state.entities[game.state.players[1].hero_id].armor == 8
    assert game.snapshot()['resolution_frame'] is None
    final = game.snapshot()
    assert Game.from_snapshot(final, build_registry()).snapshot() == final
    for branch in branches:
        _private_information_absent(branch)
        assert replay(build_replay(branch), build_registry()).snapshot() == final
    summary = dict(registry=game.registry.version, schema=final['schema_version'],
        actions=len(game.history), events=len(game.events), choices=len(waiting),
        waiting_positions=positions, groups=len(batches), group_origins=origins,
        accepted_counts=[[p.plan.repetitions for p in b.payloads] for b in batches],
        contributor_counts=[[len(p.plan.contributors) for p in b.payloads] for b in batches],
        deathrattles=len(game.state.deathrattle_history), natural_deaths=len(game.state.death_history),
        once_paid_costs=[record.cost for record in paid], final_mana=5, armor=8,
        printed_and_granted_payloads_have_separate_plans=True,
        accepted_face_and_condition_survive_transform=True,
        next_group_rechecks_condition=True, persistent_policy_not_consumed=True,
        restored_cloned_replayed_every_wait=True, player_dtos_have_no_private_acceptance=True,
        no_rng_consumed=True, synthetic_scenario=True, representative_cards_added=0,
        official_cn_calibrated=False, constructed_tribal_source_verified=False,
        paid_graveyard_transform_covered=False, state_hash=game.state_hash())
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
        (args.output_dir / f'v113-deathrattle-matching-{suffix}.json').write_bytes(
            (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
