"""Full local print qualification through the real Avatar/native pack entry."""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
import json
from pathlib import Path
from random import Random
import tempfile
import unittest
from unittest.mock import patch

from card_batch_testkit import CardBatchTestMixin
from hs_sim.cards import standard_pack_inventory as inventory
from hs_sim.cards.standard_pack_inventory import CARD, POOL_ID, load_batch
from hs_sim.engine import (CardDefinition, CardType, Game, PlayerSetup, ResolutionError,
    Scenario, SnapshotError, TriggerSpec, Zone)
from hs_sim.engine.card_packs import OPENED, STEP, FINISHED, pack_candidates
from hs_sim.engine.effects import ChoiceOption, InvokeBehavior, RequestChoice
from hs_sim.engine.pools import GenerationContext, sample_candidates
from hs_sim.engine.registry import UnsupportedDefinitionError
from hs_sim.launch_candidate_format import build_cn37_launch_candidate_format
from hs_sim.local_pool_format import build_cn37_local_pool_format, load_bindings
from hs_sim.targets import TargetValidationError, canonical_digest
from test_current_deck_empty_basics import rehash
from tools import card_batch as batch


P = 'k570.'
UNIT, WATCH, FAULT = (P + key for key in ('unit', 'watch', 'fault'))
# Chosen by pure RNG probing, always against all 997 original candidates.
RECIPES = {
    'TLC_100': (248, ('TLC_100', 'EDR_572', 'TIME_032', 'TLC_520', 'TIME_618')),
    'BE_042': (5637, ('BE_042', 'END_032', 'TLC_903', 'EDR_978', 'TIME_029')),
    'BE_000': (38931, ('BE_000', 'EDR_465', 'BE_565', 'CATA_161', 'EDR_469')),
    'CATA_301': (9726, ('CATA_301', 'TLC_600', 'BE_045', 'TIME_045', 'DINO_407')),
    'CATA_190h': (36690, ('CATA_190h', 'FIR_924', 'DINO_410', 'BE_151', 'TIME_720')),
}


@lru_cache(None)
def fixture(mode='normal', role='writer'):
    fmt = build_cn37_local_pool_format(); r = fmt.registry
    def fail(c):
        raise ResolutionError('k570 deliberate pack resume failure')
    def watch(c):
        entity = c.state.entities[c.event.target_id]
        if mode != 'wait' or entity.card_id in (CARD, WATCH):
            return ()
        return (RequestChoice(c.player_id, (ChoiceOption('continue', 'Continue'),
            ChoiceOption('fault', 'Fail', (InvokeBehavior(FAULT, c.source_id, c.player_id),))), c.source_id),)
    r.register_behavior(FAULT, fail); r.register_behavior(WATCH, watch)
    r.register_card(CardDefinition(UNIT, UNIT, CardType.MINION, attack=1, health=9))
    r.register_card(CardDefinition(WATCH, WATCH, CardType.MINION, health=20,
        triggers=(TriggerSpec('minion_summoned', WATCH),)))
    r.validate()
    if mode == 'missing':
        r._cards.pop('EDR_572')
    return r, fmt


