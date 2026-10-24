"""A reported native Steed/Chains/Soldier case over shared Reborn lifecycle."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, Keyword,
                          PlayerSetup, Scenario, SelectChoice, SnapshotError,
                          TriggerSpec, Zone)
from hs_sim.engine.effects import (ChoiceOption, CopyMinion, GrantKeyword,
                                   InvokeBehavior, RequestChoice, Silence)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.serialization import canonical_hash, SNAPSHOT_SCHEMA_VERSION
from hs_sim.targets import canonical_digest
from card_batch_testkit import CardBatchTestMixin

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/support/retained-reborn-control-v1.json'
PIN = 'bf98c1d1ef3c9f6495e51120b3db3f8881d4be61ff5a00afedbdd3d8e2d0dd9b'
STEED, CHAINS, SOLDIER = 'CAP_800', 'CATA_496', 'CATA_725t'
SPIRIT, CROCOLISK, WISP = 'CAP_803', 'CS2_120', 'EDR_851t'
P = 'fixture.retained_control.'


@lru_cache(maxsize=1)
def packet():
    result = json.loads(DATA.read_text(encoding='utf-8'))
    if canonical_digest(result) != PIN:
        raise ValueError('Retained-control source packet changed')
    if tuple(r['record']['id'] for r in result['records']) != (STEED, CHAINS, SOLDIER):
        raise ValueError('Reported native source set changed')
    for row in result['records']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise ValueError('Complete real card source changed')
    return result


@lru_cache(maxsize=None)
def fixture(mode=None, role='writer'):
    if mode not in (None, 'reborn_wait', 'end_wait', 'return_fail'):
        raise ValueError('Unknown retained-control fixture')
    packet()
    registry = build_registry()
    registry.register_behavior(P + 'copy', lambda c: (CopyMinion(c.target_id, c.player_id),))
    registry.register_behavior(P + 'silence', lambda c: (Silence(c.target_id),))
    registry.register_behavior(P + 'gift', lambda c: (GrantKeyword(c.target_id, Keyword.REBORN,
        c.source_id, reborn_policy='full_health_enchantments'),))
    for name in ('copy', 'silence', 'gift'):
        registry.register_card(CardDefinition(P + name, name, CardType.SPELL,
            on_play=P + name, requires_target=True))

    def fail(context):
        raise ResolutionError('Retained-control deliberate late failure')

    def watch(context):
        event = context.event
        if mode == 'reborn_wait':
            if event.kind != 'minion_reborn' or context.state.entities[event.target_id].card_id != STEED:
                return ()
        elif mode == 'end_wait':
            if event.kind != 'turn_ended' or event.player_id != 2:
                return ()
        elif mode == 'return_fail':
            target = context.state.entities.get(event.target_id)
            if event.kind == 'control_changed' and target is not None and (
                    target.card_id, target.owner, target.controller) == (STEED, 1, 2):
                return (InvokeBehavior(P + 'fail', context.source_id, context.player_id),)
            return ()
        else:
            return ()
        return (RequestChoice(1, (ChoiceOption('ok', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', context.source_id, 1),))),
            context.source_id),)

    registry.register_behavior(P + 'fail', fail)
    registry.register_behavior(P + 'watch', watch)
    kinds = ('minion_reborn',) if mode == 'reborn_wait' else (
        'turn_ended',) if mode == 'end_wait' else ('control_changed',)
    registry.register_card(CardDefinition(P + 'watch', 'Lifecycle observer', CardType.MINION,
        health=8, triggers=tuple(TriggerSpec(k, P + 'watch') for k in kinds)))
    registry._version = 'retained-reborn-control-v1-' + str(mode)
    registry.validate()
    registry.freeze()
    return registry


def marker(entity):
    return next((e for e in entity.enchantments if e.control_return_player_id is not None), None)


def rehash(snapshot):
    snapshot['events_hash'] = canonical_hash(snapshot['events'])
    snapshot['state_hash'] = canonical_hash({k: v for k, v in snapshot.items()
        if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
    return snapshot


class RetainedRebornControlTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, mode=None, card=STEED, hand=(), enemy_hand=()):
        self.mode = mode
        board = (SOLDIER,) if mode is None else (P + 'watch', SOLDIER)
        return Game.from_scenario(Scenario((
            PlayerSetup('HERO_07', board=board, hand=(*hand, CHAINS),
                deck=('CORE_CS2_182',) * 8, mana=10, max_mana=10),
            PlayerSetup('HERO_11', board=(card,), hand=enemy_hand,
                deck=('CORE_CS2_182',) * 8, mana=10, max_mana=10)), seed=5321), fixture(mode, 'writer'))

    def steal(self, game, card=STEED):
        target = self.entity(game, card, player=2, zone='board').id
        source = self.play(game, CHAINS, target)
        current = game.state.entities[target]
        self.assertEqual(current.controller, 1)
        self.assertEqual(game.state.players[1].mana, 8)
        self.assertEqual(game.state.entities[source].zone, Zone.GRAVEYARD)
        self.assertEqual(marker(current).source_id, source)
        return target, marker(current)

    def newborn(self, game, original):
        event = next(e for e in reversed(game.events)
            if e.kind == 'minion_reborn' and e.source_id == original)
        return game.state.entities[event.target_id]

    def assert_retained(self, game, original, old_marker):
        body = self.newborn(game, original)
        current = marker(body)
        self.assertIsNotNone(current)
        self.assertNotEqual(body.id, original)
        self.assertNotEqual(current.id, old_marker.id)
        self.assertEqual((current.source_id, current.control_return_player_id,
                          current.control_return_expiry, current.expires_turn),
                         (old_marker.source_id, 2, old_marker.control_return_expiry, old_marker.expires_turn))
        self.assertEqual((body.controller, body.health), (1, body.max_health))
        self.assertNotIn(Keyword.REBORN, body.keywords)
        self.assertEqual(game.state.entities[original].zone, Zone.GRAVEYARD)
        for player in (1, 2):
            view = json.dumps(game.for_player(player).observe())
            self.assertNotIn('control_return_player_id', view)
            self.assertNotIn('control_return_expiry', view)
        return body.id

    def test_reported_native_soldier_sacrifice_returns_reborn_steed_on_original_clock(self):
        game = self.game()
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        self.assertEqual(game.state.active_player, 2)
        restored = self.portable(game)
        for candidate in (game, restored):
            candidate.apply(EndTurn(2))
            self.assertEqual(candidate.state.entities[new_id].controller, 2)
            self.assertIsNone(marker(candidate.state.entities[new_id]))
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)

    def test_existing_granted_full_health_policy_retains_same_deadline_on_other_native_minion(self):
        game = self.game(card=CROCOLISK, hand=(P + 'gift',))
        target = self.entity(game, CROCOLISK, player=2, zone='board').id
        self.play(game, P + 'gift', target)
        original, lease = self.steal(game, CROCOLISK)
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[new_id].controller, 2)
        self.portable(game)

    def test_ordinary_reborn_does_not_inherit_return_obligation(self):
        game = self.game(card=SPIRIT)
        original, _ = self.steal(game, SPIRIT)
        game.apply(EndTurn(1))
        body = self.newborn(game, original)
        self.assertEqual((body.controller, body.health), (1, 1))
        self.assertIsNone(marker(body))
        new_id = body.id
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[new_id].controller, 1)
        self.portable(game)

    def test_current_copy_still_excludes_physical_return_while_original_reborn_keeps_it(self):
        game = self.game(hand=(P + 'copy',))
        original, lease = self.steal(game)
        self.play(game, P + 'copy', original)
        copied_id = game.state.players[1].board[-1]
        self.assertNotEqual(copied_id, original)
        self.assertIsNone(marker(game.state.entities[copied_id]))
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[new_id].controller, 2)
        self.assertEqual(game.state.entities[copied_id].controller, 1)
        self.portable(game)

    def test_silencing_reborn_body_returns_it_once_without_waiting_for_deadline(self):
        game = self.game(enemy_hand=(P + 'silence',))
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        before = len([e for e in game.events if e.kind == 'control_changed' and e.target_id == new_id])
        self.play(game, P + 'silence', new_id, player=2)
        self.assertEqual(game.state.entities[new_id].controller, 2)
        self.assertIsNone(marker(game.state.entities[new_id]))
        game.apply(EndTurn(2))
        changes = [e for e in game.events if e.kind == 'control_changed' and e.target_id == new_id]
        self.assertEqual(len(changes), before + 1)
        self.portable(game)

    def test_reborn_choice_preserves_deadline_and_failure_rolls_back_before_continuing_restored(self):
        game = self.game('reborn_wait')
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        self.assertIsNotNone(game.state.pending_choice)
        new_id = self.assert_retained(game, original, lease)
        saved = game.snapshot()
        choice = game.state.pending_choice
        with self.assertRaisesRegex(ResolutionError, 'deliberate late failure'):
            game.apply(SelectChoice(1, choice.id, ('bad',)))
        self.assertEqual(game.snapshot(), saved)
        restored = self.portable(game)
        for candidate in (game, restored):
            self.choose(candidate, 'ok')
            candidate.apply(EndTurn(2))
            self.assertEqual(candidate.state.entities[new_id].controller, 2)
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)

    def test_original_owner_end_choice_restores_then_expires_return_once(self):
        game = self.game('end_wait')
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        game.apply(EndTurn(2))
        self.assertIsNotNone(game.state.pending_choice)
        self.assertEqual(game.state.entities[new_id].controller, 1)
        restored = self.portable(game)
        for candidate in (game, restored):
            self.choose(candidate, 'ok')
            self.assertEqual(candidate.state.entities[new_id].controller, 2)
            self.assertIsNone(marker(candidate.state.entities[new_id]))
        self.assertEqual(game.snapshot(), restored.snapshot())
        self.portable(game)

    def test_late_return_failure_rolls_back_complete_original_end_action(self):
        game = self.game('return_fail')
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        self.assert_retained(game, original, lease)
        before = game.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late failure'):
            game.apply(EndTurn(2))
        self.assertEqual(game.snapshot(), before)
        self.portable(game)

    def test_full_destination_uses_existing_death_path_without_reborn_again(self):
        game = self.game(enemy_hand=(WISP,) * 7)
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        new_id = self.assert_retained(game, original, lease)
        for _ in range(7):
            self.play(game, WISP, player=2)
        self.assertEqual(len(game.state.players[2].board), 7)
        game.apply(EndTurn(2))
        self.assertEqual(game.state.entities[new_id].zone, Zone.GRAVEYARD)
        self.assertEqual(len([e for e in game.events if e.kind == 'minion_reborn']), 1)
        self.portable(game)

    def test_old_core_signature_is_rejected_even_with_current_structural_schema_and_valid_hashes(self):
        game = self.game()
        original, lease = self.steal(game)
        game.apply(EndTurn(1))
        self.assert_retained(game, original, lease)
        saved = deepcopy(game.snapshot())
        self.assertEqual(saved['schema_version'], SNAPSHOT_SCHEMA_VERSION)
        self.assertEqual(saved['mechanics_version']['version'], 'core-effects-v730')
        saved['mechanics_version']['version'] = 'core-effects-v729'
        with self.assertRaisesRegex(SnapshotError, 'Mechanics version mismatch'):
            Game.from_snapshot(rehash(saved), fixture(None, 'independent-reader'))


if __name__ == '__main__':
    unittest.main()
