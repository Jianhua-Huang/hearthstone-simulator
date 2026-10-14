"""Necessary Vexallus manual-spell fixture with independent waiting recovery.

The real Arcane Bolt, Fireball, Frostbolt and Coin use the representative
registry unchanged. One local synthetic Arcane spell exposes both iterations
as independent choices, including the final extra payload's acceptance tail.
This is an experimental mechanism scenario, not a legal constructed deck or
an official timing calibration. It does not exercise automatic CAST routes.
"""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType,
    EndTurn, Game, GenerationContext, PlayCard, PlayerSetup, Scenario,
    SelectChoice, SpellSchool, Zone)
from hs_sim.engine.effects import ChoiceOption, Destroy, GainArmor, RequestChoice
from hs_sim.engine.lifecycle import active_abilities
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.representative import build_registry as representative_registry


ARCANE_CHOICE = 'example.spell-match.arcane-choice'


def build_registry():
    """Rebuild the real pinned pack, then install only this local fixture."""
    registry = representative_registry()

    def payload(context):
        effects = [GainArmor(context.player_id, 1)]
        if context.cast.iteration == 2:
            carrier = next(entity.id for entity in context.state.entities.values()
                if entity.card_id == 'RLK_541' and entity.zone == Zone.BOARD)
            effects.append(Destroy(carrier, context.source_id))
        # No repeat_key: each iteration really waits for its own decision.
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Resolve this Arcane iteration', tuple(effects)),),
            source_id=context.source_id)]

    registry.register_behavior(ARCANE_CHOICE + '.payload', payload)
    registry.register_card(CardDefinition(ARCANE_CHOICE, 'Synthetic Arcane choice',
        CardType.SPELL, cost=1, spell_school=SpellSchool.ARCANE,
        on_play=ARCANE_CHOICE + '.payload',
        metadata=CardMetadata(False, (CardClass.MAGE,), None)))
    return registry


