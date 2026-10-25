"""Observed two Chains leases and the affected existing lifecycle boundaries."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import unittest

from hs_sim.cards import build_registry
from hs_sim.engine import (CardDefinition, CardType, EndTurn, Game, PlayerSetup,
    Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.effects import (ChangeControl, ChoiceOption, CopyMinion,
    Destroy, InvokeBehavior, RemoveEnchantment, RequestChoice, ReturnToHand, Silence,
    Transform)
from hs_sim.engine.errors import ResolutionError
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION
from hs_sim.engine.serialization import canonical_hash
from hs_sim.targets import canonical_digest
from card_batch_testkit import CardBatchTestMixin

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/support/overlapping-control-observation-v1.json'
PIN = 'a9ebe100bb6e44a824c28e9d53bdae67421c361f5cd9d3ac80d004adf004e549'
CHAINS, BODY, STEED = 'CATA_496', 'TLC_603', 'CAP_800'
P = 'fixture.overlapping_control.'


@lru_cache(maxsize=1)
def packet():
    value = json.loads(DATA.read_text(encoding='utf-8'))
    if canonical_digest(value) != PIN:
        raise ValueError('Observed control packet changed')
    for row in value['records']:
        if canonical_digest(row['record']) != row['record_sha256']:
            raise ValueError('Incomplete control source record')
    return value


def leases(entity):
    return tuple(e for e in entity.enchantments if e.control_return_player_id is not None)


@lru_cache(maxsize=None)
def fixture(mode=None, role='writer'):
    if mode is not None or role not in ('writer', 'independent-reader'):
        raise ValueError('Unknown observed control fixture')
    packet()
    r = build_registry()

    def fail(c):
        raise ResolutionError('Observed control deliberate late failure')

    def remove_first(c):
        return (RemoveEnchantment(c.target_id, leases(c.state.entities[c.target_id])[0].id),)

    def reuse_source(c):
        return (ChangeControl(c.target_id, c.player_id,
            source_id=leases(c.state.entities[c.target_id])[0].source_id,
            until_previous_controller_turn_end=True),)

    scripts = {
        'remove_first': remove_first,
        'copy': lambda c: (CopyMinion(c.target_id, c.player_id),),
        'bounce': lambda c: (ReturnToHand(c.target_id),),
        'face': lambda c: (Transform(c.target_id, P + 'plain'),),
        'kill': lambda c: (Destroy(c.target_id, c.source_id),),
        'silence': lambda c: (Silence(c.target_id),),
        'global': lambda c: (ChangeControl(c.target_id, c.player_id,
            source_id=c.source_id, until_end_of_turn=True),),
        'third': lambda c: (ChangeControl(c.target_id, 3 - c.player_id,
            source_id=c.source_id, until_previous_controller_turn_end=True),),
        'reuse': reuse_source,
        'reverse_mixed': lambda c: (
            ChangeControl(c.target_id, 3 - c.player_id,
                source_id=c.source_id, until_end_of_turn=True),
            ChangeControl(c.target_id, c.player_id,
                source_id=c.target_id, until_previous_controller_turn_end=True)),
    }
    r.register_behavior(P + 'fail', fail)
    for name, body in scripts.items():
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.SPELL,
            on_play=P + name, requires_target=True))
    r.register_card(CardDefinition(P + 'plain', 'Different incarnation',
        CardType.MINION, attack=1, health=4))

    def observed_target(c):
        return next((e for e in c.state.entities.values() if e.card_id == BODY
            and e.zone == Zone.BOARD and e.owner == 2), None)

    def wait_first(c):
        target = observed_target(c)
        if c.event.player_id != 2 or target is None or len(leases(target)) != 2:
            return ()
        return waiting(c)

    def waiting(c):
        return (RequestChoice(1, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('bad', 'Fail', (InvokeBehavior(P + 'fail', c.source_id, 1),))),
            c.source_id),)

    def control_event(c):
        target = c.state.entities.get(c.event.target_id)
        return target if target is not None and target.card_id == BODY else None

    def fail_second(c):
        target = control_event(c)
        return (InvokeBehavior(P + 'fail', c.source_id, c.player_id),) if (
            target is not None and len(leases(target)) == 2) else ()

    def wait_return(c):
        target = control_event(c)
        return waiting(c) if (target is not None and target.controller == 1
            and not leases(target)) else ()

    for name, kind, body in (
        ('wait_first', 'turn_ended', wait_first),
        ('fail_second', 'control_changed', fail_second),
        ('wait_return', 'control_changed', wait_return),
    ):
        r.register_behavior(P + name, body)
        r.register_card(CardDefinition(P + name, name, CardType.MINION,
            health=8, triggers=(TriggerSpec(kind, P + name),)))
    r._version = 'observed-two-owner-end-control-v1'
    r.validate()
    r.freeze()
    return r


class OverlappingControlObservationTests(CardBatchTestMixin, unittest.TestCase):
    registry_factory = staticmethod(fixture)

    def game(self, *, original=2, card=BODY, extra=(), watcher=None):
        self.mode = None
        players = []
        for p in (1, 2):
            hand = (card, CHAINS, *extra) if p == original else (CHAINS,)
            players.append(PlayerSetup('HERO_07', hand=hand,
                board=(P + watcher,) if p == 1 and watcher else (),
                deck=('CORE_CS2_179',) * 10, mana=10, max_mana=10))
        return Game.from_scenario(Scenario(tuple(players), active_player=original,
            seed=5371), fixture())

    def end(self, g):
        g.apply(EndTurn(g.state.active_player))

    def first(self, g, *, original=2, card=BODY):
        target = self.play(g, card, player=original)
        self.end(g)
        source = self.play(g, CHAINS, target, player=3 - original)
        return target, source, leases(g.state.entities[target])[0]

    def doubled(self, g, *, original=2, card=BODY):
        target, first, old = self.first(g, original=original, card=card)
        self.end(g)
        second = self.play(g, CHAINS, target, player=original)
        return target, first, second, old

    def assert_private(self, g):
        for p in (1, 2):
            view = json.dumps(g.for_player(p).observe())
            for field in ('control_return_player_id', 'control_return_expiry',
                          'created_owner_turn_id', 'resolution_frame', 'rng_state'):
                self.assertNotIn('"' + field + '"', view)

    def test_observed_native_double_chain_keeps_both_sources_and_distinct_expiries(self):
        for original in (2, 1):
            with self.subTest(original=original):
                g = self.game(original=original)
                target, first, second, old = self.doubled(g, original=original)
                both = leases(g.state.entities[target])
                self.assertEqual(len(both), 2)
                self.assertEqual(both[0], old)
                self.assertEqual(tuple(x.source_id for x in both), (first, second))
                self.assertEqual(tuple(x.control_return_player_id for x in both),
                                 (original, 3 - original))
                self.assertNotEqual(both[0].id, both[1].id)
                self.assertTrue(all(x.control_return_expiry is not None for x in both))
                self.assertEqual((g.state.players[original].mana,
                    g.state.entities[first].zone, g.state.entities[second].zone),
                    (8, Zone.GRAVEYARD, Zone.GRAVEYARD))
                changes = sum(e.kind == 'control_changed' for e in g.events)
                self.end(g)
                self.assertEqual(g.state.entities[target].controller, original)
                self.assertEqual(leases(g.state.entities[target]), (both[1],))
                self.assertEqual(sum(e.kind == 'control_changed' for e in g.events), changes)
                self.end(g)
                self.assertEqual(g.state.entities[target].controller, 3 - original)
                self.assertEqual(leases(g.state.entities[target]), ())
                self.assertEqual(sum(e.kind == 'control_changed' for e in g.events), changes + 1)
                self.assert_private(g)

    def test_source_window_distinguishes_expiry_from_other_minion_combat(self):
        data = packet()
        self.assertEqual(len(data['events']), 749)
        self.assertEqual(data['source_observation']['metadata']['metadata'],
            dict(BuildNumber=254477, GameType='GT_VS_FRIEND',
                 FormatType='FT_STANDARD', ScenarioID=2))
        changes = [e['value'] for e in data['events'] if e.get('tag') == 'CONTROLLER'
            and e.get('entity', {}).get('entity_id') == 39]
        self.assertEqual(changes, [1, 2, 1])
        attacks = [e for e in data['events'] if e.get('block_type') == 'ATTACK']
        self.assertEqual([(e['entity']['entity_id'], e['target']['entity_id']) for e in attacks], [(16, 66)])
        for attachment, source in ((85, 10), (87, 35)):
            self.assertTrue(any(e.get('tag') == 'CREATOR' and e.get('value') == source
                and e.get('entity', {}).get('entity_id') == attachment for e in data['events']))
        self.assertFalse(data['source_observation']['target_build_255026_matched'])
        self.assertTrue(data['source_observation']['not_full_game'])

    def test_each_boundary_restores_replays_and_continues_from_independent_registry(self):
        g = self.game()
        target, _, _, _ = self.doubled(g)
        for expected in (2, 1):
            restored = self.portable(g)
            self.end(g)
            self.end(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(g.state.entities[target].controller, expected)
        self.assert_private(g)

    def test_first_expiry_wait_keeps_both_until_choice_and_bad_choice_rolls_back(self):
        g = self.game(watcher='wait_first')
        target, _, _, _ = self.doubled(g)
        self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual(len(leases(g.state.entities[target])), 2)
        restored = self.portable(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late failure'):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(len(leases(g.state.entities[target])), 1)
        self.end(g)
        self.end(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())
        self.assertEqual(g.state.entities[target].controller, 1)

    def test_second_expiry_return_choice_restores_after_only_its_lease_is_removed(self):
        g = self.game(watcher='wait_return')
        target, _, _, _ = self.doubled(g)
        self.end(g)
        self.end(g)
        self.assertIsNotNone(g.state.pending_choice)
        self.assertEqual((g.state.entities[target].controller, leases(g.state.entities[target])), (1, ()))
        restored = self.portable(g)
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'bad')
        self.assertEqual(g.snapshot(), saved)
        self.choose(g)
        self.choose(restored)
        self.assertEqual(g.snapshot(), restored.snapshot())

    def test_second_install_failure_rolls_back_first_lease_payment_and_allocation(self):
        g = self.game(watcher='fail_second')
        target, _, old = self.first(g)
        self.end(g)
        saved = g.snapshot()
        with self.assertRaisesRegex(ResolutionError, 'deliberate late failure'):
            self.play(g, CHAINS, target, player=2)
        self.assertEqual(g.snapshot(), saved)
        self.assertEqual(leases(g.state.entities[target]), (old,))

    def test_old_lease_manual_removal_does_not_remove_new_return(self):
        g = self.game(extra=(P + 'remove_first',))
        target, _, _, _ = self.doubled(g)
        newer = leases(g.state.entities[target])[1]
        self.play(g, P + 'remove_first', target, player=2)
        self.assertEqual((g.state.entities[target].controller, leases(g.state.entities[target])), (2, (newer,)))
        self.end(g)
        self.end(g)
        self.assertEqual(g.state.entities[target].controller, 1)

    def test_copy_and_incarnation_resets_keep_existing_physical_return_policy(self):
        for operation in ('copy', 'bounce', 'face', 'silence', 'kill'):
            with self.subTest(operation=operation):
                g = self.game(extra=(P + operation,))
                target, _, _, _ = self.doubled(g)
                self.play(g, P + operation, target, player=2)
                if operation == 'copy':
                    copies = [e for e in g.state.entities.values() if e.card_id == BODY
                        and e.zone == Zone.BOARD and e.id != target]
                    self.assertEqual(len(copies), 1)
                    self.assertEqual(leases(copies[0]), ())
                    self.assertEqual(len(leases(g.state.entities[target])), 2)
                elif operation == 'kill':
                    self.assertEqual(g.state.entities[target].zone, Zone.GRAVEYARD)
                    self.assertEqual(len(leases(g.state.entities[target])), 2)
                    frozen = next(r for r in g.state.death_history if r.entity_id == target)
                    self.assertEqual(len(leases(frozen)), 2)
                else:
                    self.assertEqual(leases(g.state.entities[target]), ())
                self.end(g)
                self.end(g)
                self.assertEqual(g.state.entities[target].controller, 1 if operation == 'copy' else 2)
                if operation == 'kill':
                    self.assertEqual(leases(g.state.entities[target]), ())
                    self.assertEqual(len(leases(frozen)), 2)

    def test_full_health_reborn_retains_both_original_deadlines(self):
        g = self.game(card=STEED, extra=(P + 'kill',))
        target, _, _, _ = self.doubled(g, card=STEED)
        originals = leases(g.state.entities[target])
        self.play(g, P + 'kill', target, player=2)
        event = next(e for e in reversed(g.events) if e.kind == 'minion_reborn' and e.source_id == target)
        new_id = event.target_id
        copied = leases(g.state.entities[new_id])
        self.assertEqual(tuple((e.source_id, e.control_return_player_id, e.control_return_expiry) for e in copied),
            tuple((e.source_id, e.control_return_player_id, e.control_return_expiry) for e in originals))
        self.assertTrue(set(e.id for e in originals).isdisjoint(e.id for e in copied))
        restored = self.portable(g)
        for expected in (2, 1):
            self.end(g)
            self.end(restored)
            self.assertEqual(g.snapshot(), restored.snapshot())
            self.assertEqual(g.state.entities[new_id].controller, expected)

    def test_unobserved_third_mixed_and_reused_sources_stay_rejected_atomically(self):
        for operation in ('third', 'global', 'reuse', 'reverse_mixed'):
            g = self.game(extra=(P + operation,))
            if operation == 'reverse_mixed':
                target = self.play(g, BODY, player=2)
            elif operation == 'third':
                target, _, _, _ = self.doubled(g)
            else:
                target, _, _ = self.first(g)
                self.end(g)
            saved = g.snapshot()
            with self.subTest(operation=operation), self.assertRaisesRegex(ResolutionError, 'Overlapping temporary control'):
                self.play(g, P + operation, target, player=2)
            self.assertEqual(g.snapshot(), saved)

    def test_previous_core_is_rejected_with_current_schema_and_valid_hashes(self):
        g = self.game()
        self.doubled(g)
        saved = deepcopy(g.snapshot())
        self.assertEqual(saved['mechanics_version']['version'], CORE_EFFECTS_VERSION)
        saved['mechanics_version']['version'] = 'core-effects-v731'
        saved['events_hash'] = canonical_hash(saved['events'])
        saved['state_hash'] = canonical_hash({k: v for k, v in saved.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        with self.assertRaisesRegex(SnapshotError, 'Mechanics version mismatch'):
            Game.from_snapshot(saved, fixture(None, 'independent-reader'))


if __name__ == '__main__':
    unittest.main()
