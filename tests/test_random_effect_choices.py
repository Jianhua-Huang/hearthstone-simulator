"""Finite random branches share ordinary atomic execution and waiting frames."""
from dataclasses import dataclass
from functools import lru_cache
import unittest

from card_batch_testkit import CardBatchTestMixin
from hs_sim.engine import (CardClass, CardDefinition, CardMetadata, CardType, Game,
    PlayerSetup, Rarity, Registry, ResolutionError, Scenario, SnapshotError, TriggerSpec)
from hs_sim.engine.effects import ChoiceOption, Damage, Effect, InvokeBehavior, RequestChoice
from hs_sim.engine.random_effect_choices import ChooseRandomEffects
from hs_sim.engine.serialization import canonical_hash

P = 'random.effect.fixture.'
HERO, POWER, SPELL, WATCH = (P+x for x in ('hero', 'power', 'spell', 'watch'))
META = CardMetadata(False, (CardClass.MAGE,), Rarity.NONE, tribes=())


@dataclass(frozen=True)
class UnregisteredEffect(Effect):
    pass


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    registry = Registry(P+mode)
    registry.register_behavior(P+'empty', lambda c: ())
    registry.register_card(CardDefinition(HERO, HERO, CardType.HERO, health=30, metadata=META))
    registry.register_card(CardDefinition(POWER, POWER, CardType.HERO_POWER,
        on_use=P+'empty', metadata=META))

    def fail(c):
        raise ResolutionError('Random branch fixture failure')

    registry.register_behavior(P+'fail', fail)

    def body(c):
        own = c.state.players[c.player_id].hero_id
        enemy = c.state.players[3-c.player_id].hero_id
        first = (Damage(own, 1, c.source_id),)
        second = (Damage(enemy, 2, c.source_id),)
        if mode == 'unknown':
            second = (UnregisteredEffect(),)
        if mode == 'fail':
            first = second = (Damage(own, 3, c.source_id), InvokeBehavior(P+'fail', c.source_id, c.player_id))
        request = ChooseRandomEffects(c.player_id, c.source_id,
            (ChoiceOption('one', 'One', first), ChoiceOption('two', 'Two', second)))
        if mode == 'prewait':
            return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue', (request,)),), c.source_id),)
        return (request,)

    def watch(c):
        if mode == 'wait' and dict(c.event.data).get('producer') == 'effect_branch':
            return (RequestChoice(c.event.player_id, (ChoiceOption('continue', 'Continue'),), c.source_id),)
        return ()

    registry.register_behavior(P+'body', body)
    registry.register_behavior(P+'watch', watch)
    registry.register_card(CardDefinition(SPELL, SPELL, CardType.SPELL, on_play=P+'body', metadata=META))
    registry.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=10, metadata=META,
        triggers=(TriggerSpec('random_choice', P+'watch'),)))
    registry.validate()
    return registry


def typed_fields(value):
    if isinstance(value, dict):
        if value.get('type', '').endswith('.ChooseRandomEffects'):
            yield value['fields']
        for child in value.values():
            yield from typed_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from typed_fields(child)


class RandomEffectChoiceTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode='normal', player=1, seed=7):
        self.mode = mode
        players = tuple(PlayerSetup(HERO, hero_power_card_id=POWER,
            hand=(SPELL,) if p == player else (), board=(WATCH,) if p == player and mode == 'wait' else (),
            mana=10, max_mana=10) for p in (1, 2))
        return Game.from_scenario(Scenario(players, active_player=player, seed=seed), fixture(mode))

    def health(self, game):
        return tuple(game.state.entities[game.state.players[p].hero_id].health for p in (1, 2))

    def test_structural_contract_rejects_mutable_empty_duplicate_and_invalid_source(self):
        option = ChoiceOption('one', 'One')
        for arguments in ((True, 1, (option,)), (1, 0, (option,)), (1, 1, []),
                (1, 1, ()), (1, 1, (option, option)), (1, 1, ('bad',))):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                ChooseRandomEffects(*arguments)

    def test_one_outcome_only_and_original_second_player_ownership(self):
        for player in (1, 2):
            with self.subTest(player=player):
                game = self.game(player=player); self.play(game, SPELL, player=player)
                choices = [event for event in game.events if dict(event.data).get('producer') == 'effect_branch']
                self.assertEqual(len(choices), 1)
                self.assertEqual(choices[0].player_id, player)
                selected = dict(choices[0].data)['selected']
                expected = [30, 30]; expected[player-1 if selected == 'one' else 2-player] -= 1 if selected == 'one' else 2
                self.assertEqual(self.health(game), tuple(expected))

    def test_unselected_unknown_instruction_is_rejected_and_whole_action_rolls_back(self):
        game = self.game('unknown'); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, SPELL)
        self.assertEqual(game.snapshot(), saved)

    def test_selected_late_failure_rolls_back_prior_damage_and_rng(self):
        game = self.game('fail'); saved = game.snapshot()
        with self.assertRaises(ResolutionError):
            self.play(game, SPELL)
        self.assertEqual(game.snapshot(), saved)

    def test_selection_is_frozen_across_notification_wait_restore_clone_and_replay(self):
        game = self.game('wait'); self.play(game, SPELL)
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(self.health(game), (30, 30))
        selected_rng = game._rng.getstate()
        restored = self.portable(game)
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
        self.assertEqual(game._rng.getstate(), selected_rng)
        self.assertIn(self.health(game), ((29, 30), (30, 28)))

    def test_queued_request_restores_before_sampling_and_rejects_unallocated_source(self):
        game = self.game('prewait'); self.play(game, SPELL)
        restored = self.portable(game)
        saved = game.snapshot(); nodes = list(typed_fields(saved)); self.assertEqual(len(nodes), 1)
        nodes[0]['source_id'] = 999999
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaises(SnapshotError):
            Game.from_snapshot(saved, fixture('prewait'))
        self.choose(game); self.choose(restored)
        self.assertEqual(restored.snapshot(), game.snapshot())
