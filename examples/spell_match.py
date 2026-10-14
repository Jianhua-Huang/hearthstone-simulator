"""Synthetic A1 school/class, frozen quota and independent waiting replay."""
import argparse
import json
from pathlib import Path

from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayerSetup, RecipientMetadataFilter, Registry, RepeatMatchSpec, Scenario,
    SpellRepeatSpec, SpellSchool)
from hs_sim.engine.effects import ChoiceOption, Destroy, GainArmor, RequestChoice
from hs_sim.engine.spell_modifiers import AddSpellRepeatModifier
from hs_sim.engine.replay import build_replay, replay
from examples.battlecry_activations import submit


def build_registry():
    registry = Registry('spell-match-example-v1')
    for cid, hero_class in (('hero.one', CardClass.WARRIOR), ('hero.two', CardClass.MAGE)):
        registry.register_card(CardDefinition(cid, cid, CardType.HERO, health=30,
            metadata=CardMetadata(False, (hero_class,), None)))
    match = RepeatMatchSpec(RecipientMetadataFilter(spell_schools=(SpellSchool.ARCANE,)))
    registry.register_card(CardDefinition('aura', 'Arcane other-class quota', CardType.MINION,
        health=5, spell_repeats=(SpellRepeatSpec(3, 'other', match),)))
    registry.register_behavior('grant', lambda c: [AddSpellRepeatModifier(
        c.player_id, SpellRepeatSpec(2, 'any', match), source_id=c.source_id, uses=2)])
    registry.register_card(CardDefinition('policy', 'Arcane player quota', CardType.MINION,
        cost=1, health=4, battlecry='grant'))

    def arcane(context):
        carrier = next(e.id for e in context.state.entities.values() if e.card_id == 'aura')
        return [RequestChoice(context.player_id, (
            ChoiceOption('resolve', 'Gain armor and remove the source', (
                GainArmor(context.player_id, 1), Destroy(carrier, context.source_id))),),
            source_id=context.source_id, repeat_key='branch')]

    registry.register_behavior('arcane', arcane)
    registry.register_behavior('fire', lambda c: [GainArmor(c.player_id, 3)])
    for cid, school in (('arcane', SpellSchool.ARCANE), ('fire', SpellSchool.FIRE)):
        registry.register_card(CardDefinition(cid, cid, CardType.SPELL, cost=1,
            spell_school=school, on_play=cid, metadata=CardMetadata(False, (CardClass.MAGE,), None)))
    return registry


def run():
    game = Game.from_scenario(Scenario((
        PlayerSetup('hero.one', hand=('policy', 'arcane', 'fire', 'arcane'),
            board=('aura',), mana=10, max_mana=10), PlayerSetup('hero.two')), seed=108), build_registry())
    waiting = []
    submit(game, 'play_card', 'policy')
    submit(game, 'play_card', 'arcane')
    assert game.state.pending_choice is not None
    waiting.append(game.snapshot())
    branches = (game, game.clone(), Game.from_snapshot(json.loads(json.dumps(waiting[0])), build_registry()))
    for match in branches:
        submit(match, 'select_choice')
        assert match.state.entities[match.state.players[1].hero_id].armor == 3
        assert match.state.players[1].spell_modifiers[0].uses_remaining == 1
        submit(match, 'play_card', 'fire')
        assert match.state.players[1].spell_modifiers[0].uses_remaining == 1
        submit(match, 'play_card', 'arcane')
        assert match.state.pending_choice is not None
    assert all(match.snapshot() == game.snapshot() for match in branches)
    waiting.append(game.snapshot())
    final_branches = (*branches, Game.from_snapshot(json.loads(json.dumps(waiting[1])), build_registry()))
    for match in final_branches:
        submit(match, 'select_choice')
        roots = [p for p in match.state.play_history if p.kind == CardType.SPELL]
        assert [p.spell_payload.casts for p in roots] == [3, 1, 2]
        assert all(p.spell_acceptance_closed for p in roots)
        assert [len(p.spell_payload.contributors) for p in roots] == [1, 0, 0]
        assert [len(p.spell_submission.modifiers) for p in roots] == [1, 0, 1]
        assert match.state.players[1].spell_modifiers == []
        assert match.state.entities[match.state.players[1].hero_id].armor == 8
    assert all(match.snapshot() == game.snapshot() for match in final_branches)
    for snapshot in waiting:
        restored = Game.from_snapshot(json.loads(json.dumps(snapshot)), build_registry())
        assert restored.snapshot() == replay(build_replay(restored), build_registry()).snapshot()
    assert replay(build_replay(game), build_registry()).snapshot() == game.snapshot()
    return game, waiting


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--replay')
    args = parser.parse_args()
    if args.replay:
        game = replay(json.loads(Path(args.replay).read_text(encoding='utf-8')), build_registry())
        print(json.dumps(dict(replayed=True, actions=len(game.history), state_hash=game.state_hash())))
        return
    game, waiting = run()
    output = Path(__file__).resolve().parents[1] / 'outputs'
    summary = dict(actions=len(game.history), events=len(game.events), state_hash=game.state_hash(),
        schema=game.snapshot()['schema_version'], casts=len(game.state.cast_history),
        accepted_quotas=[3, 1, 2], armor=8, choices=len(waiting), restored_and_replayed=True,
        synthetic_scenario=True, representative_cards_added=0)
    for suffix, value in (('summary', summary), ('snapshot', waiting[0]),
            ('waiting', waiting), ('replay', build_replay(game)), ('view', game.observe(1))):
        (output / f'v108-spell-match-{suffix}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__': main()