def _private_information_absent(game):
    forbidden = ('spell_submission', 'spell_payload', 'spell_acceptance_closed',
        'spell_acceptances', 'FinishSpellAcceptance', 'resolution_frame',
        'contributors', 'behavior_ids', 'rng_state')
    for player_id in (1, 2):
        encoded = json.dumps(game.observe(player_id), sort_keys=True)
        assert all('"' + field + '"' not in encoded for field in forbidden)


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('HERO_08', hand=('RLK_541', 'RLK_843', 'CS2_029',
            'GAME_005', 'CS2_024', ARCANE_CHOICE), deck=('CS2_182',) * 4,
            mana=10, max_mana=10),
        PlayerSetup('HERO_01', deck=('CS2_182',) * 4)), seed=150,
        name='representative-vexallus-manual-school-match',
        generation_context=GenerationContext('local-2026-09-23', 'experimental')),
        build_registry())
    enemy = game.state.players[2].hero_id

    def play(card_id, target_id=None):
        entity_id = next(entity_id for entity_id in game.state.players[1].hand
            if game.state.entities[entity_id].card_id == card_id)
        game.apply(PlayCard(1, entity_id, target_id))
        return entity_id

    carrier_id = play('RLK_541')
    ability = active_abilities(game.state.entities[carrier_id], 'spell_repeat')[0]
    assert game.state.players[1].mana == 5
    assert (game.state.entities[carrier_id].attack,
        game.state.entities[carrier_id].health) == (3, 5)

    play('RLK_843', enemy)
    bolt = game.state.play_history[-1]
    assert bolt.spell_payload.casts == 2 and bolt.spell_payload.hero_class == CardClass.MAGE
    assert [source.ability.id for source in bolt.spell_payload.contributors] == [ability.id]
    assert bolt.cost == 1 and (bolt.mana_before, bolt.mana_after) == (5, 4)
    bolt_casts = [cast for cast in game.state.cast_history if cast.play_id == bolt.id]
    assert [cast.iteration for cast in bolt_casts] == [1, 2]
    assert all(cast.manathirst and cast.completed for cast in bolt_casts)
    assert game.state.entities[enemy].health == 24

    play('CS2_029', enemy)
    fire = game.state.play_history[-1]
    assert fire.spell_payload.casts == 1 and not fire.spell_payload.contributors
    assert fire.cost == 4 and (fire.mana_before, fire.mana_after) == (4, 0)
    assert game.state.entities[enemy].health == 18
    play('GAME_005')
    coin = game.state.play_history[-1]
    assert coin.spell_payload.casts == 1 and not coin.spell_payload.contributors
    assert coin.cost == 0 and game.state.players[1].mana == 1

    game.apply(EndTurn(1))
    game.apply(EndTurn(2))
    play('CS2_024', enemy)
    frost = game.state.play_history[-1]
    assert frost.spell_payload.casts == 1 and not frost.spell_payload.contributors
    assert frost.cost == 2 and (frost.mana_before, frost.mana_after) == (10, 8)
    assert game.state.entities[enemy].health == 15
    play(ARCANE_CHOICE)
    branches = [game]
    waiting = []
    waiting_iterations = []
    while game.state.pending_choice is not None:
        assert len(waiting) < 2
        snapshot = json.loads(json.dumps(game.snapshot()))
        repeat = game.state.spell_repeats[-1]
        root = game.state.play_history[-1]
        assert repeat.play_id == root.id and repeat.casts == 2 and repeat.running
        assert repeat.completed == len(waiting)
        assert not root.completed and not root.spell_acceptance_closed
        assert game._frame.spell_acceptances == (root.id,)
        _private_information_absent(game)
        waiting.append(snapshot)
        waiting_iterations.append(repeat.completed + 1)

        # Existing branches must reach each actual wait unchanged. Add both a
        # clone and a restore built from a new representative registry there.
        assert all(branch.snapshot() == snapshot for branch in branches)
        branches.extend((game.clone(), Game.from_snapshot(snapshot, build_registry())))
        assert replay(build_replay(game), build_registry()).snapshot() == snapshot
        for branch in branches:
            assert replay(build_replay(branch), build_registry()).snapshot() == snapshot
            choice = branch.state.pending_choice
            branch.apply(SelectChoice(choice.player_id, choice.id, ('resolve',)))
        assert all(branch.snapshot() == game.snapshot() for branch in branches)

    assert waiting_iterations == [1, 2]
    roots = [play for play in game.state.play_history if play.kind == CardType.SPELL]
    quotas = [play.spell_payload.casts for play in roots]
    assert [play.card_id for play in roots] == [
        'RLK_843', 'CS2_029', 'GAME_005', 'CS2_024', ARCANE_CHOICE]
    assert quotas == [2, 1, 1, 1, 2]
    assert all(play.completed and play.spell_acceptance_closed for play in roots)
    assert all(play.spell_submission.modifiers == () for play in roots)
    assert [len(play.spell_payload.contributors) for play in roots] == [1, 0, 0, 0, 1]
    assert [play.cost for play in roots] == [1, 4, 0, 2, 1]
    assert game.state.players[1].mana == 7
    assert game.state.entities[game.state.players[1].hero_id].armor == 2
    assert game.state.entities[carrier_id].zone == Zone.GRAVEYARD
    assert len(game.state.cast_history) == sum(quotas)
    assert all(cast.completed and not cast.interrupted for cast in game.state.cast_history)
    assert game.snapshot()['resolution_frame'] is None
    final_snapshot = game.snapshot()
    assert Game.from_snapshot(final_snapshot, build_registry()).snapshot() == final_snapshot
    for branch in branches:
        _private_information_absent(branch)
        assert replay(build_replay(branch), build_registry()).snapshot() == final_snapshot
    summary = dict(raw_card='RLK_541', real_arcane_recipient='RLK_843',
        registry=game.registry.version, schema=final_snapshot['schema_version'],
        actions=len(game.history), events=len(game.events), casts=len(game.state.cast_history),
        choices=len(waiting), waiting_iterations=waiting_iterations,
        accepted_quotas=quotas, once_paid_costs=[play.cost for play in roots],
        final_mana=game.state.players[1].mana, enemy_health=game.state.entities[enemy].health,
        armor=game.state.entities[game.state.players[1].hero_id].armor,
        restored_and_replayed=True, same_class_arcane_repeated=True,
        non_arcane_and_no_school_single=True, last_extra_wait_has_acceptance_obligation=True,
        final_source_zone=game.state.entities[carrier_id].zone.value,
        synthetic_cards_in_this_example=1, representative_cards_added=1,
        experimental_scenario=True, official_cn_calibrated=False,
        automatic_cast_covered=False, state_hash=game.state_hash())
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
            ('waiting', waiting), ('replay', build_replay(game)), ('view', game.observe(1))):
        (output / f'v109-spell-match-representatives-{suffix}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
