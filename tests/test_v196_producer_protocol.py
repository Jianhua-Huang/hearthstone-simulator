"""Unexecuted protocol checks for producer amounts and ordered-group wire state."""
from hs_sim.engine.serialization import SNAPSHOT_SCHEMA_VERSION
from copy import deepcopy
from pathlib import Path
import json
import os
import unittest

from hs_sim.engine import Game, PlayCard, PlayerSetup, Scenario, SelectChoice, SnapshotError
from hs_sim.engine.replay import build_replay, replay
from hs_sim.engine.serialization import canonical_hash
import test_v195_ordered_group_kernel as fixture
from hs_sim.engine.resolver import CORE_EFFECTS_VERSION


class ProducerProtocolTests(unittest.TestCase):
    def blob(self, value, label):
        directory = os.environ.get('V196_INPUT_DIR')
        if not directory:
            return
        root = Path(directory) / self._testMethodName
        root.mkdir(parents=True, exist_ok=True)
        self.counter = getattr(self, 'counter', 0) + 1
        value = value.snapshot() if hasattr(value, 'snapshot') else value
        (root / f'{self.counter:03d}-{label}.json').write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def game(self, waiting=False):
        g = Game.from_scenario(Scenario((
            PlayerSetup('hero', hand=('pq-grant', 'og-group'),
                        board=('og-watch',) if waiting else (), mana=10, max_mana=10,
                        deck=('red',) * 10),
            PlayerSetup('hero', mana=10, max_mana=10, deck=('blue',) * 10)),
            seed=196, generation_context=fixture.pending.CONTEXT), fixture.registry())
        self.blob(g, 'initial')
        if waiting:
            self.play(g, 'pq-grant'); self.play(g, 'og-group')
            self.assertIsNotNone(g.state.pending_choice)
            self.blob(g, 'waiting')
        return g

    def play(self, g, name):
        card = next(i for i in g.state.players[1].hand if g.state.entities[i].card_id == name)
        return g.apply(PlayCard(1, card))

    def choose(self, g):
        choice = g.state.pending_choice
        return g.apply(SelectChoice(choice.player_id, choice.id, ('ok',)))

    def rehash(self, value):
        value['events_hash'] = canonical_hash(value['events'])
        value['state_hash'] = canonical_hash({k: v for k, v in value.items()
            if k not in ('schema_version', 'events', 'events_hash', 'state_hash')})
        return value

    def test_current_wire_and_host_versions_are_bound_without_public_api_changes(self):
        g = self.game(); value = g.snapshot()
        self.assertEqual((value['schema_version'], g.ruleset.id, g.mechanics.version),
                         (SNAPSHOT_SCHEMA_VERSION, 'prototype-v302', CORE_EFFECTS_VERSION))
        self.assertEqual((value['state']['next_ordered_group_id'], value['state']['ordered_group_history']), (1, []))
        self.assertEqual(value['state']['pool_summon_history'], [])
        self.assertEqual(Game.from_snapshot(deepcopy(value), fixture.registry()).snapshot(), value)
        self.assertEqual(g.observe(1)['version'], 'player-view-v86')
        self.assertEqual(g.for_player(1).observe()['version'], 'player-actions-v12')
        self.assertEqual(build_replay(g)['schema_version'], 1)

    def test_every_former_snapshot_schema_is_rejected_before_state_decoding(self):
        value = self.game().snapshot(); registry = fixture.registry()
        for version in range(1, value['schema_version']):
            with self.subTest(version=version):
                bad = deepcopy(value); bad['schema_version'] = version
                bad['state'] = []  # The explicit legacy error must precede this malformed wire body.
                self.blob(bad, 'old-' + str(version))
                with self.assertRaisesRegex(SnapshotError, f"1 through {value['schema_version'] - 1} need their original engines"):
                    Game.from_snapshot(bad, registry)

    def test_exact_current_schema_rejects_type_aliases_unknown_versions_and_old_host_labels(self):
        value = self.game().snapshot()
        for version in (True, False, '111', 111.0, 0, -1, 112, value['schema_version'] + 1):
            with self.subTest(version=version):
                bad = deepcopy(value); bad['schema_version'] = version
                self.blob(bad, 'wrong-schema')
                if type(version) is int and version == value['schema_version']:
                    self.assertEqual(Game.from_snapshot(bad, fixture.registry()).snapshot(), bad)
                else:
                    with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture.registry())
        for label in ('ruleset', 'mechanics_version'):
            bad = deepcopy(value)
            if label == 'ruleset': bad[label]['id'] = 'prototype-v113'
            else: bad[label]['version'] = 'core-effects-v113'
            self.rehash(bad); self.blob(bad, 'old-' + label)
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture.registry())

    def test_new_group_waiting_wire_restores_and_continues_on_independent_registries(self):
        g = self.game(waiting=True); value = g.snapshot()
        root = value['state']['ordered_group_history'][0]
        self.assertEqual((value['schema_version'], root['producer_amount']['family']), (SNAPSHOT_SCHEMA_VERSION, 'ordered_group'))
        self.assertEqual((root['producer_amount']['base_count'], root['producer_amount']['total']), (3, 4))
        restored = (Game.from_snapshot(deepcopy(value), fixture.registry()), g.clone(),
                    replay(build_replay(g), fixture.registry()))
        self.choose(g); expected = g.snapshot(); self.blob(expected, 'continued')
        for other in restored:
            self.choose(other); self.assertEqual(other.snapshot(), expected)
        self.assertEqual(replay(build_replay(g), fixture.registry()).snapshot(), expected)

    def test_current_wire_cannot_silently_default_missing_group_fields_or_amount_family(self):
        value = self.game(waiting=True).snapshot()
        for key in ('next_ordered_group_id', 'ordered_group_history', 'amount-family'):
            bad = deepcopy(value)
            if key == 'amount-family': bad['state']['ordered_group_history'][0]['producer_amount'].pop('family')
            else: bad['state'].pop(key)
            self.rehash(bad); self.blob(bad, 'missing-' + key)
            with self.assertRaises(SnapshotError): Game.from_snapshot(bad, fixture.registry())

    def test_replay_v1_requires_a_current_origin_and_rejects_a_relabelled_legacy_origin(self):
        g = self.game(waiting=True); value = build_replay(g)
        self.assertEqual((value['schema_version'], value['origin']['schema_version']), (1, SNAPSHOT_SCHEMA_VERSION))
        self.assertEqual(replay(deepcopy(value), fixture.registry()).snapshot(), g.snapshot())
        bad = deepcopy(value); bad['origin']['schema_version'] = 110
        self.blob(bad, 'legacy-replay-origin')
        with self.assertRaisesRegex(ValueError, f"1 through {value['origin']['schema_version'] - 1} need their original engines"):
            replay(bad, fixture.registry())


if __name__ == '__main__':
    unittest.main()
