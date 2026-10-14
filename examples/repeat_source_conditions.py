"""Synthetic sustained-source conditions and physical "another" witnesses.

All operations go through the seat-bound player API. Two different entities
with the same printed Dragon source definition qualify one another. Once the
middle Arcane root has been accepted, its first choice transforms one source
into a non-Dragon: the last extra payload still runs and really waits, whereas
the next paid root has only the remaining false source and executes once.

This fixture does not adapt TIME cards, establish constructed legality, exercise
automatic CAST routes, or calibrate official Chinese-server timing.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    Game, PlayerSetup, RecipientMetadataFilter, Registry, RepeatMatchSpec,
    RepeatSourceEligibility, Scenario, SpellRepeatSpec, SpellSchool, Zone)
from hs_sim.engine.effects import ChoiceOption, GainArmor, RequestChoice, Transform
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.repeat_source_conditions import qualifying_repeat_witnesses
from hs_sim.engine.spell_acceptance import FinishSpellAcceptance


SOURCE = 'example.repeat-source.dragon'
BLANK = 'example.repeat-source.non-dragon'
PROBE = 'example.repeat-source.before'
TRANSFORM = 'example.repeat-source.transform'
AFTER = 'example.repeat-source.after'
HIDDEN = 'example.repeat-source.hidden'


def build_registry():
    """Install a new independent registry, including the same witness policy."""
    registry = Registry('repeat-source-conditions-example-v1')
    metadata = CardMetadata(False, (CardClass.MAGE,), None, tribes=())
    dragon_metadata = CardMetadata(False, (CardClass.MAGE,), None, tribes=('dragon',))
    for card_id in ('hero.one', 'hero.two'):
        registry.register_card(CardDefinition(card_id, card_id, CardType.HERO,
            health=30, metadata=metadata))
    match = RepeatMatchSpec(
        recipient_metadata=RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)),
        source_eligibility=RepeatSourceEligibility('repeat.witness.controlled',
            tribes_any=('dragon',), exclude_carrier=True))
    registry.register_card(CardDefinition(SOURCE, 'Synthetic another-Dragon source',
        CardType.MINION, cost=1, attack=1, health=5, metadata=dragon_metadata,
        spell_repeats=(SpellRepeatSpec(casts=2, class_mode='any', match=match),)))
    registry.register_card(CardDefinition(BLANK, 'Synthetic non-Dragon shape',
        CardType.MINION, cost=1, attack=1, health=5, metadata=metadata))
    registry.register_card(CardDefinition(HIDDEN, 'Private fixture hand card',
        CardType.MINION, cost=1, health=1, metadata=metadata))

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.cast.card_id == TRANSFORM and context.cast.iteration == 1:
            # This is an ordinary synthetic card payload, not a special
            # conditional-source handler. Both entities have the same card ID;
            # select the later physical source for the public Transform effect.
            sources = [entity_id for entity_id in context.state.players[context.player_id].board
                if context.state.entities[entity_id].card_id == SOURCE]
            assert len(sources) == 2
            effects.append(Transform(max(sources), BLANK))
        # No repeat_key: every actual payload asks for a separate decision.
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Resolve this Arcane payload', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior('example.repeat-source.payload', payload)
    for card_id in (PROBE, TRANSFORM, AFTER):
        registry.register_card(CardDefinition(card_id, card_id, CardType.SPELL,
            cost=1, spell_school=SpellSchool.ARCANE,
            on_play='example.repeat-source.payload', metadata=metadata))
    return registry


def _private_information_absent(game):
    forbidden = ('spell_submission', 'spell_payload', 'spell_acceptance_closed',
        'spell_acceptances', 'FinishSpellAcceptance', 'resolution_frame',
        'contributors', 'behavior_ids', 'rng_state', 'source_results',
        'spell_source_results', 'qualifying_witnesses', 'witness_ids')
    for player_id in (1, 2):
        port = game.for_player(player_id)
        encoded = json.dumps(dict(observation=port.observe(),
            actions=port.legal_actions(), events=port.events()), sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)
        if player_id == 1:
            assert HIDDEN not in encoded


def _submit(game, kind, card_id=None):
    port = game.for_player(game.state.active_player)
    listing = port.legal_actions()
    assert listing['error'] is None, listing
    actions = [action for action in listing['actions'] if action['type'] == kind]
    if card_id is not None:
        own = next(player for player in listing['observation']['players']
            if player['id'] == game.state.active_player)
        reference = next(card['ref'] for card in own['hand'] if card['card_id'] == card_id)
        actions = [action for action in actions if action['card'] == reference]
    assert actions, (kind, card_id)
    result = port.submit({'revision': listing['revision'], 'action': actions[0]})
    assert result['accepted'], result
    return result


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero.one', hand=(SOURCE, PROBE, SOURCE, TRANSFORM, AFTER),
            mana=10, max_mana=10),
        PlayerSetup('hero.two', hand=(HIDDEN,))), seed=151,
        name='synthetic-sustained-source-and-physical-another'), build_registry())
    rng_state = game.snapshot()['rng_state']
    branches = [game]
    waiting = []
    waiting_positions = []
    source_ids = []

    def apply_all(kind, card_id=None):
        for branch in branches:
            _submit(branch, kind, card_id)
        assert all(branch.snapshot() == game.snapshot() for branch in branches)
        assert game.snapshot()['rng_state'] == rng_state

    def finish_waiting(expected_quota):
        while game.state.pending_choice is not None:
            snapshot = json.loads(json.dumps(game.snapshot()))
            root = game.state.play_history[-1]
            assert root.kind == CardType.SPELL
            assert root.spell_payload.casts == expected_quota
            assert not root.completed and not root.spell_acceptance_closed
            assert game._frame.spell_acceptances == (root.id,)
            proof = next(work for work in (*game._frame.prefix, *game._frame.continuation)
                if isinstance(work, FinishSpellAcceptance) and work.play_id == root.id)
            original_state = proof.resolution.state
            original_sources = [entity_id for entity_id in original_state.players[1].board
                if original_state.entities[entity_id].card_id == SOURCE]
            assert len(original_sources) == (2 if root.card_id == TRANSFORM else 1)
            for source_id in original_sources:
                ability = active_abilities(original_state.entities[source_id], 'spell_repeat')[0]
                witnesses = qualifying_repeat_witnesses(original_state, game.registry,
                    player_id=1, carrier_id=source_id,
                    eligibility=ability.spell_repeat.match.source_eligibility)
                expected = tuple(entity_id for entity_id in original_sources if entity_id != source_id)
                assert witnesses == expected
            iteration = next(cast.iteration for cast in reversed(game.state.cast_history)
                if cast.play_id == root.id)
            if root.card_id == TRANSFORM:
                assert len(root.spell_payload.contributors) == 2
                if iteration == 2:
                    assert game.state.entities[source_ids[1]].card_id == BLANK
                    assert game.state.entities[source_ids[0]].card_id == SOURCE
            else:
                assert root.spell_payload.contributors == ()
            _private_information_absent(game)
            waiting.append(snapshot)
            waiting_positions.append(dict(card_id=root.card_id,
                iteration=iteration, quota=expected_quota))
            assert all(branch.snapshot() == snapshot for branch in branches)
            branches.extend((game.clone(), Game.from_snapshot(snapshot, build_registry())))
            for branch in branches:
                assert replay(build_replay(branch), build_registry()).snapshot() == snapshot
            apply_all('select_choice')

    apply_all('play_card', SOURCE)
    source_ids.append(game.state.play_history[-1].source_id)
    original_ability = active_abilities(game.state.entities[source_ids[0]], 'spell_repeat')[0]
    apply_all('play_card', PROBE)
    finish_waiting(1)
    apply_all('play_card', SOURCE)
    source_ids.append(game.state.play_history[-1].source_id)
    assert source_ids[0] != source_ids[1]
    assert all(game.state.entities[entity_id].card_id == SOURCE for entity_id in source_ids)
    apply_all('play_card', TRANSFORM)
    finish_waiting(2)
    assert game.state.entities[source_ids[1]].card_id == BLANK
    apply_all('play_card', AFTER)
    finish_waiting(1)

    roots = [play for play in game.state.play_history if play.kind == CardType.SPELL]
    quotas = [play.spell_payload.casts for play in roots]
    assert quotas == [1, 2, 1]
    assert [len(play.spell_payload.contributors) for play in roots] == [0, 2, 0]
    assert [play.card_id for play in roots] == [PROBE, TRANSFORM, AFTER]
    assert all(play.completed and play.spell_acceptance_closed for play in roots)
    assert all(play.spell_submission.modifiers == () for play in roots)
    assert all(play.cost == 1 and play.mana_before - play.mana_after == 1 for play in roots)
    assert all(cast.completed and not cast.interrupted for cast in game.state.cast_history)
    assert len(game.state.cast_history) == 4
    assert game.state.players[1].mana == 5
    assert game.state.entities[game.state.players[1].hero_id].armor == 4
    assert active_abilities(game.state.entities[source_ids[0]], 'spell_repeat') == (original_ability,)
    assert not original_ability.consumed and original_ability.uses_remaining is None
    assert all(branch.state.players[1].spell_modifiers == [] for branch in branches)
    assert all(game.state.entities[entity_id].zone == Zone.BOARD for entity_id in source_ids)
    assert game.snapshot()['resolution_frame'] is None
    assert game.snapshot()['rng_state'] == rng_state
    final_snapshot = game.snapshot()
    assert Game.from_snapshot(final_snapshot, build_registry()).snapshot() == final_snapshot
    for branch in branches:
        _private_information_absent(branch)
        assert replay(build_replay(branch), build_registry()).snapshot() == final_snapshot
    assert [position['iteration'] for position in waiting_positions] == [1, 1, 2, 1]
    summary = dict(registry=game.registry.version, schema=final_snapshot['schema_version'],
        actions=len(game.history), events=len(game.events), casts=len(game.state.cast_history),
        choices=len(waiting), waiting_positions=waiting_positions,
        accepted_quotas=quotas, contributor_counts=[0, 2, 0],
        once_paid_costs=[play.cost for play in roots], final_mana=5, armor=4,
        same_card_id_different_physical_witnesses=True,
        accepted_plan_survives_witness_and_source_transform=True,
        following_paid_root_rechecks_false_source=True,
        all_false_unit_roots_wait_and_restore=True,
        last_extra_wait_has_acceptance_obligation=True,
        restored_cloned_and_replayed_every_wait=True,
        player_dtos_have_no_private_acceptance=True,
        no_rng_or_source_usage_consumed=True,
        synthetic_scenario=True, representative_cards_added=0,
        official_cn_calibrated=False, automatic_cast_covered=False,
        state_hash=game.state_hash())
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
    for suffix, value in (('summary', summary), ('snapshot', game.snapshot()),
            ('waiting', waiting), ('replay', build_replay(game)),
            ('views', [game.observe(1), game.observe(2)])):
        (output / f'v110-repeat-source-conditions-{suffix}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
