"""Synthetic Combo recipients, two accepted policy windows and physical self.

A policy Spell primes Combo and grants two finite Dragon policies. A plain
receiver leaves both policies untouched. A paid Dragon accepts its own self
count together with a sustained Beast condition and both policies. Its first
choice transforms the receiver and witness; the accepted extra bodies keep
their original plan. The next paid Dragon recomputes the false condition.

This standalone registry demonstrates a local public contract. It does not
adapt new real cards, establish a constructed tribal source, or calibrate CN.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, Keyword, PlayerSetup, Registry, Scenario)
from hs_sim.engine.model import (ComboRecipientMetadataFilter, ComboRepeatMatchSpec,
    ComboRepeatSpec, RepeatSourceEligibility)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Transform
from hs_sim.engine.combo_modifiers import AddComboRepeatModifier
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.repeat_source_conditions import qualifying_repeat_witnesses
from hs_sim.engine.replay import build_replay, replay


SOURCE = 'example.combo-match.source'
WITNESS = 'example.combo-match.beast-witness'
SELF = 'example.combo-match.self-receiver'
BLANK = 'example.combo-match.blank'
PROBE = 'example.combo-match.probe'
POLICY = 'example.combo-match.finite-policies'
AFTER = 'example.combo-match.after'
HIDDEN = 'example.combo-match.hidden'


def build_registry():
    registry = Registry('combo-matching-example-v1')
    plain = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=())
    dragon = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('dragon',))
    beast = CardMetadata(False, (CardClass.NEUTRAL,), None, tribes=('beast',))
    registry.register_card(CardDefinition('hero', 'Hero', CardType.HERO, health=30, metadata=plain))
    tribal = ComboRecipientMetadataFilter(tribes_any=('dragon',))
    source_match = ComboRepeatMatchSpec(tribal, RepeatSourceEligibility(
        'repeat.witness.controlled', tribes_any=('beast',), exclude_carrier=True))
    registry.register_card(CardDefinition(SOURCE, 'Synthetic sustained source',
        CardType.MINION, cost=1, health=5, metadata=dragon,
        combo_repeats=(ComboRepeatSpec(match=source_match),)))
    registry.register_card(CardDefinition(WITNESS, 'Synthetic Beast witness',
        CardType.MINION, cost=1, health=5, metadata=beast))
    for card_id in (BLANK, HIDDEN):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
            cost=1, health=5, metadata=plain))

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.play.card_id == SELF and context.combo.repeat_index == 1:
            witness_id = next(i for i in context.state.players[context.player_id].board
                if context.state.entities[i].card_id == WITNESS)
            effects += [Transform(witness_id, BLANK), Transform(context.source_id, BLANK)]
        return [RequestChoice(context.player_id,
            (ChoiceOption('resolve', 'Resolve this Combo', tuple(effects)),), source_id=context.source_id)]

    registry.register_behavior('example.combo-match.payload', payload)
    registry.register_card(CardDefinition(SELF, 'Synthetic self receiver', CardType.MINION,
        cost=1, health=5, metadata=dragon, keywords=(Keyword.COMBO,),
        combo='example.combo-match.payload', combo_repeats=(ComboRepeatSpec(3,
            (CardType.MINION,), 'self', ComboRepeatMatchSpec(tribal)),)))
    for card_id, card_metadata in ((PROBE, plain), (AFTER, dragon)):
        registry.register_card(CardDefinition(card_id, card_id, CardType.MINION,
            cost=1, health=5, metadata=card_metadata, keywords=(Keyword.COMBO,),
            combo='example.combo-match.payload'))
    registry.register_behavior('example.combo-match.policy', lambda context: [
        AddComboRepeatModifier(context.player_id, ComboRepeatSpec(match=ComboRepeatMatchSpec(tribal)),
            source_id=context.source_id, uses=1, trigger='play'),
        AddComboRepeatModifier(context.player_id, ComboRepeatSpec(match=ComboRepeatMatchSpec(tribal)),
            source_id=context.source_id, uses=1, trigger='activation')])
    registry.register_card(CardDefinition(POLICY, 'Synthetic next tribal policies',
        CardType.SPELL, cost=1, metadata=plain, on_play='example.combo-match.policy'))
    return registry


def _private_information_absent(game):
    forbidden = ('combo_acceptance', 'combo_submission_receipt_id', 'combo_policy_receipts',
        'ComboRecipient', 'FinishComboAcceptance', 'resolution_frame', 'contributors',
        'consumable_ids', 'source_eligibility', 'profile_id', 'qualifying_witnesses',
        'witness_ids', 'rng_state', 'consumption_applied')
    for player_id in (1, 2):
        port = game.for_player(player_id)
        encoded = json.dumps((port.observe(), port.legal_actions(), port.events()), sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded


def _submit(game, kind, card_id=None):
    port = game.for_player(1)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    choices = [action for action in listing['actions'] if action['type'] == kind]
    if card_id is not None:
        own = next(player for player in listing['observation']['players'] if player['id'] == 1)
        reference = next(card['ref'] for card in own['hand'] if card['card_id'] == card_id)
        choices = [action for action in choices if action['card'] == reference]
    assert choices, (kind, card_id)
    result = port.submit({'revision': listing['revision'], 'action': choices[0]})
    assert result['accepted'], result


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero', board=(SOURCE, WITNESS, SELF), hand=(POLICY, PROBE, SELF, AFTER),
            mana=10, max_mana=10), PlayerSetup('hero', hand=(HIDDEN,))), seed=153,
        name='synthetic-combo-two-window-physical-self-and-sustained-witness'), build_registry())
    rng_state = game.snapshot()['rng_state']
    old_self_id = next(i for i in game.state.players[1].board if game.state.entities[i].card_id == SELF)
    source_id = next(i for i in game.state.players[1].board if game.state.entities[i].card_id == SOURCE)
    witness_id = next(i for i in game.state.players[1].board if game.state.entities[i].card_id == WITNESS)
    old_self_policy = active_abilities(game.state.entities[old_self_id], 'combo_repeat')[0].id
    source_policy = active_abilities(game.state.entities[source_id], 'combo_repeat')[0]
    branches = [game]
    waiting = []
    waiting_positions = []

    def apply_all(kind, card_id=None):
        for branch in branches:
            _submit(branch, kind, card_id)
        assert all(branch.snapshot() == game.snapshot() for branch in branches)
        assert game.snapshot()['rng_state'] == rng_state

    def finish_waiting(expected_count, expected_contributors):
        while game.state.pending_choice is not None:
            snapshot = json.loads(json.dumps(game.snapshot()))
            root = game.state.play_history[-1]
            accepted = root.combo_acceptance
            policies = [r for r in game.state.combo_policy_receipts if r.play_id == root.id]
            assert accepted.status == 'activated'
            assert accepted.plan.repetitions == expected_count
            assert len(accepted.plan.contributors) == expected_contributors
            assert accepted.recipient.carrier_id == root.source_id
            assert accepted.recipient.card_id == root.card_id
            assert [p.phase for p in policies] == ['play', 'activation']
            assert all(p.consumption_applied for p in policies)
            assert old_self_policy not in accepted.plan.contributors
            proofs = [item for item in (*game._frame.prefix, *game._frame.continuation)
                if type(item).__name__ == 'FinishComboAcceptance']
            assert len(proofs) == 2
            activation_proof = next(item for item in proofs if item.phase == 'activation')
            assert activation_proof.context.play.combo_acceptance == accepted
            witnesses = qualifying_repeat_witnesses(activation_proof.context.state, game.registry,
                player_id=1, carrier_id=source_id,
                eligibility=source_policy.combo_repeat.match.source_eligibility)
            assert witnesses == (() if root.card_id == AFTER else (witness_id,))
            child = game.state.combo_history[-1]
            if root.card_id == SELF:
                assert accepted.recipient.carrier_id != old_self_id
                assert len(accepted.plan.consumable_ids) == 2
                assert source_policy.id in accepted.plan.contributors
                assert game.state.players[1].combo_modifiers == []
                assert [len(p.modifiers) for p in policies] == [1, 1]
                if child.repeat_index > 1:
                    assert game.state.entities[root.source_id].card_id == BLANK
                    assert game.state.entities[witness_id].card_id == BLANK
            else:
                assert accepted.plan.contributors == ()
                assert [p.modifiers for p in policies] == [(), ()]
            _private_information_absent(game)
            waiting.append(snapshot)
            waiting_positions.append(dict(card_id=root.card_id, repeat_index=child.repeat_index,
                count=expected_count, contributor_count=expected_contributors,
                phases=[p.phase for p in policies]))
            assert all(branch.snapshot() == snapshot for branch in branches)
            branches.extend((game.clone(), Game.from_snapshot(snapshot, build_registry())))
            for branch in branches:
                assert replay(build_replay(branch), build_registry()).snapshot() == snapshot
            apply_all('select_choice')

    apply_all('play_card', POLICY)
    spell = game.state.play_history[-1]
    assert spell.kind == CardType.SPELL and spell.combo_submission_receipt_id is None and spell.combo_acceptance is None
    assert game.state.combo_policy_receipts == []
    assert [m.trigger for m in game.state.players[1].combo_modifiers] == ['play', 'activation']
    apply_all('play_card', PROBE)
    finish_waiting(1, 0)
    assert [m.uses_remaining for m in game.state.players[1].combo_modifiers] == [1, 1]
    apply_all('play_card', SELF)
    finish_waiting(3, 4)
    apply_all('play_card', AFTER)
    finish_waiting(1, 0)
    roots = [record for record in game.state.play_history if record.kind == CardType.MINION]
    counts = [record.combo_acceptance.plan.repetitions for record in roots]
    assert counts == [1, 3, 1]
    assert [len(record.combo_acceptance.plan.contributors) for record in roots] == [0, 4, 0]
    assert len(game.state.combo_history) == 5
    assert len(game.state.combo_policy_receipts) == 6
    assert all(record.completed for record in roots)
    assert [record.cost for record in roots] == [1, 1, 1]
    assert all(record.mana_before - record.mana_after == 1 for record in roots)
    assert sum(event.kind == 'combo_modifier_used' for event in game.events) == 2
    assert game.state.players[1].mana == 6
    assert game.state.entities[game.state.players[1].hero_id].armor == 5
    assert game.snapshot()['resolution_frame'] is None
    assert game.snapshot()['rng_state'] == rng_state
    final_snapshot = game.snapshot()
    assert Game.from_snapshot(final_snapshot, build_registry()).snapshot() == final_snapshot
    for branch in branches:
        _private_information_absent(branch)
        assert replay(build_replay(branch), build_registry()).snapshot() == final_snapshot
    summary = dict(registry=game.registry.version, schema=final_snapshot['schema_version'],
        actions=len(game.history), events=len(game.events), combos=len(game.state.combo_history),
        choices=len(waiting), waiting_positions=waiting_positions, accepted_counts=counts,
        contributor_counts=[0, 4, 0], policy_receipts=len(game.state.combo_policy_receipts),
        once_paid_costs=[record.cost for record in roots], final_mana=6, armor=5,
        same_card_self_requires_physical_recipient=True,
        both_policy_windows_accept_and_consume_once=True,
        complete_max_keeps_lower_finite_sources=True,
        accepted_plan_survives_recipient_and_witness_transform=True,
        next_paid_root_rechecks_false_sustained_source=True,
        restored_cloned_and_replayed_every_wait=True,
        player_dtos_have_no_private_acceptance=True, no_rng_consumed=True,
        synthetic_scenario=True, representative_cards_added=0, official_cn_calibrated=False,
        constructed_tribal_source_verified=False, preentry_face_transform_covered=False,
        same_action_paid_nesting_covered=False, state_hash=game.state_hash())
    return game, waiting, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    if args.replay is not None:
        game = replay(json.loads(args.replay.read_text(encoding='utf-8')), build_registry())
        print(json.dumps(dict(replayed=True, actions=len(game.history), state_hash=game.state_hash())))
        return
    game, waiting, summary = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    for suffix, value in (('summary', summary), ('snapshot', game.snapshot()), ('waiting', waiting),
            ('replay', build_replay(game)), ('views', [game.observe(1), game.observe(2)])):
        (output / f'v112-combo-matching-{suffix}.json').write_bytes(
            (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