class StandardPackInventoryTests(CardBatchTestMixin, unittest.TestCase):
    mode = 'normal'
    registry_factory = staticmethod(lambda mode, role: fixture(mode, role)[0])

    def game(self, recipe='TLC_100', *, mode='normal', hand=(), board=(), player=1):
        self.mode = mode; r, fmt = fixture(mode)
        own = PlayerSetup('HERO_03', hand=(CARD,) + hand,
            board=((WATCH,) if mode == 'wait' else ()) + board,
            deck=(UNIT,) * 8, mana=10, max_mana=10)
        other = PlayerSetup('HERO_08', deck=(UNIT,) * 8)
        players = (own, other) if player == 1 else (other, own)
        return Game.from_scenario(Scenario(players, active_player=player,
            seed=RECIPES[recipe][0], generation_context=fmt.context), r)

    def opening(self, g):
        return next(dict(event.data) for event in g.events if event.kind == OPENED)

    def assert_finished(self, g, recipe, player=1):
        expected = RECIPES[recipe][1]; data = self.opening(g)
        self.assertEqual(tuple(data['drawn']), expected)
        self.assertEqual(len(data['candidates']), 997)
        self.assertEqual(len([e for e in g.events if e.kind == STEP]), 5)
        self.assertEqual(len([e for e in g.events if e.kind == FINISHED]), 1)
        self.assertEqual(g.state.players[player].mana, 1)
        self.assertEqual(len(g.state.play_history), 1)
        self.assertEqual([b.payload.card_id for b in g.state.battlecry_history], [CARD])

    def test_all_1322_complete_source_rows_and_original_avatar_face_are_preserved(self):
        data = load_batch(); raw = {r['id']: r for r in batch.read(data['source'])}
        self.assertEqual(len(data['cards'] + data['existing_dependencies']), 1322)
        for key in ('cards', 'existing_dependencies'):
            for row in data[key]:
                self.assertEqual(row['record'], raw[row['record']['id']])
        for face in data['official_faces']:
            batch.check_face(raw[face['card_id']], face['face'], face['locale'])
        self.assertFalse(data['formal_pool_complete']); self.assertFalse(data['cn_calibrated'])
        for evidence in data['primary_evidence']:
            self.assertEqual(batch.sha(evidence['path']), evidence['sha256'])

    def test_complete_six_set_inventory_keeps_excluded_grants_and_all_five_kinds(self):
        r, fmt = fixture(); data = load_batch()
        pool, members = pack_candidates(r, fmt.context, r._standard_pack_profiles[CARD])
        self.assertEqual([m.card_id for m in pool.members], data['member_ids'])
        self.assertEqual(len(pool.members), 1012); self.assertTrue(pool.complete)
        self.assertEqual(list(pool.excluded_card_ids), data['excluded_card_ids'])
        self.assertEqual(len(pool.excluded_card_ids), 15)
        self.assertEqual([m.card_id for m in members], sorted(data['eligible_card_ids']))
        self.assertEqual({m.weight for m in pool.members}, {1})
        self.assertEqual(Counter(r.card(m.card_id).kind.value for m in members),
            Counter(minion=607, spell=336, weapon=32, location=21, hero=1))
        self.assertEqual(len({r.pool_card(m.card_id).generation_identity for m in members}), 997)

    def test_pack_qualification_distinguishes_normal_prints_cosmetics_and_inference(self):
        data = load_batch(); by_id = {a['card_id']: a for a in data['assessments']}
        self.assertEqual(by_id['TIME_003']['role'], 'explicit-not-in-expansion-pack')
        self.assertFalse(by_id['TIME_003']['inference'])
        self.assertEqual(by_id['TLC_468']['role'], 'normal-promotional-grant')
        self.assertTrue(by_id['TLC_468']['inference'])
        self.assertEqual(by_id['EDR_105']['role'], 'pack-candidate')
        self.assertFalse(by_id['EDR_105']['inference'])
        for cid in ('EDR_571', 'TLC_603', 'TIME_056', 'TIME_103'):
            self.assertIn(cid, data['eligible_card_ids'])
        self.assertEqual(len(data['class_set_member_ids']), 58)
        self.assertTrue(set(data['class_set_member_ids']) <= set(data['eligible_card_ids']))
        self.assertEqual(Counter(a['card_set_id'] for a in data['assessments']
            if a['role'].startswith('outside-pack-set')), Counter({1637: 289, 1941: 21}))
        self.assertTrue(any('local inference' in text for text in data['uncertainties']))

    def test_all_native_definitions_and_existing_alias_metadata_match_pinned_digests(self):
        r, _ = fixture(); data = load_batch()
        for row in data['assessments']:
            self.assertEqual(canonical_digest(asdict(r.card(row['card_id']))), row['definition_sha256'])
        self.assertEqual(r.pool_card('CORE_AT_037').metadata.deck_identity, 'AT_037')
        self.assertEqual(r.pool_card('CORE_AT_037').generation_identity, 'CORE_AT_037')
        self.assertIsNone(r.card('CATA_130').metadata.deck_identity)
        self.assertEqual(r.pool_card('CATA_130').generation_identity, 'CATA_130')

    def test_real_full_inventory_can_install_each_kind_without_child_hand_plays(self):
        for first in RECIPES:
            with self.subTest(first=first):
                g = self.game(first); self.play(g, CARD); self.assert_finished(g, first)
                player = g.state.players[1]; r = g.registry
                board = [g.state.entities[e].card_id for e in player.board]
                self.assertEqual(Counter(board), Counter((CARD,) + tuple(c for c in RECIPES[first][1]
                    if r.card(c).kind in (CardType.MINION, CardType.LOCATION))))
                self.assertIsNone(g.state.pending_choice)
                if first == 'BE_042':
                    self.assertEqual((g.state.entities[player.hero_id].attack,
                        g.state.entities[player.hero_id].armor), (4, 0))
                    self.assertEqual([(c.card_id, c.origin, c.completed) for c in g.state.cast_history], [('BE_042', 'effect', True)])
                elif first == 'BE_000':
                    self.assertEqual(g.state.entities[player.weapon_id].card_id, first)
                    self.assertEqual(g.state.entities[player.weapon_id].attack, r.card(first).attack)
                elif first == 'CATA_301':
                    self.assertEqual(self.entity(g, first, zone='board').durability, r.card(first).durability)
                elif first == 'CATA_190h':
                    self.assertEqual(g.state.entities[player.hero_id].card_id, first)
                    self.assertEqual(g.state.entities[player.hero_power_id].card_id, 'CATA_190p')
                    self.assertEqual(g.state.entities[player.hero_id].armor, 12)
                if first in ('BE_042', 'CATA_190h'):
                    self.portable(g)

    def test_full_hand_keeps_all_five_original_pack_occurrences(self):
        g = self.game(hand=(UNIT,) * 9); original_entries = len(g.state.hand_entries)
        self.play(g, CARD)
        self.assert_finished(g, 'TLC_100')
        self.assertEqual(len(g.state.players[1].hand), 9)
        self.assertEqual(len(g.state.players[1].board), 6)
        self.assertEqual(len(g.state.hand_entries), original_entries)

    def test_full_board_consumes_all_five_attempts_and_finishes(self):
        g = self.game(board=(UNIT,) * 6); self.play(g, CARD)
        self.assert_finished(g, 'TLC_100')
        self.assertEqual(len(g.state.players[1].board), 7)
        self.assertFalse(any(g.state.entities[i].card_id in RECIPES['TLC_100'][1]
            for i in g.state.players[1].board))

    def test_full_domain_acceptance_and_waiting_resume_preserve_rng_replay_and_atomicity(self):
        g = self.game(mode='wait'); initial = g._rng.getstate(); self.play(g, CARD)
        self.assertIsNotNone(g.state.pending_choice); restored = self.portable(g)
        data = self.opening(g); self.assertEqual(data['rng_before'], initial)
        r, fmt = fixture('wait'); _, members = pack_candidates(r, fmt.context, r._standard_pack_profiles[CARD])
        probe = Random(); probe.setstate(initial)
        self.assertEqual(sample_candidates(probe, members, 5, replacement=True), tuple(data['drawn']))
        self.assertEqual(data['rng_after'], probe.getstate())
        saved = g.snapshot()
        with self.assertRaises(ResolutionError):
            self.choose(g, 'fault')
        self.assertEqual(g.snapshot(), saved)
        for current in (g, restored):
            while current.state.pending_choice:
                self.choose(current)
            self.assert_finished(current, 'TLC_100')
            self.assertEqual(current._rng.getstate(), probe.getstate())
        self.assertEqual(g.snapshot(), restored.snapshot()); self.portable(g)

    def test_second_seat_uses_same_complete_pool_and_original_paid_source(self):
        g = self.game(player=2); self.play(g, CARD, player=2)
        self.assert_finished(g, 'TLC_100', 2)
        self.assertEqual(len(g.state.players[2].board), 6)
        self.assertFalse(g.state.players[1].board)
        self.portable(g)

    def test_missing_eligible_definition_is_an_error_without_cropping_inventory(self):
        g = self.game(mode='missing'); saved = g.snapshot()
        fmt = fixture('missing')[1]
        self.assertEqual(len(g.registry.pool(POOL_ID, fmt.context).members), 1012)
        with self.assertRaisesRegex((ResolutionError, UnsupportedDefinitionError), 'EDR_572'):
            self.play(g, CARD)
        self.assertEqual(g.snapshot(), saved)

    def test_private_full_pool_and_unplayed_order_do_not_enter_player_views(self):
        g = self.game(mode='wait'); self.play(g, CARD)
        for player in (1, 2):
            view = json.dumps(g.observe(player)) + json.dumps(g.player_events(player))
            for private in (OPENED, STEP, 'rng_before', 'opening_id', 'pool_version', 'excluded_card_ids'):
                self.assertNotIn(private, view)
            # Later, still unplayed identities remain in the private acceptance only.
            self.assertNotIn('TIME_618', view)

    def test_rehashed_original_domain_or_draw_mutation_rejects_with_full_local_registry(self):
        g = self.game(mode='wait'); self.play(g, CARD); saved = g.snapshot()
        for change in ('domain', 'weight', 'draw'):
            bad = deepcopy(saved); event = next(e for e in bad['events'] if e['kind'] == OPENED)
            if change == 'domain':
                event['data']['candidates'].pop()
            elif change == 'weight':
                event['data']['candidates'][0][1] += 1
            else:
                event['data']['drawn'][0] = 'TIME_003'
            with self.subTest(change=change), self.assertRaises(SnapshotError):
                Game.from_snapshot(rehash(bad), fixture('wait', 'independent-reader')[0])

    def test_source_manifest_changes_reject_and_original_launch_has_no_implicit_pack(self):
        data = load_batch(); data['excluded_card_ids'].remove('TIME_003')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'altered.json'; path.write_text(json.dumps(data), encoding='utf8')
            with patch.object(inventory, 'BATCH_PATH', path), self.assertRaises(TargetValidationError):
                load_batch()
        old = build_cn37_launch_candidate_format()
        with self.assertRaises(UnsupportedDefinitionError):
            old.registry.pool(POOL_ID, old.context)
        # Pool qualification is a format-bound manifest, not a global registry default.
        r, fmt = fixture()
        with self.assertRaises(UnsupportedDefinitionError):
            pack_candidates(r, GenerationContext(old.target_id, old.context.mode), r._standard_pack_profiles[CARD])
        self.assertNotIn(POOL_ID, load_bindings()['unresolved_pool_ids'])
        self.assertFalse(fmt.formal_pool_complete)

    def test_old_ordinary_and_reviewed_source_inventories_remain_unchanged(self):
        r, fmt = fixture(); original = build_cn37_launch_candidate_format()
        for pid in ('constructed.cards', 'constructed.minions'):
            old = original.registry.pool(pid, original.context); current = r.pool(pid, fmt.context)
            self.assertEqual((old.members, old.excluded_card_ids, old.complete),
                (current.members, current.excluded_card_ids, current.complete))
        previous = batch.read('data/cards/local-special-pool-bindings-v6.json')
        for item in previous['bindings']:
            old = r.pool(item['pool_id'], GenerationContext(item['source_target_id'], item['source_mode']))
            current = r.pool(item['pool_id'], fmt.context)
            self.assertEqual((old.members, old.excluded_card_ids), (current.members, current.excluded_card_ids))
        self.assertEqual(len(r.generation_scopes), 3)

    def test_local_complete_binding_needs_no_outputs_or_network_at_runtime(self):
        text_reader, byte_reader = Path.read_text, Path.read_bytes
        outputs = Path(__file__).resolve().parents[1] / 'outputs'
        def text(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outputs))
            return text_reader(path, *args, **kwargs)
        def binary(path, *args, **kwargs):
            self.assertFalse(path.resolve().is_relative_to(outputs))
            return byte_reader(path, *args, **kwargs)
        with patch.object(Path, 'read_text', text), patch.object(Path, 'read_bytes', binary), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected network')):
            fmt = build_cn37_local_pool_format()
        self.assertEqual(fmt.target_id, fixture()[1].target_id)


if __name__ == '__main__':
    unittest.main()
